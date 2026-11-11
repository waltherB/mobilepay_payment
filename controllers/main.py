# -*- coding: utf-8 -*-

import re

import hmac
import hashlib
import base64
import json
import logging
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)
_logger.info("MobilePay Controller: Initializing...")


class MobilePayController(http.Controller):
    """Controller for MobilePay payment processing and webhooks."""

    @http.route(
        "/payment/mobilepay/status", type="http", auth="public", methods=["GET"]
    )
    def mobilepay_status(self, **kwargs):
        """Simple reachability check."""
        return request.make_response(
            "MobilePay Controller is active and reachable.", status=200
        )

    @http.route(
        ["/payment/mobilepay/webhook", "/payment/vipps/webhook"],
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
        save_session=False,
    )
    def mobilepay_webhook(self, **kwargs):
        """
        Handle MobilePay/Vipps webhook notifications.
        Supports POST for actual events and GET for reachability pings.
        """
        _logger.info(
            f"MobilePay Webhook: {request.httprequest.method} request received at {request.httprequest.path}"
        )
        if request.httprequest.method == "GET":
            return request.make_response("OK", status=200)

        return self._process_webhook(**kwargs)

    def _process_webhook(self, **kwargs):
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
        host_header = headers.get("Host")

        if not auth_header or not content_hash_header or not date_header:
            _logger.warning(
                "MobilePay Webhook: Missing required authentication headers"
            )
            raise Forbidden("Missing headers")

        try:
            data = json.loads(raw_data)
        except ValueError:
            _logger.warning("MobilePay Webhook: Invalid JSON payload")
            return request.make_response("Invalid JSON", status=400)
        if not isinstance(data, dict) or not isinstance(data.get("data", data), dict):
            _logger.warning("MobilePay Webhook: Expected a JSON object")
            return request.make_response("Invalid payload", status=400)

        # Log raw payload for debugging
        _logger.info(f"MobilePay Webhook Payload: {data}")

        # Extract all potential identifiers from payload
        event_data = data.get("data", data)
        payment_id = (
            data.get("paymentId")
            or data.get("pspReference")
            or event_data.get("paymentId")
            or event_data.get("pspReference")
        )
        reference = data.get("reference") or event_data.get("reference")

        _logger.info(
            f"MobilePay Webhook: Processing payload (ID: {payment_id}, Ref: {reference})"
        )

        event_type = (
            data.get("eventType")
            or data.get("name")
            or event_data.get("eventType")
            or event_data.get("name")
        )

        # Build search clues
        search_clues = []
        if payment_id:
            search_clues.append(payment_id)
        if reference:
            search_clues.append(reference)
            # Add stripped variants for Odoo reference matching
            if "-TX" in reference:
                search_clues.append(reference.split("-TX")[0])
            if reference.startswith("MP-"):
                mp_parts = reference.replace("MP-", "").split("-")
                if mp_parts:
                    search_clues.append(mp_parts[0])

        if not search_clues:
            _logger.warning("MobilePay Webhook: No identifier found in payload")
            return request.make_response("OK", status=200)

        # Search for transaction using any of the available clues
        # This handles cases where Odoo stores Merchant Reference but webhook sends UUID
        tx_sudo = (
            request.env["payment.transaction"]
            .sudo()
            .search(
                [
                    ("provider_id.code", "=", "mobilepay"),
                    ("source_transaction_id", "=", False),
                    "|",
                    "|",
                    "|",
                    ("mobilepay_payment_id", "in", search_clues),
                    ("mobilepay_api_reference", "in", search_clues),
                    ("reference", "in", search_clues),
                    ("mobilepay_idempotency_key", "in", search_clues),
                ],
                limit=1,
            )
        )

        # 4. Verify Signature (Must happen before any logic returns)
        # If we didn't find the transaction yet (race condition), we find the provider by MSN
        provider_sudo = tx_sudo.provider_id if tx_sudo else None
        msn = data.get("merchantSerialNumber") or data.get("msn")
        if not provider_sudo and msn:
            # Search using STORED fields to avoid non-stored search error
            provider_sudo = (
                request.env["payment.provider"]
                .sudo()
                .search(
                    [
                        ("code", "=", "mobilepay"),
                        "|",
                        ("mobilepay_test_merchant_serial", "=", msn),
                        ("mobilepay_prod_merchant_serial", "=", msn),
                    ],
                    limit=1,
                )
            )

        if not provider_sudo:
            _logger.warning("MobilePay Webhook: No provider available to verify signature")
            raise Forbidden("Unknown provider")

        if provider_sudo:
            # 4. Verify Signature
            path = request.httprequest.path
            query = request.httprequest.query_string.decode("utf-8")
            if query:
                path = f"{path}?{query}"

            msg_webhook_id = headers.get("Webhook-Id")
            stored_webhook_id = provider_sudo.mobilepay_webhook_id
            msn = data.get("merchantSerialNumber") or data.get("msn") or provider_sudo.mobilepay_merchant_serial
            
            _logger.info(
                f"MobilePay Webhook Trace: MSN={msn}, "
                f"Incoming ID={msg_webhook_id}, "
                f"Stored ID={stored_webhook_id}, "
                f"Has Secret={'YES' if provider_sudo.mobilepay_webhook_secret else 'NO'}"
            )

            # Note: Webhook-Id header is a unique message ID (for idempotency), 
            # NOT the registration ID (stored_webhook_id). We do NOT reject based on this mismatch.
            # This follows the Vipps/MobilePay ePayment API specification.

            signature_valid = self._verify_signature(
                raw_data,
                auth_header,
                content_hash_header,
                date_header,
                host_header,
                path,
                provider_sudo,
            )

            if not signature_valid:
                _logger.warning(
                    f"MobilePay Webhook: Invalid signature for paymentId {payment_id}"
                )
                raise Forbidden("Invalid signature")
            else:
                _logger.info(f"✅ MobilePay Webhook: Signature verified for {payment_id} (Webhook-Id: {msg_webhook_id})")

        # 5. Handle Race Conditions / Transaction Not Found
        if not tx_sudo:
            if event_type == "CREATED":
                _logger.info(
                    f"MobilePay Webhook: Transaction {payment_id} not yet committed, skipping CREATED event."
                )
                return request.make_response("OK", status=200)

            _logger.warning(
                f"MobilePay Webhook: Transaction not found for paymentId {payment_id}. Returning 404 to trigger retry."
            )
            return request.make_response("Not Found", status=404)

        # Process Webhook Event
        _logger.info(
            f"MobilePay Webhook: Processing {event_type} for {tx_sudo.reference} (Payment ID: {payment_id})"
        )

        try:
            # Fetch latest status to be safe (idempotent)
            if tx_sudo._mobilepay_get_payment_status() is None:
                _logger.warning("MobilePay Webhook: Status refresh failed; requesting retry")
                return request.make_response("Status refresh failed", status=503)
            return request.make_response("OK", status=200)

        except Exception as e:
            _logger.error(f"MobilePay Webhook: Error processing event: {str(e)}")
            return request.make_response("Internal Server Error", status=500)

    def _verify_signature(
        self,
        payload,
        auth_header,
        content_hash_header,
        date_header,
        host_header,
        path,
        provider,
    ):
        """Verify the canonical Vipps signed request, including the body hash."""
        if not provider or not provider.mobilepay_webhook_secret or not host_header:
            return False
        calculated_hash = base64.b64encode(hashlib.sha256(payload).digest()).decode()
        if not hmac.compare_digest(calculated_hash, content_hash_header or ""):
            _logger.warning("MobilePay Webhook: Content hash mismatch")
            return False
        signed = f"POST\n{path}\n{date_header};{host_header};{content_hash_header}"
        signature = base64.b64encode(hmac.new(
            provider.mobilepay_webhook_secret.encode(), signed.encode(), hashlib.sha256
        ).digest()).decode()
        expected = (
            "HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256"
            f"&Signature={signature}"
        )
        return hmac.compare_digest(expected, auth_header or "")

    @http.route(
        "/payment/mobilepay/return",
        type="http",
        auth="public",
        save_session=False,
    )
    def mobilepay_return(self, **kwargs):
        """
        Handle customer return from MobilePay payment interface.
        Triggers an immediate status poll to ensure the user sees the latest state.
        """
        reference = kwargs.get("reference")

        if reference:
            # Search for the transaction, removing prefix/suffix if necessary
            # Pattern Examples: S00053-TX17 or MP-S00053
            search_refs = [reference]
            if "-TX" in reference:
                search_refs.append(reference.split("-TX")[0])
            if reference.startswith("MP-"):
                mp_parts = reference.replace("MP-", "").split("-")
                if mp_parts:
                    search_refs.append(mp_parts[0])

            domain = [
                ("provider_id.code", "=", "mobilepay"),
                ("source_transaction_id", "=", False),
                "|",
                ("reference", "in", search_refs),
                ("mobilepay_api_reference", "in", search_refs),
            ]
            tx_sudo = request.env["payment.transaction"].sudo().search(domain, limit=1)

            if tx_sudo:
                _logger.info(f"MobilePay Return: Polling status for {reference}")
                try:
                    # Poll for latest status (Sync)
                    tx_sudo._mobilepay_get_payment_status()
                except Exception as e:
                    _logger.warning(
                        f"MobilePay Return: Failed to poll status for {reference}: {e}"
                    )

        # Redirect to generic payment status
        return request.redirect("/payment/status")
