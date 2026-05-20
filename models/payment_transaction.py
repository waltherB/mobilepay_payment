# -*- coding: utf-8 -*-

import uuid
import re
import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    show_mobilepay_fields = fields.Boolean(compute="_compute_show_mobilepay_fields")

    @api.depends("provider_id.code")
    def _compute_show_mobilepay_fields(self):
        for tx in self:
            tx.show_mobilepay_fields = tx.provider_id.code == "mobilepay"

    # MobilePay Integration Fields
    mobilepay_payment_id = fields.Char(
        string="MobilePay Payment ID",
        help="Unique payment identifier from MobilePay API",
        readonly=True,
    )
    mobilepay_idempotency_key = fields.Char(
        string="Idempotency Key",
        help="Unique key to prevent duplicate payments",
        readonly=True,
    )
    mobilepay_status = fields.Char(
        string="MobilePay Status",
        help="Current payment status from MobilePay API",
        readonly=True,
    )
    mobilepay_api_reference = fields.Char(
        string="MobilePay API Reference",
        help="The unique reference used in the MobilePay API calls",
        readonly=True,
        index=True,
    )

    # Capture Management
    authorized_amount = fields.Monetary(
        string="Authorized Amount",
        help="Amount authorized by MobilePay",
        currency_field="currency_id",
        readonly=True,
    )
    captured_amount = fields.Monetary(
        string="Captured Amount",
        help="Amount captured from authorized payment",
        currency_field="currency_id",
        readonly=True,
    )
    refunded_amount = fields.Monetary(
        string="Refunded Amount",
        help="Total amount refunded for this transaction",
        currency_field="currency_id",
        readonly=True,
    )

    # Status Tracking
    last_status_poll = fields.Datetime(
        string="Last Status Poll",
        help="Timestamp of last status check with MobilePay API",
        readonly=True,
    )
    capture_eligible = fields.Boolean(
        string="Eligible for Capture",
        help="Whether this transaction can be manually captured",
        compute="_compute_capture_eligible",
        store=False,
    )

    @api.depends("state", "mobilepay_status", "provider_id.code", "authorized_amount")
    def _compute_capture_eligible(self):
        """Compute whether transaction is eligible for manual capture."""
        for transaction in self:
            transaction.capture_eligible = (
                transaction.provider_id.code == "mobilepay"
                and transaction.state == "authorized"
                and transaction.mobilepay_status in ["RESERVED", "AUTHORIZED"]
                and transaction.authorized_amount > 0
            )

    def _convert_dkk_to_ore(self, amount_dkk):
        """
        Convert DKK amount to øre for MobilePay API.

        Args:
            amount_dkk (float): Amount in DKK

        Returns:
            int: Amount in øre (DKK * 100)
        """
        if not amount_dkk:
            return 0
        return int(round(amount_dkk * 100))

    def _convert_ore_to_dkk(self, amount_ore):
        """
        Convert øre amount to DKK from MobilePay API.

        Args:
            amount_ore (int): Amount in øre

        Returns:
            float: Amount in DKK (øre / 100)
        """
        if not amount_ore:
            return 0.0
        return float(amount_ore) / 100.0

    def _parse_mobilepay_amount(self, amount_data):
        """
        Parse a MobilePay amount payload into DKK.

        MobilePay may return a plain integer amount in øre, or a nested object
        with currency/value fields. This helper tries to infer the unit used.
        """
        if not amount_data:
            return 0.0

        if isinstance(amount_data, dict):
            amount_value = amount_data.get("value")
        else:
            amount_value = amount_data

        try:
            amount_value = float(amount_value)
        except (TypeError, ValueError):
            return 0.0

        if self.amount and abs(amount_value - float(self.amount) * 100) < 0.01:
            return amount_value / 100.0

        if amount_value >= 1000:
            return amount_value / 100.0

        return amount_value

    def _generate_idempotency_key(self, api_reference=None):
        """
        Generate unique idempotency key for MobilePay API requests.
        If an api_reference is provided, generate a deterministic UUID.

        Args:
            api_reference (str, optional): The checkout reference.

        Returns:
            str: Unique idempotency key
        """
        if api_reference:
            return str(uuid.uuid5(uuid.NAMESPACE_OID, str(api_reference)))
        return str(uuid.uuid4())

    def _format_phone_number_v3(self, phone_number):
        """
        Format phone number for MobilePay V3 API (digits only, 9-15 chars).

        Args:
            phone_number (str): Phone number in various formats

        Returns:
            str: Phone number in digits only (45XXXXXXXX) or None if invalid
        """
        if not phone_number:
            return None

        # Remove all non-digit characters
        digits_only = re.sub(r"\D", "", phone_number)

        # Handle Danish phone numbers specifically
        if len(digits_only) == 8:
            # Add Danish country code (digits only)
            return f"45{digits_only}"
        elif digits_only.startswith("0045") and len(digits_only) == 12:
            # Remove leading 00
            return digits_only[2:]
        elif digits_only.startswith("45") and len(digits_only) == 10:
            # Already has country code
            return digits_only

        # Validate digits only (9-15 digits) as per API regex ^\d{9,15}$
        if 9 <= len(digits_only) <= 15:
            return digits_only

        return None

        return None

    def _send_payment_request(self):
        """
        Send payment request to MobilePay API.

        Returns:
            dict: Payment response data from MobilePay API

        Raises:
            UserError: If payment initiation fails
        """
        self.ensure_one()

        if self.provider_id.code != "mobilepay":
            return super()._send_payment_request()

        # Prepare payment data according to ePayment V3 API specifications
        # Ensure reference is consistent (min 8 chars) between payload and returnUrl
        api_reference = self.reference
        if len(api_reference) < 8:
            api_reference = f"{api_reference}-TX{self.id}"
            api_reference = re.sub(r"[^a-zA-Z0-9-]", "", api_reference)

        # Generate idempotency key if not already set
        if not self.mobilepay_idempotency_key:
            self.mobilepay_idempotency_key = self._generate_idempotency_key(api_reference)

        # Convert amount to øre
        amount_ore = self._convert_dkk_to_ore(self.amount)

        # Format customer phone number
        # Priority: 1. Context (from checkout form), 2. Partner phone, 3. Partner mobile
        raw_phone = self.env.context.get("mobilepay_phone")
        if not raw_phone and self.partner_id:
            raw_phone = self.partner_id.phone or self.partner_id.mobile

        customer_phone = self._format_phone_number_v3(raw_phone) if raw_phone else None

        _logger.info(
            f"Initiating MobilePay payment for transaction {self.reference}. Phone: {customer_phone}"
        )

        # Prepare returnUrl (MobilePay V3 requires HTTPS)
        base_url = self.provider_id.get_base_url().rstrip("/")
        if base_url.startswith("http://"):
            _logger.info(
                "MobilePay: Forcing HTTPS for returnUrl as per V3 requirements"
            )
            base_url = base_url.replace("http://", "https://", 1)

        payment_data = {
            "amount": {
                "currency": "DKK",
                "value": amount_ore,
            },
            "reference": api_reference,
            "userFlow": "WEB_REDIRECT",
            "returnUrl": f"{base_url}/payment/mobilepay/return?reference={api_reference}",
            "paymentMethod": {
                "type": "WALLET",
            },
        }

        # Add customer information if available
        if self.partner_id:
            # Strictly clean names for portal compatibility but allow spaces
            customer_name = re.sub(r"[^a-zA-Z0-9 ]", "", self.partner_id.name or "")
            customer_data = {
                "name": customer_name[:50],
                "email": self.partner_id.email or "",
            }

            # Only send phone number in production to avoid MT landing page crashes with unregistered test numbers
            if customer_phone and self.provider_id.state == "enabled":
                customer_data["phoneNumber"] = customer_phone

            payment_data["customer"] = customer_data

        # Add merchant information
        merchant_url = self.provider_id.sudo().company_id.website or base_url
        # If website is dummy or missing, use the system base URL (forced to https)
        if not merchant_url or "example.com" in merchant_url:
            merchant_url = base_url

        if merchant_url.startswith("http://"):
            merchant_url = merchant_url.replace("http://", "https://", 1)

        # Clean merchant name strictly but allow spaces
        merchant_name = re.sub(
            r"[^a-zA-Z0-9 ]",
            "",
            self.provider_id.sudo().company_id.name or "Odoo Store",
        )

        payment_data["merchantInfo"] = {
            "merchantContactUrl": merchant_url,
            "merchantName": merchant_name[:50],
        }

        _logger.info(
            f"MobilePay Final Payload for {self.reference}: {json.dumps(payment_data)}"
        )

        try:
            # Send payment request via API client
            api_client = self.env["mobilepay.api.client"]
            response_data = api_client.create_payment(
                self.provider_id,
                payment_data,
                idempotency_key=self.mobilepay_idempotency_key,
            )

            self.mobilepay_api_reference = response_data.get("reference")

            # Store MobilePay payment info
            # In Merchant Test (MT) or some V3 environments, paymentId might be missing from body.
            # Priority: 1. paymentId (if body has it) 2. reference (for MT environment polling)
            self.mobilepay_payment_id = (
                response_data.get("paymentId") or self.mobilepay_api_reference
            )

            _logger.info(
                f"MobilePay Initiation for {self.reference}: Stored ID {self.mobilepay_payment_id}"
            )
            self.authorized_amount = self.amount

            # Update transaction state
            self._set_pending()

            return response_data

        except Exception as e:
            _logger.error(
                f"MobilePay payment initiation failed for transaction {self.reference}: {str(e)}"
            )
            self._set_error(f"Payment initiation failed: {str(e)}")
            raise UserError(_("Payment initiation failed: %s") % str(e))

        return f"{self.provider_id.get_base_url()}/payment/mobilepay/return?reference={self.reference}"

    def _set_authorized(self, **kwargs):
        """Override to ensure capture_manually is respected for MobilePay."""
        for tx in self:
            if tx.provider_code == "mobilepay" and tx.provider_id.capture_on_delivery:
                tx.capture_manually = True
        return super()._set_authorized(**kwargs)


    def _mobilepay_get_payment_status(self):
        """
        Poll MobilePay API for current payment status.

        Returns:
            dict: Payment status data
        """
        self.ensure_one()
        if self.provider_id.code != "mobilepay" or not self.mobilepay_payment_id:
            return None

        try:
            api_client = self.env["mobilepay.api.client"]
            status_data = api_client.get_payment_status(
                self.provider_id, self.mobilepay_payment_id
            )

            _logger.info(
                "MobilePay status poll result for %s: %s",
                self.mobilepay_payment_id,
                json.dumps(status_data),
            )

            # Normalize status from either Vipps 'status' or 'state'
            raw_status = status_data.get("status") or status_data.get("state")

            # Update status field and timestamp
            self.write(
                {
                    "mobilepay_status": raw_status,
                    "last_status_poll": fields.Datetime.now(),
                }
            )

            # Process the status update
            self._mobilepay_process_status(status_data)

            return status_data

        except Exception as e:
            _logger.error(
                f"Failed to poll status for transaction {self.reference}: {str(e)}"
            )
            return None

    def _mobilepay_process_status(self, status_data):
        """
        Process payment status from MobilePay and update Odoo transaction state.

        Args:
            status_data (dict): Payment status data from API
        """
        status = status_data.get("status") or status_data.get("state")
        if not status:
            _logger.warning(
                "MobilePay status poll returned no status for transaction %s: %s",
                self.reference,
                json.dumps(status_data),
            )
            return

        # Map MobilePay status to Odoo state
        if status in ["RESERVED", "AUTHORIZED"]:
            self._set_authorized()
        elif status == "CAPTURED":
            self._set_done()
        elif status in ["CANCELLED", "EXPIRED", "ABORTED", "TERMINATED"]:
            self._set_canceled()
        else:
            _logger.warning(
                "MobilePay status '%s' is not mapped to an Odoo state for transaction %s",
                status,
                self.reference,
            )

        # Update captured/refunded amounts if present
        details = status_data.get("paymentDetails", {}) or status_data.get("aggregate", {})
        if details:
            vals = {}
            if "capturedAmount" in details:
                vals["captured_amount"] = self._parse_mobilepay_amount(
                    details["capturedAmount"]
                )
            if "refundedAmount" in details:
                vals["refunded_amount"] = self._parse_mobilepay_amount(
                    details["refundedAmount"]
                )
            if "authorizedAmount" in details:
                vals["authorized_amount"] = self._parse_mobilepay_amount(
                    details["authorizedAmount"]
                )

            if vals:
                self.write(vals)

    def _send_capture_request(self, amount_to_capture=None):
        """
        Request the capture of the transaction.
        
        Args:
            amount_to_capture (float, optional): The amount to capture. If not set,
                                                the full transaction amount is captured.
        """
        self.ensure_one()
        if self.provider_id.code != "mobilepay":
            return super()._send_capture_request(amount_to_capture=amount_to_capture)

        if not self.capture_eligible:
            raise UserError(_("This transaction is not eligible for capture."))

        # Use amount_to_capture if provided, otherwise the full transaction amount
        capture_amount = amount_to_capture or self.amount

        # Amount to capture (in øre)
        amount_ore = self._convert_dkk_to_ore(capture_amount)

        capture_data = {
            "modificationAmount": {
                "currency": self.currency_id.name or "DKK",
                "value": amount_ore,
            },
        }

        try:
            api_client = self.env["mobilepay.api.client"]
            api_client.capture_payment(
                self.provider_id,
                self.mobilepay_payment_id,
                capture_data,
                idempotency_key=str(uuid.uuid4()),
            )

            # Update transaction state and amounts
            new_captured_amount = self.captured_amount + capture_amount
            # If fully captured (or close to it)
            if new_captured_amount >= self.authorized_amount - 0.01:
                self._set_done()
                self.write({
                    "captured_amount": new_captured_amount,
                    "mobilepay_status": "CAPTURED",
                })
            else:
                self.write({
                    "captured_amount": new_captured_amount,
                    "mobilepay_status": "PARTIALLY_CAPTURED",
                })

            return True

        except UserError as e:
            # Re-raise UserErrors from API client
            raise e
        except Exception as e:
            _logger.error(f"Failed to capture transaction {self.reference}: {str(e)}")
            raise UserError(_("Payment capture failed: %s") % str(e))

    def _mobilepay_retry_poll_status(self):
        """
        Retry status polling if within timeout window.
        Called by cron or automated action.
        """
        status_timeout_min = 5

        for tx in self:
            if tx.provider_id.code != "mobilepay" or tx.state not in [
                "draft",
                "pending",
            ]:
                continue

            # Check if time elapsed < 5 minutes
            time_diff = fields.Datetime.now() - tx.create_date
            if time_diff.total_seconds() < (status_timeout_min * 60):
                tx._mobilepay_get_payment_status()

    def _send_refund_request(self, amount_to_refund=None):
        """
        Send refund request to MobilePay API.

        Args:
            amount_to_refund (float): Amount to refund in DKK. Defaults to full amount.

        Returns:
            dict: Refund response data
        """
        self.ensure_one()
        if self.provider_id.code != "mobilepay":
            return super()._send_refund_request(amount_to_refund)

        if self.state != "done":
            raise UserError(_("Only confirmed transactions can be refunded."))

        if not self.mobilepay_payment_id:
            raise UserError(_("Missing MobilePay payment ID for refund."))

        # Calculate refund amount
        refund_amount = amount_to_refund or self.captured_amount

        # Validate refund amount
        remaining_amount = self.captured_amount - self.refunded_amount
        # Allow small float discrepancies if necessary, but DKK is usually 2 decimals
        if refund_amount > remaining_amount + 0.01:
            raise UserError(
                _(
                    "Refund amount (%(refund)s) cannot exceed remaining captured amount (%(remaining)s).",
                    refund=refund_amount,
                    remaining=remaining_amount,
                )
            )

        amount_ore = self._convert_dkk_to_ore(refund_amount)

        refund_data = {
            "modificationAmount": {
                "currency": self.currency_id.name or "DKK",
                "value": amount_ore,
            },
        }

        try:
            api_client = self.env["mobilepay.api.client"]
            response = api_client.refund_payment(
                self.provider_id,
                self.mobilepay_payment_id,
                refund_data,
                idempotency_key=str(uuid.uuid4()),
            )

            # Update refunded amount
            # Note: Odoo core usually handles state if we return a specific structure,
            # but for partial refunds we manage the amounts manually here to be safe and precise
            new_refunded_amount = self.refunded_amount + refund_amount
            self.write(
                {
                    "refunded_amount": new_refunded_amount,
                    # Update status if needed, but 'done' usually stays 'done' for partial refunds
                    # If fully refunded, we might set 'mobilepay_status' to 'REFUNDED'
                    "mobilepay_status": "REFUNDED"
                    if new_refunded_amount >= self.captured_amount
                    else self.mobilepay_status,
                }
            )

            return response

        except UserError as e:
            raise e
        except Exception as e:
            _logger.error(f"Failed to refund transaction {self.reference}: {str(e)}")
            raise UserError(_("Refund failed: %s") % str(e))

    def _send_cancel_request(self):
        """
        Send cancel request to MobilePay API (void operation).

        Returns:
            dict: Cancel response data
        """
        self.ensure_one()
        if self.provider_id.code != "mobilepay":
            return super()._send_cancel_request()

        if not self.mobilepay_payment_id:
            raise UserError(_("Missing MobilePay payment ID for cancellation."))

        try:
            api_client = self.env["mobilepay.api.client"]
            response = api_client.cancel_payment(
                self.provider_id,
                self.mobilepay_payment_id,
                idempotency_key=str(uuid.uuid4()),
            )

            # Update status
            self.write({"mobilepay_status": "CANCELLED"})
            # Log response for debugging
            _logger.info(f"API response (HTTP {response.status_code}): {response.text}")
            if response.status_code >= 400:
                _logger.error(f"API error response body: {response.text}")
            self._set_canceled()

            return response

        except Exception as e:
            _logger.error(f"Failed to cancel transaction {self.reference}: {str(e)}")
            raise UserError(_("Cancellation failed: %s") % str(e))

    def _get_specific_rendering_values(self, processing_values):
        """Override to provide MobilePay-specific rendering values."""
        _logger.warning("MOBILEPAY REDIRECT FIX IS LOADED AND RUNNING!")
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_id.code != "mobilepay":
            return res

        # Initiate payment with MobilePay to get the redirect URL
        # Use sudo() to ensure we can build the payload without ACL restrictions on related orders (guest checkout)
        payment_response = self.sudo()._send_payment_request()
        
        redirect_url = payment_response.get("redirectUrl")
        
        from urllib.parse import urlparse, parse_qsl
        parsed_url = urlparse(redirect_url)

        mobilepay_values = {
            "api_url": redirect_url.split("?")[0],
        }
        
        # Add all query parameters (like token) to rendering values
        for key, value in parse_qsl(parsed_url.query):
            mobilepay_values[key] = value
            
        _logger.warning("MOBILEPAY RENDER DICT: %s" % mobilepay_values)

        return {**res, **mobilepay_values}
