# -*- coding: utf-8 -*-

import uuid
import re
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

    @api.depends("state", "mobilepay_status", "provider_id.code")
    def _compute_capture_eligible(self):
        """Compute whether transaction is eligible for manual capture."""
        for transaction in self:
            transaction.capture_eligible = (
                transaction.provider_id.code == "mobilepay"
                and transaction.state == "authorized"
                and transaction.mobilepay_status == "RESERVED"
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

    def _generate_idempotency_key(self):
        """
        Generate unique idempotency key for MobilePay API requests.

        Returns:
            str: Unique idempotency key
        """
        return str(uuid.uuid4())

    def _format_phone_number_e164(self, phone_number):
        """
        Format phone number to E.164 format for MobilePay API.

        Args:
            phone_number (str): Phone number in various formats

        Returns:
            str: Phone number in E.164 format (+45XXXXXXXX) or None if invalid
        """
        if not phone_number:
            return None

        # Remove all non-digit characters except leading plus
        digits_only = re.sub(r"(?!^\+)\D", "", phone_number)

        # If it already starts with + and has a reasonable length, assume it's E.164
        if digits_only.startswith("+") and 10 <= len(digits_only) <= 15:
            return digits_only

        # Handle Danish phone numbers specifically if only 8 or 10 digits
        if len(digits_only) == 8:
            # Add Danish country code
            return f"+45{digits_only}"
        elif digits_only.startswith("45") and len(digits_only) == 10:
            # Already has country code but missing plus
            return f"+{digits_only}"
        elif digits_only.startswith("0045") and len(digits_only) == 12:
            # Remove leading 00 and add +
            return f"+{digits_only[2:]}"

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

        # Generate idempotency key if not already set
        if not self.mobilepay_idempotency_key:
            self.mobilepay_idempotency_key = self._generate_idempotency_key()

        # Convert amount to øre
        amount_ore = self._convert_dkk_to_ore(self.amount)

        # Format customer phone number if available
        customer_phone = None
        if self.partner_phone:
            customer_phone = self._format_phone_number_e164(self.partner_phone)
        elif self.partner_id and self.partner_id.phone:
            customer_phone = self._format_phone_number_e164(self.partner_id.phone)
        elif self.partner_id and self.partner_id.mobile:
            customer_phone = self._format_phone_number_e164(self.partner_id.mobile)

        # Prepare payment data
        payment_data = {
            "amount": amount_ore,
            "paymentPointId": self.provider_id.mobilepay_merchant_serial,
            "redirectUri": self._get_landing_route(),
            "reference": self.reference,
            "userFlow": "WEB_REDIRECT",
            "paymentMethod": "MobilePay",
        }

        # Add customer information if available
        if self.partner_id:
            customer_data = {
                "name": self.partner_id.name or "",
                "email": self.partner_id.email or "",
            }

            if customer_phone:
                customer_data["phoneNumber"] = customer_phone

            payment_data["customer"] = customer_data

        # Add merchant information
        payment_data["merchantInfo"] = {
            "merchantContactUrl": self.provider_id.company_id.website or "",
            "merchantName": self.provider_id.company_id.name or "Odoo Store",
        }

        try:
            # Send payment request via API client
            api_client = self.env["mobilepay.api.client"]
            response_data = api_client.create_payment(
                self.provider_id,
                payment_data,
                idempotency_key=self.mobilepay_idempotency_key,
            )

            # Store MobilePay payment ID
            self.mobilepay_payment_id = response_data.get("paymentId")
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

    def _get_landing_route(self):
        """
        Get the landing route URL for payment return.

        Returns:
            str: Complete URL for payment return
        """
        base_url = self.provider_id.get_base_url()
        return f"{base_url}/payment/mobilepay/return?reference={self.reference}"

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

            # Update status field and timestamp
            self.write(
                {
                    "mobilepay_status": status_data.get("status"),
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
        status = status_data.get("status")
        if not status:
            return

        # Map MobilePay status to Odoo state
        if status == "RESERVED":
            self._set_authorized()
        elif status == "CAPTURED":
            self._set_done()
        elif status in ["CANCELLED", "EXPIRED", "ABORTED"]:
            self._set_canceled()

        # Update captured/refunded amounts if present
        details = status_data.get("paymentDetails", {})
        if details:
            vals = {}
            if "capturedAmount" in details:
                vals["captured_amount"] = self._convert_ore_to_dkk(
                    details["capturedAmount"]
                )
            if "refundedAmount" in details:
                vals["refunded_amount"] = self._convert_ore_to_dkk(
                    details["refundedAmount"]
                )

            if vals:
                self.write(vals)

    def action_capture(self):
        """
        Capture the authorized payment.

        Returns:
            dict: The result of the capture operation
        """
        self.ensure_one()
        if self.provider_id.code != "mobilepay":
            return super().action_capture()

        if not self.capture_eligible:
            raise UserError(_("This transaction is not eligible for capture."))

        # Amount to capture (in øre)
        amount_ore = self._convert_dkk_to_ore(self.amount)

        capture_data = {
            "amount": amount_ore,
            "description": f"Capture for {self.reference}",
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
            self._set_done()
            self.write({"captured_amount": self.amount, "mobilepay_status": "CAPTURED"})

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
            if tx.provider_id.code != "mobilepay" or tx.state not in ["draft", "pending"]:
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
            "amount": amount_ore,
            "description": f"Refund for {self.reference}",
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
            self._set_canceled()

            return response

        except Exception as e:
            _logger.error(f"Failed to cancel transaction {self.reference}: {str(e)}")
            raise UserError(_("Cancellation failed: %s") % str(e))

    def _get_specific_rendering_values(self, processing_values):
        """Override to provide MobilePay-specific rendering values."""
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_id.code != "mobilepay":
            return res

        # Initiate payment with MobilePay to get the redirect URL
        payment_response = self._send_payment_request()

        mobilepay_values = {
            "api_url": payment_response.get("redirectUrl"),
        }

        return {**res, **mobilepay_values}
