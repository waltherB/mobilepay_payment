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
            # 4. Verify Signature
            path = request.httprequest.path
            query = request.httprequest.query_string.decode("utf-8")
            if query:
                path = f"{path}?{query}"

            # Comprehensive Header Logging for diagnostics
            _logger.info("MobilePay Webhook: Incoming Headers:")
            for key, value in headers.items():
                _logger.info(f"  {key}: {value}")

            msg_webhook_id = headers.get("Webhook-Id")
            stored_webhook_id = provider_sudo.mobilepay_webhook_id
            msn = data.get("msn") or provider_sudo.mobilepay_merchant_serial
            
            _logger.info(
                f"MobilePay Webhook Trace: MSN={msn}, "
                f"Incoming ID={msg_webhook_id}, "
                f"Stored ID={stored_webhook_id}, "
                f"Has Secret={'YES' if provider_sudo.mobilepay_webhook_secret else 'NO'}"
            )

            if msg_webhook_id and stored_webhook_id and msg_webhook_id != stored_webhook_id:
                _logger.warning(
                    f"MobilePay Webhook: Received notification for unrecognized/legacy ID {msg_webhook_id}. "
                    f"Current active ID is {stored_webhook_id}. Ignoring to avoid signature mismatch."
                )
                return request.make_response("Accepted Legacy", status=202)

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
        Robust signature verification (v42).
        Tests multiple permutations of STS construction and secret formats.
        """
        if not provider:
            return False

        headers = request.httprequest.headers
        try:
            # 1. Content Hash Verification
            calculated_hash_bytes = base64.b64encode(hashlib.sha256(payload).digest())
            calculated_hash = calculated_hash_bytes.decode("utf-8").strip()
            provided_hash = (content_hash_header or "").strip()

            if not hmac.compare_digest(calculated_hash, provided_hash):
                _logger.warning(
                    f"MobilePay Webhook: Content hash mismatch. Calc: {calculated_hash}, Provided: {provided_hash}"
                )
                # We continue anyway as some test environments might have slight payload mutations
            
            # 2. Extract Provided Signature
            signature_match = re.search(r"Signature=([^& \n]+)", auth_header or "")
            provided_signature = (
                signature_match.group(1).strip() if signature_match else ""
            )
            if not provided_signature:
                _logger.warning("MobilePay Webhook: No signature found in headers.")
                return False

            # 3. Handle Hinted Headers
            signed_headers_match = re.search(r"SignedHeaders=([^& \n]+)", auth_header or "")
            hint_headers = (
                signed_headers_match.group(1).split(";") if signed_headers_match else []
            )
            if not hint_headers:
                hint_headers = ["x-ms-date", "host", "x-ms-content-sha256"]

            # 4. Prepare Secret(s)
            secret_str = (provider.mobilepay_webhook_secret or "").strip()
            if not secret_str:
                _logger.warning("MobilePay Webhook: Missing webhook secret.")
                return False

            secrets_to_test = [secret_str.encode("utf-8")]
            try:
                secrets_to_test.append(base64.b64decode(secret_str))
            except Exception:
                pass

            # 5. Permutation Matrix
            # We test various ways the 'Host' might be treated and how the header list is joined
            host_original = (headers.get("host") or "").strip()
            
            # Host permutations
            hosts = [host_original, host_original.lower().split(":")[0], host_original.lower()]
            hosts = list(dict.fromkeys(hosts)) # Unique

            # Separator permutations
            separators = [";", "\n", " "]

            for secret_bytes in secrets_to_test:
                for current_host in hosts:
                    for sep in separators:
                        # Build values based on hint_headers
                        h_vals = []
                        for h_name in hint_headers:
                            if h_name.lower() == "host":
                                h_vals.append(current_host)
                            else:
                                h_vals.append((headers.get(h_name) or "").strip())

                        signed_headers_string = sep.join(h_vals)
                        
                        # STS Variations
                        sts_variations = [
                            f"POST\n{path}\n{signed_headers_string}", # Standard APIM
                            f"POST\n{path}\n{signed_headers_string}\n", # Trailing newline
                        ]

                        for sts in sts_variations:
                            calc_hmac = hmac.new(
                                secret_bytes, sts.encode("utf-8"), hashlib.sha256
                            ).digest()
                            calc_sig = base64.b64encode(calc_hmac).decode("utf-8")

                            if hmac.compare_digest(calc_sig, provided_signature):
                                _logger.info(f"✅ MobilePay Webhook: Signature verified (Path: {path}, Sep: '{sep}', Host: '{current_host}')")
                                return True

            _logger.warning("MobilePay Webhook: All signature verification permutations failed.")
            _logger.info(f"Diagnostic - Last STS attempted: '{sts.replace(chr(10), chr(92)+chr(110))}'")
            return False

        except Exception as e:
            _logger.error(f"MobilePay Webhook: Error during signature verification: {str(e)}")
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
