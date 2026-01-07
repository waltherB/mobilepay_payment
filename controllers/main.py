# -*- coding: utf-8 -*-

import hmac
import hashlib
import base64
import json
import logging
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MobilePayController(http.Controller):
    """Controller for MobilePay payment processing and webhooks."""

    @http.route(
        "/payment/mobilepay/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def mobilepay_webhook(self, **kwargs):
        """
        Handle MobilePay webhook notifications.
        Verifies signature and dispatches events to transaction processing.
        """
        # Get raw data and headers
        raw_data = request.httprequest.get_data()
        headers = request.httprequest.headers

        # Check required headers for Azure-style auth
        auth_header = headers.get("Authorization")
        content_hash_header = headers.get("x-ms-content-sha256")
        date_header = headers.get("x-ms-date")
        host_header = headers.get("Host")  # Host header is standard

        if not auth_header or not content_hash_header or not date_header:
            _logger.warning(
                "MobilePay Webhook: Missing required authentication headers"
            )
            raise Forbidden("Missing headers")

        try:
            data = json.loads(raw_data)
        except ValueError:
            _logger.warning("MobilePay Webhook: Invalid JSON payload")
            return "Invalid JSON"

        # Extract payment ID to find the transaction and provider
        event_data = data.get("data", {})
        payment_id = event_data.get("paymentId")

        if not payment_id:
            _logger.warning("MobilePay Webhook: Missing paymentId in event data")
            return "OK"

        # Find transaction
        tx_sudo = (
            request.env["payment.transaction"]
            .sudo()
            .search(
                [
                    ("mobilepay_payment_id", "=", payment_id),
                    ("provider_code", "=", "mobilepay"),
                ],
                limit=1,
            )
        )

        if not tx_sudo:
            _logger.warning(
                f"MobilePay Webhook: Transaction not found for paymentId {payment_id}"
            )
            return "OK"

        # Verify Signature
        provider = tx_sudo.provider_id
        path = request.httprequest.path
        query = request.httprequest.query_string.decode("utf-8")
        if query:
            path = f"{path}?{query}"

        if not self._verify_signature(
            raw_data,
            auth_header,
            content_hash_header,
            date_header,
            host_header,
            path,
            provider.mobilepay_webhook_secret,
        ):
            _logger.warning(
                f"MobilePay Webhook: Invalid signature for paymentId {payment_id}"
            )
            raise Forbidden("Invalid signature")

        # Process Webhook Event
        event_type = data.get("eventType")
        _logger.info(
            f"MobilePay Webhook: Processing {event_type} for {tx_sudo.reference}"
        )

        try:
            # Fetch latest status to be safe (idempotent)
            tx_sudo._mobilepay_get_payment_status()
            return "OK"

        except Exception as e:
            _logger.error(f"MobilePay Webhook: Error processing event: {str(e)}")
            return http.Response("Internal Server Error", status=500)

    def _verify_signature(
        self,
        payload,
        auth_header,
        content_hash_header,
        date_header,
        host_header,
        path,
        secret,
    ):
        """
        Verify Azure-style HMAC-SHA256 signature.

        Format:
        POST\n<path>\n<date>;<host>;<content_hash>
        """
        if not secret:
            return False

        try:
            # 1. Verify content hash
            calculated_hash = base64.b64encode(hashlib.sha256(payload).digest()).decode(
                "utf-8"
            )
            if not hmac.compare_digest(calculated_hash, content_hash_header):
                _logger.warning(
                    f"MobilePay Webhook: Content hash mismatch. Calc: {calculated_hash}, Header: {content_hash_header}"
                )
                return False

            # 2. Extract signature from Authorization header
            # Header format: HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature=<sig>
            if "Signature=" not in auth_header:
                return False

            provided_signature = auth_header.split("Signature=")[1]

            # 3. Construct string to sign
            # Note: The documentation specifies strict format: POST\n<path>\n<date>;<host>;<hash>
            # And expects specific headers in specific order in the 3rd line.
            # Usually SignedHeaders list dictates the order, but Vipps doc example shows x-ms-date;host;x-ms-content-sha256

            string_to_sign = (
                f"POST\n{path}\n{date_header};{host_header};{content_hash_header}"
            )

            # 4. Calculate HMAC
            try:
                key = base64.b64decode(
                    secret
                )  # Secret is typically base64 encoded in Vipps response
            except Exception:
                # Fallback if secret is not base64 encoded
                _logger.debug("Webhook secret not base64 encoded, using raw")
                key = secret.encode("utf-8")

            calculated_hmac = hmac.new(
                key, string_to_sign.encode("utf-8"), hashlib.sha256
            ).digest()
            calculated_signature = base64.b64encode(calculated_hmac).decode("utf-8")

            # 5. Compare
            return hmac.compare_digest(calculated_signature, provided_signature)

        except Exception as e:
            _logger.error(f"Signature verification failed: {str(e)}")
            return False

    @http.route(
        "/payment/mobilepay/return",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
        save_session=False,
    )
    def mobilepay_return(self, **kwargs):
        """
        Handle customer return from MobilePay payment interface.
        Triggers an immediate status poll to ensure the user sees the latest state.
        """
        # Extract parameters (MobilePay might pass reference or we rely on session/params)
        # Usually params like ?reference=... are passed if we configured the return URL with them
        # Or we can look up by payment_id if provided.
        # MobilePay return URL usually has standard Odoo params if generated correctly.

        # Odoo's /payment/status expects 'payment_id' (internal ID) or 'reference' in session
        # But here we want to update the transaction first.

        # Let's try to find the transaction from params
        reference = kwargs.get("reference")

        if reference:
            tx_sudo = (
                request.env["payment.transaction"]
                .sudo()
                .search(
                    [
                        ("reference", "=", reference),
                        ("provider_code", "=", "mobilepay"),
                    ],
                    limit=1,
                )
            )

            if tx_sudo:
                _logger.info(f"MobilePay Return: Polling status for {reference}")
                try:
                    # Poll for latest status (Sync)
                    tx_sudo._mobilepay_get_payment_status()
                except Exception as e:
                    _logger.warning(
                        f"MobilePay Return: Failed to poll status for {reference}: {e}"
                    )

        # Redirect to standard Odoo payment status page
        return request.redirect("/payment/status")
