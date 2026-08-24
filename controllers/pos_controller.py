# -*- coding: utf-8 -*-

import logging
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)

# Status values returned to the JS layer (simplified from the Vipps API states)
_VIPPS_TO_POS_STATUS = {
    "CREATED": "CREATED",
    "ABORTED": "CANCELLED",
    "EXPIRED": "EXPIRED",
    "CANCELLED": "CANCELLED",
    "AUTHORIZED": "AUTHORIZED",
    "TERMINATED": "CANCELLED",
    # Captured (full or partial) means the payment is done
    "CAPTURED": "CAPTURED",
}


def _resolve_provider(pos_session_id):
    """
    Find the MobilePay payment.provider to use for this POS session.

    Resolution order:
    1. The provider linked on the active payment method that uses the 'mobilepay'
       terminal (mobilepay_pos_provider_id).
    2. The first active MobilePay provider belonging to the session's company.

    Returns:
        payment.provider record, or None if nothing is configured.
    """
    session = request.env["pos.session"].sudo().browse(pos_session_id)
    if not session.exists():
        return None

    # Try the explicitly linked provider on any mobilepay payment method
    mobilepay_methods = session.config_id.payment_method_ids.filtered(
        lambda m: m.use_payment_terminal == "mobilepay"
    )
    if mobilepay_methods and mobilepay_methods[0].mobilepay_pos_provider_id:
        return mobilepay_methods[0].mobilepay_pos_provider_id

    # Fall back: first active MobilePay provider for the company
    return (
        request.env["payment.provider"]
        .sudo()
        .search(
            [
                ("code", "=", "mobilepay"),
                ("state", "!=", "disabled"),
                ("company_id", "=", session.company_id.id),
            ],
            limit=1,
        )
        or None
    )


def _get_timeout(pos_session_id):
    """Return the configured timeout (seconds) for the active MobilePay method, or 60."""
    session = request.env["pos.session"].sudo().browse(pos_session_id)
    if not session.exists():
        return 60
    mobilepay_methods = session.config_id.payment_method_ids.filtered(
        lambda m: m.use_payment_terminal == "mobilepay"
    )
    if mobilepay_methods:
        return max(10, min(300, mobilepay_methods[0].mobilepay_pos_timeout or 60))
    return 60


class MobilePayPosController(http.Controller):
    """JSON-RPC endpoints consumed by the MobilePay POS JavaScript interface."""

    # ------------------------------------------------------------------
    # POST /mobilepay/pos/initiate_payment
    # ------------------------------------------------------------------
    @http.route(
        "/mobilepay/pos/initiate_payment",
        type="json",
        auth="user",
        csrf=False,
    )
    def initiate_payment(
        self,
        pos_session_id,
        amount,
        currency,
        pos_reference,
        payment_mode,
        phone_number=None,
        **kwargs,
    ):
        """
        Create a new MobilePay payment request from the POS terminal.

        Args:
            pos_session_id (int): Active POS session ID.
            amount (int): Payment amount in minor units (e.g. øre for DKK).
            currency (str): ISO 4217 currency code, e.g. "DKK".
            pos_reference (str): Unique POS order reference (max 50 chars).
            payment_mode (str): "phone_push" or "qr_code".
            phone_number (str|None): E.164 phone number; required for phone_push.

        Returns:
            dict: {payment_id, qr_payload (base64 str or None), status, timeout}
                  or {error: str} on failure.
        """
        try:
            provider = _resolve_provider(pos_session_id)
            if not provider:
                return {"error": _("No active MobilePay provider found for this POS session.")}

            if payment_mode == "phone_push" and not phone_number:
                return {"error": _("A phone number is required for Phone Push payments.")}

            # Sanitise reference to Vipps limits (max 50, alphanum + hyphen)
            import re
            safe_ref = re.sub(r"[^A-Za-z0-9\-]", "-", str(pos_reference))[:50]

            # Build ePayment payload
            user_flow = "PUSH_MESSAGE" if payment_mode == "phone_push" else "QR"
            payment_data = {
                "amount": {
                    "currency": currency,
                    "value": int(amount),
                },
                "paymentMethod": {"type": "WALLET"},
                "reference": safe_ref,
                "userFlow": user_flow,
                "returnUrl": "https://pos.internal/noop",  # POS does not use redirect
                "paymentDescription": f"POS Payment {safe_ref}",
            }

            if payment_mode == "phone_push" and phone_number:
                payment_data["customer"] = {"phoneNumber": phone_number}

            api_client = request.env["mobilepay.api.client"].sudo()
            result = api_client.create_payment(provider, payment_data)
            payment_id = result.get("reference") or result.get("paymentId") or result.get("orderId")

            if not payment_id:
                return {"error": _("MobilePay API did not return a payment ID.")}

            # For QR mode fetch the QR image
            qr_payload = None
            if payment_mode == "qr_code":
                qr_payload = _fetch_qr_image(api_client, provider, payment_id)

            timeout = _get_timeout(pos_session_id)

            _logger.info(
                "MobilePay POS: payment initiated (ref=%s, mode=%s, payment_id=%s)",
                safe_ref,
                payment_mode,
                payment_id,
            )
            return {
                "payment_id": payment_id,
                "qr_payload": qr_payload,
                "status": "CREATED",
                "timeout": timeout,
            }

        except Exception as e:
            _logger.error("MobilePay POS initiate_payment error: %s", str(e))
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # POST /mobilepay/pos/check_status
    # ------------------------------------------------------------------
    @http.route(
        "/mobilepay/pos/check_status",
        type="json",
        auth="user",
        csrf=False,
    )
    def check_status(self, pos_session_id, payment_id, **kwargs):
        """
        Poll the current status of a MobilePay payment.

        Args:
            pos_session_id (int): Active POS session ID.
            payment_id (str): MobilePay payment ID returned by initiate_payment.

        Returns:
            dict: {status, amount} or {error: str}.
        """
        try:
            provider = _resolve_provider(pos_session_id)
            if not provider:
                return {"error": _("No active MobilePay provider found.")}

            api_client = request.env["mobilepay.api.client"].sudo()
            data = api_client.get_payment_status(provider, payment_id)

            raw_state = (data.get("state") or data.get("status") or "").upper()
            pos_status = _VIPPS_TO_POS_STATUS.get(raw_state, "CREATED")

            # Amount is returned in minor units by the API
            amount = None
            aggregate = data.get("aggregate") or {}
            if aggregate.get("capturedAmount"):
                amount = aggregate["capturedAmount"].get("value")
            elif aggregate.get("authorizedAmount"):
                amount = aggregate["authorizedAmount"].get("value")

            return {"status": pos_status, "amount": amount}

        except Exception as e:
            _logger.error("MobilePay POS check_status error (payment_id=%s): %s", payment_id, str(e))
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # POST /mobilepay/pos/cancel_payment
    # ------------------------------------------------------------------
    @http.route(
        "/mobilepay/pos/cancel_payment",
        type="json",
        auth="user",
        csrf=False,
    )
    def cancel_payment(self, pos_session_id, payment_id, **kwargs):
        """
        Cancel a pending MobilePay payment.

        Args:
            pos_session_id (int): Active POS session ID.
            payment_id (str): MobilePay payment ID to cancel.

        Returns:
            dict: {success: bool} or {error: str}.
        """
        try:
            provider = _resolve_provider(pos_session_id)
            if not provider:
                return {"error": _("No active MobilePay provider found.")}

            api_client = request.env["mobilepay.api.client"].sudo()
            api_client.cancel_payment(provider, payment_id)

            _logger.info("MobilePay POS: payment cancelled (payment_id=%s)", payment_id)
            return {"success": True}

        except Exception as e:
            _logger.error("MobilePay POS cancel_payment error (payment_id=%s): %s", payment_id, str(e))
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # POST /mobilepay/pos/get_qr
    # ------------------------------------------------------------------
    @http.route(
        "/mobilepay/pos/get_qr",
        type="json",
        auth="user",
        csrf=False,
    )
    def get_qr(self, pos_session_id, payment_id, **kwargs):
        """
        Fetch (or re-fetch) a QR image for an existing payment.
        Used for mid-flight switch from phone push to QR mode.

        Args:
            pos_session_id (int): Active POS session ID.
            payment_id (str): Existing MobilePay payment ID.

        Returns:
            dict: {qr_payload: str (base64)} or {error: str}.
        """
        try:
            provider = _resolve_provider(pos_session_id)
            if not provider:
                return {"error": _("No active MobilePay provider found.")}

            api_client = request.env["mobilepay.api.client"].sudo()
            qr_payload = _fetch_qr_image(api_client, provider, payment_id)

            if not qr_payload:
                return {"error": _("Could not retrieve QR code from MobilePay.")}

            return {"qr_payload": qr_payload}

        except Exception as e:
            _logger.error("MobilePay POS get_qr error (payment_id=%s): %s", payment_id, str(e))
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_qr_image(api_client, provider, payment_id):
    """
    Fetch a QR image for a given payment from the Vipps QR endpoint.

    The endpoint returns a PNG image directly.  We base64-encode it so it
    can be inlined as a data-URI in the POS frontend.

    Returns:
        str: Base64-encoded PNG, or None on failure.
    """
    import base64

    endpoint = f"/epayment/v1/payments/{payment_id}/qr"
    try:
        # The QR endpoint returns image/png, not JSON, so we call _make_request
        # directly and handle the raw bytes response.
        headers = api_client._get_system_headers(provider)
        # Override Accept for image response
        headers["Accept"] = "image/png"

        base_url = provider._mobilepay_get_api_url()
        import requests as _requests
        response = _requests.get(
            f"{base_url}{endpoint}",
            headers=headers,
            timeout=10,
        )

        if response.status_code == 200:
            return base64.b64encode(response.content).decode("utf-8")

        _logger.warning(
            "MobilePay POS: QR endpoint returned HTTP %s for payment %s",
            response.status_code,
            payment_id,
        )
        return None

    except Exception as e:
        _logger.error("MobilePay POS: Failed to fetch QR image for %s: %s", payment_id, str(e))
        return None
