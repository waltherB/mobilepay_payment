# -*- coding: utf-8 -*-

import itertools
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
        if not provider_sudo and data.get("msn"):
            # Search using STORED fields to avoid non-stored search error
            msn = data.get("msn")
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

        if provider_sudo:
            path = request.httprequest.path
            query = request.httprequest.query_string.decode("utf-8")
            if query:
                path = f"{path}?{query}"

            # Comprehensive Header Logging for diagnostics
            _logger.info("MobilePay Webhook: Incoming Headers:")
            for key, value in headers.items():
                _logger.info(f"  {key}: {value}")

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
                _logger.info(f"MobilePay Webhook: Signature verified for {payment_id}")

        # 5. Handle Race Conditions / Transaction Not Found
        if not tx_sudo:
            if event_type == "CREATED":
                _logger.info(
                    f"MobilePay Webhook: Transaction {payment_id} not yet committed, skipping CREATED event."
                )
                return request.make_response("OK", status=200)

            _logger.warning(
                f"MobilePay Webhook: Transaction not found for paymentId {payment_id}"
            )
            return request.make_response("OK", status=200)

        # Process Webhook Event
        _logger.info(
            f"MobilePay Webhook: Processing {event_type} for {tx_sudo.reference} (Payment ID: {payment_id})"
        )

        try:
            # Fetch latest status to be safe (idempotent)
            tx_sudo._mobilepay_get_payment_status()
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
        """
        Hyper-Matrix Diagnostic (v37).
        Exhaustively tests permutations of subsets (3 & 4 headers).
        """
        if not provider:
            return False

        headers = request.httprequest.headers
        webhook_id = (headers.get("Webhook-Id") or "").strip()

        try:
            # 1. Verify content hash
            calculated_hash_bytes = base64.b64encode(hashlib.sha256(payload).digest())
            calculated_hash = calculated_hash_bytes.decode("utf-8").strip()
            provided_hash = (content_hash_header or "").strip()

            _logger.info("MobilePay Webhook: Hash Debug:")
            _logger.info(f"  Payload Len: {len(payload)}")
            _logger.info(
                f"  Calc Hash:   '{calculated_hash}' (Len: {len(calculated_hash)})"
            )
            _logger.info(
                f"  Header Hash: '{provided_hash}' (Len: {len(provided_hash)})"
            )

            # Check for hidden characters by comparing hex
            calc_hex = calculated_hash.encode("utf-8").hex()
            prov_hex = provided_hash.encode("utf-8").hex()
            _logger.info(f"  Calc Hex: {calc_hex}")
            _logger.info(f"  Prov Hex: {prov_hex}")

            if not hmac.compare_digest(calculated_hash, provided_hash):
                _logger.warning(
                    "MobilePay Webhook: Content hash mismatch (detected by compare_digest)"
                )
                # DO NOT RETURN FALSE YET
            else:
                _logger.info("MobilePay Webhook: Content SHA256 matches exactly.")

            # 2. Extract signature and SignedHeaders
            if "Signature=" not in (auth_header or ""):
                _logger.warning(
                    "MobilePay Webhook: Missing Signature in Authorization header"
                )
                return False

            # Use regex to extract Signature and SignedHeaders more robustly
            signature_match = re.search(r"Signature=([^&]+)", auth_header)
            provided_signature = (
                signature_match.group(1).strip() if signature_match else ""
            )

            # Parse SignedHeaders hint
            hint_headers = []
            signed_headers_match = re.search(r"SignedHeaders=([^&]+)", auth_header)
            if signed_headers_match:
                hint_headers = signed_headers_match.group(1).split(";")

            # 3. Simple & Robust Verification
            # As per official MobilePay documentation for Webhooks API v1

            # Use raw UTF-8 secret for HMAC calculation
            secret_str = provider.mobilepay_webhook_secret or ""
            if not secret_str:
                _logger.warning(
                    "MobilePay Webhook: Missing webhook secret in provider."
                )
                return False

            key = secret_str.encode("utf-8")

            # Case-insensitive header access via Werkzeug Headers object
            headers = request.httprequest.headers
            date_val = headers.get("x-ms-date") or headers.get("Date") or ""
            host_val = headers.get("host") or ""
            hash_val = headers.get("x-ms-content-sha256") or ""

            # RFC compliance: lowercase host in signature string
            host_val = host_val.lower()

            # SignHeaders hint: extract values in the specified order
            # Usually: x-ms-date;host;x-ms-content-sha256
            if not hint_headers:
                hint_headers = ["x-ms-date", "host", "x-ms-content-sha256"]

            h_vals = []
            for h_name in hint_headers:
                # Special handling for Host to match the lowercase requirement in STS
                if h_name.lower() == "host":
                    h_vals.append(host_val)
                else:
                    h_vals.append((headers.get(h_name) or "").strip())

            signed_headers_string = ";".join(h_vals)

            # Format: HTTP_METHOD\nPATH_AND_QUERY\nSIGNED_HEADERS_STRING
            # PATH_AND_QUERY is exactly as passed from the controller (full path + ?)
            string_to_sign = f"POST\n{path}\n{signed_headers_string}"

            calculated_hmac = hmac.new(
                key, string_to_sign.encode("utf-8"), hashlib.sha256
            ).digest()
            calculated_signature = base64.b64encode(calculated_hmac).decode("utf-8")

            _logger.info("MobilePay Webhook: Signature Verification Details:")
            sts_escaped = string_to_sign.replace("\n", "\\n")
            _logger.info(f"  STS: '{sts_escaped}'")
            _logger.info(f"  Calculated: {calculated_signature}")
            _logger.info(f"  Provided:   {provided_signature}")

            if hmac.compare_digest(calculated_signature, provided_signature):
                _logger.info("✅ MobilePay Webhook: Signature verified successfully.")
                return True

            _logger.warning("MobilePay Webhook: Signature verification failed.")
            return False

        except Exception as e:
            _logger.error(f"Signature verification failed: {str(e)}")
            return False

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

                # Redirect to payment status with access_token
                if tx_sudo.access_token:
                    return request.redirect(f"/payment/status/{tx_sudo.access_token}")

        # Fallback redirect to generic payment status
        return request.redirect("/payment/status")
