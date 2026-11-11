# -*- coding: utf-8 -*-

import uuid
import re
import json
import logging
import math
from datetime import timedelta
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
    cancelled_amount = fields.Monetary(
        string="Cancelled Amount",
        currency_field="currency_id",
        readonly=True,
        copy=False,
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

    @api.depends(
        "state", "mobilepay_status", "provider_id.code", "authorized_amount",
        "captured_amount", "cancelled_amount", "source_transaction_id",
    )
    def _compute_capture_eligible(self):
        """Compute whether transaction is eligible for manual capture."""
        for transaction in self:
            transaction.capture_eligible = (
                transaction.provider_id.code == "mobilepay"
                and transaction.state == "authorized"
                and not transaction.source_transaction_id
                and transaction.mobilepay_status in ["RESERVED", "AUTHORIZED", "PARTIALLY_CAPTURED"]
                and transaction.currency_id.compare_amounts(
                    transaction.authorized_amount,
                    transaction.captured_amount + transaction.cancelled_amount,
                ) > 0
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

        MobilePay returns amount objects with a 'value' field in minor units (øre).
        This helper extracts the value and converts it to DKK.
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

        # MobilePay API always returns amounts in minor units (øre for DKK).
        # Convert to major units (DKK) by dividing by 100.
        return amount_value / 100.0

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
        """Normalize international or customer-country local numbers for the API."""
        if not phone_number:
            return None
        if not isinstance(phone_number, str) or not re.fullmatch(r"\+?[0-9\s().-]+", phone_number.strip()):
            return None

        digits_only = re.sub(r"\D", "", phone_number)
        international = phone_number.strip().startswith("+") or digits_only.startswith("00")
        if digits_only.startswith("00"):
            digits_only = digits_only[2:]

        if not international:
            country = (
                self.partner_country_id.code
                or self.company_id.country_id.code
                or self.provider_id.mobilepay_sales_unit_region
            )
            if country in ("DK", "FO", "NO") and len(digits_only) == 8:
                digits_only = ("47" if country == "NO" else "45") + digits_only
            elif country in ("FI", "SE") and digits_only.startswith("0"):
                digits_only = ("358" if country == "FI" else "46") + digits_only[1:]
            elif country == "GL" and len(digits_only) == 6:
                digits_only = "299" + digits_only
        return digits_only if re.fullmatch(r"[1-9][0-9]{8,14}", digits_only) else None

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

        if self.currency_id.name != self.provider_id._mobilepay_currency_code():
            raise UserError(_(
                "The payment currency must be %(currency)s for the configured sales unit region.",
                currency=self.provider_id._mobilepay_currency_code(),
            ))

        # Prepare payment data according to ePayment V3 API specifications
        # Ensure reference is consistent (min 8 chars) between payload and returnUrl
        api_reference = self.reference
        if len(api_reference) < 8:
            api_reference = f"{api_reference}-TX{self.id}"
            api_reference = re.sub(r"[^a-zA-Z0-9-]", "", api_reference)

        # Generate idempotency key if not already set
        if not self.mobilepay_idempotency_key:
            self.mobilepay_idempotency_key = self._generate_idempotency_key(api_reference)

        # Convert amount to minor units (øre/cents)
        amount_ore = self._convert_dkk_to_ore(self.amount)

        # Format customer phone number
        # Priority: 1. Context (from checkout form), 2. Partner phone, 3. Partner mobile
        raw_phone = self.env.context.get("mobilepay_phone")
        if "mobilepay_phone" not in self.env.context and self.partner_id:
            raw_phone = self.partner_id.phone or self.partner_id.mobile

        customer_phone = self._format_phone_number_v3(raw_phone) if raw_phone else None
        if raw_phone and not customer_phone:
            raise UserError(_("Please enter a valid Vipps or MobilePay phone number with country code."))

        # Rewriting the scheme cannot provide TLS for an HTTP-only deployment.
        base_url = self.provider_id.get_base_url().rstrip("/")
        from urllib.parse import urlparse
        parsed_base = urlparse(base_url)
        if parsed_base.scheme != "https" or not parsed_base.netloc:
            raise UserError(_(
                "MobilePay requires a reachable HTTPS website URL for payment returns. "
                "Configure HTTPS and the website domain/base URL before starting a payment. "
                "Changing http to https without a TLS endpoint does not work."
            ))

        payment_data = {
            "amount": {
                "currency": self.currency_id.name or "DKK",
                "value": amount_ore,
            },
            "reference": api_reference,
            "userFlow": "WEB_REDIRECT",
            "returnUrl": f"{base_url}/payment/mobilepay/return?reference={api_reference}",
            "paymentMethod": {
                "type": "WALLET",
            },
            "paymentDescription": self._mobilepay_build_payment_description(),
        }

        # Add receipt / order lines if available
        receipt = self._mobilepay_build_receipt()
        if receipt:
            payment_data["receipt"] = receipt

        # Add customer information if available
        if self.partner_id:
            # Strictly clean names for portal compatibility but allow spaces
            customer_name = re.sub(r"[^a-zA-Z0-9 ]", "", self.partner_id.name or "")
            customer_data = {
                "name": customer_name[:50],
                "email": self.partner_id.email or "",
            }

            if customer_phone:
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

        try:
            # Send payment request via API client
            api_client = self.env["mobilepay.api.client"]
            response_data = api_client.create_payment(
                self.provider_id,
                payment_data,
                idempotency_key=self.mobilepay_idempotency_key,
            )

            self.mobilepay_api_reference = response_data.get("reference") or api_reference

            # Set the standard Odoo provider reference field used by payment views
            # and accounting flows. Prefer the MobilePay API reference, then the
            # payment ID as a fallback.
            self.provider_reference = (
                self.mobilepay_api_reference
                or response_data.get("paymentId")
                or api_reference
            )

            # Store MobilePay payment info
            # In Merchant Test (MT) or some V3 environments, paymentId might be missing from body.
            # Priority: 1. paymentId (if body has it) 2. reference (for MT environment polling)
            self.mobilepay_payment_id = (
                response_data.get("paymentId") or self.mobilepay_api_reference
            )

            _logger.info(
                f"MobilePay Initiation for {self.reference}: Stored ID {self.mobilepay_payment_id}, provider ref {self.provider_reference}"
            )
            self.authorized_amount = self.amount

            # Update transaction state
            self._set_pending()

            return response_data

        except Exception as e:
            _logger.error(
                f"MobilePay payment initiation failed for transaction {self.reference}: {str(e)}"
            )
            self._set_error(_("Payment initiation failed: %s") % str(e))
            raise UserError(_("Payment initiation failed: %s") % str(e))

        return f"{self.provider_id.get_base_url()}/payment/mobilepay/return?reference={self.reference}"

    def _set_authorized(self, state_message=None, extra_allowed_states=(), **kwargs):
        """Override to ensure standard compatibility and MRO propagation."""
        return super()._set_authorized(
            state_message=state_message,
            extra_allowed_states=extra_allowed_states,
            **kwargs
        )


    def _mobilepay_get_payment_status(self):
        """
        Poll MobilePay API for current payment status and fetch the event log.
        The event log is written to the chatter for support traceability.

        Returns:
            dict: Payment status data
        """
        self.ensure_one()
        if self.provider_id.code != "mobilepay" or not self.mobilepay_api_reference:
            return None
        if self.source_transaction_id:
            return self.source_transaction_id._mobilepay_get_payment_status()

        try:
            self._mobilepay_lock_payment()
            api_client = self.env["mobilepay.api.client"]
            status_data = api_client.get_payment_status(
                self.provider_id, self.mobilepay_api_reference
            )

            _logger.info(
                "MobilePay status poll result for %s: %s",
                self.mobilepay_api_reference,
                json.dumps(status_data),
            )

            # Normalize status from either Vipps 'status' or 'state'
            raw_status = status_data.get("status") or status_data.get("state")
            # The ePayment API returns 'state' as an array (e.g. ["AUTHORIZED"]).
            # Normalize to a plain string.
            if isinstance(raw_status, list):
                raw_status = raw_status[0] if raw_status else None

            # Update status field and timestamp
            self.write(
                {
                    "mobilepay_status": raw_status,
                    "last_status_poll": fields.Datetime.now(),
                }
            )

            # Process the status update
            self._mobilepay_process_status(status_data)

            # Fetch and log the payment event log for support traceability.
            # Errors here are non-fatal — status update already succeeded above.
            try:
                self._mobilepay_fetch_and_log_events()
            except Exception as e:
                _logger.warning(
                    "MobilePay: Could not fetch event log for %s: %s",
                    self.reference, str(e),
                )

            return status_data

        except Exception as e:
            _logger.error(
                f"Failed to poll status for transaction {self.reference}: {str(e)}"
            )
            return None

    def _mobilepay_chatter_post(self, body):
        """
        Post a note to the transaction chatter when mail.thread is available
        (Odoo Enterprise or mail module installed), otherwise fall back to
        _logger so the message is still captured in server logs on CE.
        """
        if hasattr(self, "message_post"):
            try:
                self.message_post(
                    body=body,
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )
                return
            except Exception:
                pass
        # CE fallback: strip HTML tags for clean log output
        import re as _re
        plain = _re.sub(r"<[^>]+>", " ", body).strip()
        _logger.info("MobilePay [%s]: %s", self.reference, plain)

    def _mobilepay_fetch_and_log_events(self):
        """
        Fetch the payment event log from MobilePay and post new events to the
        transaction chatter. This satisfies the checklist requirement to integrate
        GET /epayment/v1/payments/{reference}/events and makes the full payment
        history available to support staff directly in Odoo.

        Only events not already logged are posted, so repeated calls are idempotent.
        """
        self.ensure_one()
        if not self.mobilepay_api_reference:
            return

        api_client = self.env["mobilepay.api.client"]
        events = api_client.get_payment_events(
            self.provider_id, self.mobilepay_api_reference
        )

        if not events or not isinstance(events, list):
            return

        # Collect idempotency keys already logged to avoid duplicates.
        # message_ids is only available when mail.thread is in the MRO
        # (Enterprise or mail module installed); fall back to empty set on CE.
        existing_keys = set()
        if hasattr(self, "message_ids"):
            for msg in self.message_ids:
                body = msg.body or ""
                for line in body.split("\n"):
                    if line.startswith("Key:"):
                        existing_keys.add(line.split(":", 1)[1].strip())

        for event in events:
            ikey = event.get("idempotencyKey") or ""
            if ikey and ikey in existing_keys:
                continue  # already logged

            name = event.get("name", "UNKNOWN")
            timestamp = event.get("timestamp", "")
            success = event.get("success", True)
            amount_data = event.get("amount", {})
            amount_str = ""
            if amount_data:
                value = amount_data.get("value", 0)
                currency = amount_data.get("currency", "DKK")
                amount_str = f"{value / 100:.2f} {currency}"

            status_icon = "✅" if success else "❌"
            lines = [
                _("%(icon)s <b>MobilePay Event: %(name)s</b>", icon=status_icon, name=name),
                _("Time: %(timestamp)s", timestamp=timestamp),
            ]
            if amount_str:
                lines.append(_("Amount: %(amount)s", amount=amount_str))
            if ikey:
                lines.append(_("Key: %(key)s", key=ikey))

            self._mobilepay_chatter_post(
                body="<br/>".join(lines),
            )
            _logger.info(
                "MobilePay event logged for %s: %s at %s (success=%s)",
                self.reference, name, timestamp, success,
            )

    def action_fetch_mobilepay_event_log(self):
        """
        Manual action: fetch and display the MobilePay payment event log.
        Called from the transaction form view button for support use.
        """
        self.ensure_one()
        if self.provider_id.code != "mobilepay":
            raise UserError(_("This is not a MobilePay transaction."))
        if not self.mobilepay_api_reference:
            raise UserError(_("No MobilePay API Reference found on this transaction."))

        self._mobilepay_fetch_and_log_events()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Event Log Fetched"),
                "message": _("MobilePay payment events have been fetched and added to the chatter."),
                "type": "success",
                "sticky": False,
            },
        }

    def _mobilepay_process_status(self, status_data):
        """
        Process payment status from MobilePay and update Odoo transaction state.

        Args:
            status_data (dict): Payment status data from API
        """
        status = status_data.get("status") or status_data.get("state")
        # The ePayment API returns 'state' as an array (e.g. ["AUTHORIZED"]).
        # Normalize to a plain string.
        if isinstance(status, list):
            status = status[0] if status else None
        if not status:
            _logger.warning(
                "MobilePay status poll returned no status for transaction %s: %s",
                self.reference,
                json.dumps(status_data),
            )
            return

        details = status_data.get("paymentDetails") or status_data.get("aggregate") or {}
        values = {"mobilepay_status": status}
        for remote, local in (
            ("authorizedAmount", "authorized_amount"),
            ("capturedAmount", "captured_amount"),
            ("refundedAmount", "refunded_amount"),
            ("cancelledAmount", "cancelled_amount"),
        ):
            if remote in details:
                values[local] = self._parse_mobilepay_amount(details[remote])
        self.write(values)

        # Vipps keeps state AUTHORIZED after captures and cancellations.
        if status in ["RESERVED", "AUTHORIZED"]:
            remaining = self.authorized_amount - self.captured_amount - self.cancelled_amount
            if self.currency_id.is_zero(remaining) and self.authorized_amount:
                if self.captured_amount:
                    self._set_done()
                else:
                    self._set_canceled()
            elif self.captured_amount:
                self.mobilepay_status = "PARTIALLY_CAPTURED"
                self._set_authorized()
            else:
                self._set_authorized()
        elif status == "CAPTURED":
            self._set_done()
        elif status in ["CANCELLED", "EXPIRED", "ABORTED", "TERMINATED"]:
            self._set_canceled()
        elif status == "REFUNDED":
            # A fully refunded payment stays in 'done' in Odoo but we update amounts below.
            # If the refunded amount equals the captured amount, move to canceled.
            pass
        else:
            _logger.warning(
                "MobilePay status '%s' is not mapped to an Odoo state for transaction %s",
                status,
                self.reference,
            )

    def _mobilepay_lock_payment(self):
        """Serialize modifications of the same remote payment, including its children."""
        self.ensure_one()
        root = self
        while root.source_transaction_id:
            root = root.source_transaction_id
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE", [root.id]
        )
        (root | self).invalidate_recordset()
        return root

    def _mobilepay_modification_amount(self, requested, remaining):
        amount = remaining if requested is None else requested
        if (
            not isinstance(amount, (int, float))
            or isinstance(amount, bool)
            or not math.isfinite(amount)
            or self.currency_id.compare_amounts(amount, 0) <= 0
            or self.currency_id.compare_amounts(amount, remaining) > 0
            or not math.isclose(amount, self.currency_id.round(amount), rel_tol=0, abs_tol=1e-9)
        ):
            raise UserError(_("The amount must be positive and cannot exceed the remaining amount."))
        return self.currency_id.round(amount)

    def _mobilepay_operation_key(self, operation, amount, processed):
        # Stable across a DB rollback or a lost HTTP response; distinct for the next operation.
        return self._generate_idempotency_key(
            f"{self.mobilepay_api_reference}:{self.id}:{operation}:"
            f"{self._convert_dkk_to_ore(processed)}:{self._convert_dkk_to_ore(amount)}"
        )

    def _mobilepay_check_modification(self, response, field, expected):
        aggregate = response.get("aggregate") if isinstance(response, dict) else None
        remote_amount = aggregate.get(field) if isinstance(aggregate, dict) else None
        if (
            not isinstance(remote_amount, dict)
            or remote_amount.get("currency") != self.currency_id.name
            or remote_amount.get("value") != self._convert_dkk_to_ore(expected)
        ):
            raise UserError(_(
                "MobilePay did not confirm the requested %(operation)s amount. "
                "Check the payment in the merchant portal before retrying.",
                operation=field,
            ))

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

        root = self._mobilepay_lock_payment()
        if root != self or not self.capture_eligible:
            raise UserError(_("This transaction is not eligible for capture."))
        if not self.mobilepay_api_reference:
            raise UserError(_("Missing MobilePay API Reference for capture."))
        remaining = self.authorized_amount - self.captured_amount - self.cancelled_amount
        amount = self._mobilepay_modification_amount(amount_to_capture, remaining)
        child = super()._send_capture_request(amount_to_capture=amount)
        response = self.env["mobilepay.api.client"].capture_payment(
            self.provider_id,
            self.mobilepay_api_reference,
            {"modificationAmount": {
                "currency": self.currency_id.name,
                "value": self._convert_dkk_to_ore(amount),
            }},
            idempotency_key=self._mobilepay_operation_key("capture", amount, self.captured_amount),
        )
        total = self.captured_amount + amount
        self._mobilepay_check_modification(response, "capturedAmount", total)
        self.write({
            "captured_amount": total,
            "mobilepay_status": "CAPTURED" if self.currency_id.is_zero(remaining - amount)
            else "PARTIALLY_CAPTURED",
        })
        capture_tx = child or self
        if child:
            child.write({
                "mobilepay_api_reference": self.mobilepay_api_reference,
                "mobilepay_payment_id": self.mobilepay_payment_id,
                "provider_reference": self.provider_reference,
                "captured_amount": amount,
                "mobilepay_status": "CAPTURED",
            })
        capture_tx._set_done()
        self.env.ref("payment.cron_post_process_payment_tx")._trigger()
        return child

    def _mobilepay_build_payment_description(self):
        """
        Build a human-readable payment description (3-100 chars) for the MobilePay app.
        Uses the sale order name if available, otherwise falls back to the transaction reference.
        """
        self.ensure_one()
        # Try to get the sale order name via the invoice/source document chain
        description = None
        sale_orders = self._get_sale_orders()
        if sale_orders:
            names = ", ".join(sale_orders.mapped("name"))
            description = names[:100]

        if not description:
            description = self.reference[:100]

        # API requires minimum 3 characters
        if len(description) < 3:
            description = description.ljust(3)

        return description

    def _mobilepay_build_receipt(self):
        """
        Build a receipt object with order lines for the MobilePay payment.
        Returns None if no sale order lines are available.
        The receipt improves the user experience in the MobilePay app and is
        required for merchants using Content monitoring.
        """
        self.ensure_one()
        sale_orders = self._get_sale_orders()
        if not sale_orders:
            return None

        order_lines = []
        for order in sale_orders:
            for line in order.order_line:
                if line.display_type:
                    # Skip section/note lines
                    continue
                # Clean product name — only alphanumeric and spaces allowed
                product_name = re.sub(r"[^a-zA-Z0-9 \-]", "", line.name or "")[:45]
                if not product_name:
                    product_name = "Product"
                unit_info = {}
                if line.product_uom:
                    unit_info["unitOfMeasurement"] = line.product_uom.name[:20]
                order_lines.append({
                    "name": product_name,
                    "id": str(line.id),
                    "totalAmount": self._convert_dkk_to_ore(line.price_total),
                    "totalAmountExcludingTax": self._convert_dkk_to_ore(line.price_subtotal),
                    "totalTaxAmount": self._convert_dkk_to_ore(
                        line.price_total - line.price_subtotal
                    ),
                    "taxRate": int(round(line.tax_id[0].amount * 100)) if line.tax_id else 0,
                    "unitInfo": {
                        "unitPrice": self._convert_dkk_to_ore(line.price_unit),
                        "quantity": str(line.product_uom_qty),
                        **unit_info,
                    },
                })

        if not order_lines:
            return None

        # Bottom line: total amount and tax
        total_amount = self._convert_dkk_to_ore(self.amount)
        total_tax = sum(
            self._convert_dkk_to_ore(l.price_total - l.price_subtotal)
            for order in sale_orders
            for l in order.order_line
            if not l.display_type
        )

        return {
            "orderLines": order_lines,
            "bottomLine": {
                "currency": self.currency_id.name or "DKK",
                "tipAmount": 0,
                "posId": re.sub(r"[^a-zA-Z0-9]", "", self.provider_id.sudo().company_id.name or "Odoo")[:10],
            },
        }

    def _get_sale_orders(self):
        """Return sale orders linked to this transaction, if any."""
        self.ensure_one()
        # payment.transaction links to sale.order via sale_order_ids (Odoo 17)
        if hasattr(self, "sale_order_ids") and self.sale_order_ids:
            return self.sale_order_ids
        # Fallback: search by source document on invoices
        invoices = self.invoice_ids
        if invoices:
            sale_orders = invoices.mapped("invoice_line_ids.sale_line_ids.order_id")
            if sale_orders:
                return sale_orders
        return self.env["sale.order"].browse()

    def _mobilepay_retry_poll_status(self):
        """
        Retry status polling for draft/pending transactions within the 5-minute window.
        Also polls authorized transactions to catch any missed webhooks.
        Called by cron.
        """
        status_timeout_min = 5

        for tx in self:
            if tx.provider_id.code != "mobilepay" or tx.source_transaction_id:
                continue

            if tx.state in ["draft", "pending"]:
                # Check if time elapsed < 5 minutes
                time_diff = fields.Datetime.now() - tx.create_date
                if time_diff.total_seconds() < (status_timeout_min * 60):
                    tx._mobilepay_get_payment_status()

            elif tx.state == "authorized":
                # Poll authorized transactions to catch missed webhooks and
                # keep the event log / amounts up to date.
                tx._mobilepay_get_payment_status()

    @api.model
    def _cron_mobilepay_auto_capture(self):
        transactions = self.search([
            ("provider_id.code", "=", "mobilepay"),
            ("provider_id.state", "in", ["test", "enabled"]),
            ("provider_id.capture_manually", "=", False),
            ("provider_id.capture_on_delivery", "=", False),
            ("source_transaction_id", "=", False),
            ("state", "=", "authorized"),
        ], order="last_state_change, id")
        now = fields.Datetime.now()
        for tx in transactions:
            due = tx.last_state_change + timedelta(hours=tx.provider_id.auto_capture_delay)
            if now < due:
                continue
            try:
                with self.env.cr.savepoint():
                    tx._send_capture_request()
            except UserError as error:
                _logger.warning("MobilePay delayed capture failed for %s: %s", tx.reference, error)
                tx._mobilepay_chatter_post(
                    body=_("MobilePay delayed capture failed: %s", str(error))
                )

    @api.model
    def _mobilepay_monitor_capture_expiry(self):
        """
        Cron: warn about authorized MobilePay transactions that are approaching
        the capture deadline (14 days for ePayment), and cancel those that have
        already passed it so the customer's funds are released.

        MobilePay ePayment reservations expire after 14 days.
        We warn at 12 days and cancel at 14 days.
        """
        from datetime import timedelta

        now = fields.Datetime.now()
        warn_threshold = now - timedelta(days=12)
        cancel_threshold = now - timedelta(days=14)

        authorized_txs = self.search([
            ("provider_id.code", "=", "mobilepay"),
            ("state", "=", "authorized"),
        ])

        for tx in authorized_txs:
            age = now - tx.create_date
            if tx.create_date <= cancel_threshold:
                # Reservation has expired — cancel it so funds are released
                _logger.warning(
                    "MobilePay: Transaction %s is %d days old and past capture deadline. Cancelling.",
                    tx.reference, age.days,
                )
                try:
                    tx._send_cancel_request()
                    tx._mobilepay_chatter_post(
                        body=_(
                            "MobilePay payment reservation expired after %(days)d days "
                            "and was automatically cancelled to release the customer's funds.",
                            days=age.days,
                        ),
                    )
                except Exception as e:
                    _logger.error(
                        "MobilePay: Failed to cancel expired transaction %s: %s",
                        tx.reference, str(e),
                    )
            elif tx.create_date <= warn_threshold:
                # Approaching deadline — post a warning note so someone acts
                # Only warn once (check if we already posted a warning)
                already_warned = any(
                    "capture deadline" in (msg.body or "")
                    for msg in (tx.message_ids if hasattr(tx, "message_ids") else [])
                )
                if not already_warned:
                    _logger.warning(
                        "MobilePay: Transaction %s is %d days old and approaching capture deadline.",
                        tx.reference, age.days,
                    )
                    tx._mobilepay_chatter_post(
                        body=_(
                            "⚠️ MobilePay payment %(ref)s has been authorized for %(days)d days "
                            "and is approaching the capture deadline (14 days). "
                            "Please capture or cancel this payment soon.",
                            ref=tx.reference,
                            days=age.days,
                        ),
                    )

    @api.model
    def _mobilepay_cancel_on_sale_order_cancel(self):
        """
        Cron: cancel MobilePay authorized transactions whose sale order has been
        cancelled, so the customer's reserved funds are released promptly.
        """
        authorized_txs = self.search([
            ("provider_id.code", "=", "mobilepay"),
            ("state", "=", "authorized"),
        ])

        for tx in authorized_txs:
            sale_orders = tx._get_sale_orders()
            if not sale_orders:
                continue
            # If ALL linked sale orders are cancelled, void the authorization
            if all(so.state == "cancel" for so in sale_orders):
                _logger.info(
                    "MobilePay: Sale order(s) %s cancelled — voiding authorization for %s",
                    sale_orders.mapped("name"), tx.reference,
                )
                try:
                    tx._send_cancel_request()
                    tx._mobilepay_chatter_post(
                        body=_(
                            "MobilePay payment authorization automatically cancelled "
                            "because the related sale order was cancelled.",
                        ),
                    )
                except Exception as e:
                    _logger.error(
                        "MobilePay: Failed to cancel transaction %s after order cancel: %s",
                        tx.reference, str(e),
                    )

    def _send_refund_request(self, amount_to_refund=None):
        """
        Send refund request to MobilePay API.

        Args:
            amount_to_refund (float): Amount to refund in DKK. Defaults to full amount.

        Returns:
            payment.transaction: The negative refund child transaction.
        """
        self.ensure_one()
        if self.provider_id.code != "mobilepay":
            return super()._send_refund_request(amount_to_refund)

        root = self._mobilepay_lock_payment()
        if self.state != "done" or self.operation == "refund":
            raise UserError(_("Only confirmed transactions can be refunded."))
        if self.child_transaction_ids.filtered(
            lambda tx: tx.operation == self.operation and tx.state == "done"
        ):
            raise UserError(_("Refund the individual captured transactions, not their source."))
        if not root.mobilepay_api_reference:
            raise UserError(_("Missing MobilePay API Reference for refund."))
        remaining = min(
            self.captured_amount - self.refunded_amount,
            root.captured_amount - root.refunded_amount,
        )
        amount = self._mobilepay_modification_amount(amount_to_refund, remaining)
        refund_tx = super()._send_refund_request(amount_to_refund=amount)
        response = self.env["mobilepay.api.client"].refund_payment(
            self.provider_id,
            root.mobilepay_api_reference,
            {"modificationAmount": {
                "currency": self.currency_id.name,
                "value": self._convert_dkk_to_ore(amount),
            }},
            idempotency_key=self._mobilepay_operation_key("refund", amount, self.refunded_amount),
        )
        total = root.refunded_amount + amount
        self._mobilepay_check_modification(response, "refundedAmount", total)
        self.refunded_amount += amount
        if root != self:
            root.refunded_amount = total
        if self.currency_id.is_zero(root.captured_amount - total):
            root.mobilepay_status = "REFUNDED"
        refund_tx.write({
            "mobilepay_api_reference": root.mobilepay_api_reference,
            "mobilepay_payment_id": root.mobilepay_payment_id,
            "provider_reference": root.provider_reference,
            "refunded_amount": amount,
            "mobilepay_status": "REFUNDED",
        })
        refund_tx._set_done()
        self.env.ref("payment.cron_post_process_payment_tx")._trigger()
        return refund_tx

    def _send_cancel_request(self):
        """Compatibility entry point used by delivery/order/expiry integrations."""
        return self._send_void_request()

    def _send_void_request(self, amount_to_void=None):
        self.ensure_one()
        if self.provider_id.code != "mobilepay":
            return super()._send_void_request(amount_to_void=amount_to_void)
        root = self._mobilepay_lock_payment()
        if root != self or self.state not in ("draft", "pending", "authorized"):
            raise UserError(_("Only open MobilePay authorizations can be cancelled."))
        if not self.mobilepay_api_reference:
            raise UserError(_("Missing MobilePay API Reference for cancellation."))
        remaining = self.authorized_amount - self.captured_amount - self.cancelled_amount
        if self.state == "authorized":
            amount = self._mobilepay_modification_amount(amount_to_void, remaining)
            if self.currency_id.compare_amounts(amount, remaining):
                raise UserError(_("MobilePay can only cancel the entire remaining reservation."))
        else:
            amount = self.amount
        child = super()._send_void_request(amount_to_void=amount)
        response = self.env["mobilepay.api.client"].cancel_payment(
            self.provider_id,
            self.mobilepay_api_reference,
            idempotency_key=self._mobilepay_operation_key("cancel", amount, self.cancelled_amount),
        )
        if self.state == "authorized":
            self._mobilepay_check_modification(
                response, "cancelledAmount", self.cancelled_amount + amount
            )
        elif not isinstance(response, dict) or response.get("state") != "TERMINATED":
            raise UserError(_("MobilePay did not confirm cancellation of the pending payment."))
        self.write({
            "cancelled_amount": self.cancelled_amount + amount,
            "mobilepay_status": "CAPTURED" if self.captured_amount else "CANCELLED",
        })
        void_tx = child or self
        if child:
            child.write({
                "mobilepay_api_reference": self.mobilepay_api_reference,
                "mobilepay_payment_id": self.mobilepay_payment_id,
                "provider_reference": self.provider_reference,
                "cancelled_amount": amount,
                "mobilepay_status": "CANCELLED",
            })
        void_tx._set_canceled()
        self.env.ref("payment.cron_post_process_payment_tx")._trigger()
        return child

    def _get_specific_rendering_values(self, processing_values):
        """Override to provide MobilePay-specific rendering values."""
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
            "api_url": parsed_url._replace(query="").geturl(),
            "redirect_params": parse_qsl(parsed_url.query, keep_blank_values=True),
        }

        return {**res, **mobilepay_values}
