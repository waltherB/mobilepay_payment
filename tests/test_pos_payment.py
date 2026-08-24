# -*- coding: utf-8 -*-

"""
Automated tests for the MobilePay POS terminal integration.

Coverage:
- pos.payment.method model fields exist and use_payment_terminal includes 'mobilepay'
- /mobilepay/pos/initiate_payment — phone push mode
- /mobilepay/pos/initiate_payment — qr code mode
- /mobilepay/pos/check_status — AUTHORIZED state
- /mobilepay/pos/cancel_payment
- /mobilepay/pos/initiate_payment — missing provider graceful error
- /mobilepay/pos/get_qr — mid-flight QR switch
"""

from unittest.mock import patch, MagicMock
from odoo.tests import TransactionCase


class PosPaymentMethodModelTest(TransactionCase):
    """Test that pos.payment.method carries the new MobilePay fields."""

    def test_mobilepay_in_use_payment_terminal_selection(self):
        """'mobilepay' must appear as a valid selection value for use_payment_terminal."""
        field = self.env["pos.payment.method"]._fields.get("use_payment_terminal")
        self.assertIsNotNone(field, "Field use_payment_terminal must exist on pos.payment.method.")
        selection_keys = [k for k, _ in (field.selection or [])]
        self.assertIn(
            "mobilepay",
            selection_keys,
            "Selection 'mobilepay' must be added to use_payment_terminal.",
        )

    def test_mobilepay_config_fields_exist(self):
        """The three MobilePay config fields must be present on pos.payment.method."""
        model_fields = self.env["pos.payment.method"]._fields
        for field_name in (
            "mobilepay_pos_provider_id",
            "mobilepay_pos_default_mode",
            "mobilepay_pos_timeout",
        ):
            self.assertIn(
                field_name,
                model_fields,
                f"Field '{field_name}' must exist on pos.payment.method.",
            )

    def test_default_mode_default_value(self):
        """Default value for mobilepay_pos_default_mode must be 'prompt'."""
        method = self.env["pos.payment.method"].new({})
        self.assertEqual(
            method.mobilepay_pos_default_mode,
            "prompt",
            "Default mode should be 'prompt'.",
        )

    def test_default_timeout_value(self):
        """Default value for mobilepay_pos_timeout must be 60."""
        method = self.env["pos.payment.method"].new({})
        self.assertEqual(
            method.mobilepay_pos_timeout,
            60,
            "Default timeout should be 60 seconds.",
        )


# ---------------------------------------------------------------------------
# Shared fixtures for controller tests
# ---------------------------------------------------------------------------

class PosControllerBase(TransactionCase):
    """Base class: sets up a minimal POS environment for controller testing."""

    def setUp(self):
        super().setUp()

        self.dkk = self.env.ref("base.DKK")

        # MobilePay provider
        self.provider = self.env["payment.provider"].create({
            "name": "MobilePay POS Test Provider",
            "code": "mobilepay",
            "state": "test",
            "mobilepay_test_client_id": "fake-client-id",
            "mobilepay_test_merchant_serial": "123456",
        })

        # POS config
        self.pos_config = self.env["pos.config"].create({
            "name": "MobilePay Test POS",
        })

        # Payment method wired to the provider
        self.payment_method = self.env["pos.payment.method"].create({
            "name": "MobilePay",
            "use_payment_terminal": "mobilepay",
            "mobilepay_pos_provider_id": self.provider.id,
            "mobilepay_pos_default_mode": "prompt",
            "mobilepay_pos_timeout": 60,
        })
        self.pos_config.payment_method_ids = [(4, self.payment_method.id)]

        # Open a POS session
        self.pos_session = self.env["pos.session"].create({
            "config_id": self.pos_config.id,
        })

    # ------------------------------------------------------------------
    # Helpers to call the controller methods directly (bypassing HTTP)
    # ------------------------------------------------------------------

    def _call_initiate(self, payment_mode, phone_number=None, amount=100000,
                       currency="DKK", pos_reference="TEST-POS-001"):
        from odoo.addons.mobilepay_payment.controllers.pos_controller import (
            MobilePayPosController,
        )
        ctrl = MobilePayPosController()
        # Inject env via a request-like mock
        with self._mock_request():
            return ctrl.initiate_payment(
                pos_session_id=self.pos_session.id,
                amount=amount,
                currency=currency,
                pos_reference=pos_reference,
                payment_mode=payment_mode,
                phone_number=phone_number,
            )

    def _call_check_status(self, payment_id):
        from odoo.addons.mobilepay_payment.controllers.pos_controller import (
            MobilePayPosController,
        )
        ctrl = MobilePayPosController()
        with self._mock_request():
            return ctrl.check_status(
                pos_session_id=self.pos_session.id,
                payment_id=payment_id,
            )

    def _call_cancel(self, payment_id):
        from odoo.addons.mobilepay_payment.controllers.pos_controller import (
            MobilePayPosController,
        )
        ctrl = MobilePayPosController()
        with self._mock_request():
            return ctrl.cancel_payment(
                pos_session_id=self.pos_session.id,
                payment_id=payment_id,
            )

    def _call_get_qr(self, payment_id):
        from odoo.addons.mobilepay_payment.controllers.pos_controller import (
            MobilePayPosController,
        )
        ctrl = MobilePayPosController()
        with self._mock_request():
            return ctrl.get_qr(
                pos_session_id=self.pos_session.id,
                payment_id=payment_id,
            )

    def _mock_request(self):
        """Patch odoo.addons.mobilepay_payment.controllers.pos_controller.request.env."""
        from odoo.addons.mobilepay_payment.controllers import pos_controller as mod
        mock_req = MagicMock()
        mock_req.env = self.env
        return patch.object(mod, "request", mock_req)


# ---------------------------------------------------------------------------
# Controller tests
# ---------------------------------------------------------------------------

class TestInitiatePaymentPhonePush(PosControllerBase):

    def test_phone_push_returns_payment_id(self):
        """initiate_payment in phone_push mode must return a payment_id."""
        fake_response = {"reference": "FAKE-PAYMENT-001"}

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "create_payment",
            return_value=fake_response,
        ):
            result = self._call_initiate("phone_push", phone_number="+4512345678")

        self.assertNotIn("error", result, f"Unexpected error: {result.get('error')}")
        self.assertEqual(result["payment_id"], "FAKE-PAYMENT-001")
        self.assertIsNone(result["qr_payload"], "Phone push should not return a QR payload.")
        self.assertEqual(result["status"], "CREATED")

    def test_phone_push_sends_push_message_user_flow(self):
        """create_payment must be called with userFlow == 'PUSH_MESSAGE'."""
        captured = {}

        def fake_create(api_self, provider, payment_data, **kw):
            captured.update(payment_data)
            return {"reference": "FAKE-001"}

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "create_payment",
            side_effect=fake_create,
        ):
            self._call_initiate("phone_push", phone_number="+4512345678")

        self.assertEqual(captured.get("userFlow"), "PUSH_MESSAGE")
        self.assertIn("customer", captured)
        self.assertEqual(captured["customer"]["phoneNumber"], "+4512345678")

    def test_phone_push_without_phone_returns_error(self):
        """initiate_payment in phone_push mode without a phone number must return an error."""
        result = self._call_initiate("phone_push", phone_number=None)
        self.assertIn("error", result)


class TestInitiatePaymentQr(PosControllerBase):

    def test_qr_mode_returns_qr_payload(self):
        """initiate_payment in qr_code mode must return a base64 qr_payload."""
        import base64

        fake_png = base64.b64encode(b"FAKE_PNG_BYTES").decode()

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "create_payment",
            return_value={"reference": "FAKE-QR-001"},
        ):
            # Patch the QR image fetch helper
            from odoo.addons.mobilepay_payment.controllers import pos_controller as mod
            with patch.object(mod, "_fetch_qr_image", return_value=fake_png):
                result = self._call_initiate("qr_code")

        self.assertNotIn("error", result, f"Unexpected error: {result.get('error')}")
        self.assertEqual(result["payment_id"], "FAKE-QR-001")
        self.assertEqual(result["qr_payload"], fake_png)

    def test_qr_mode_sends_qr_user_flow(self):
        """create_payment must be called with userFlow == 'QR' for qr_code mode."""
        captured = {}

        def fake_create(api_self, provider, payment_data, **kw):
            captured.update(payment_data)
            return {"reference": "FAKE-QR-002"}

        import base64
        fake_png = base64.b64encode(b"PNG").decode()

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "create_payment",
            side_effect=fake_create,
        ):
            from odoo.addons.mobilepay_payment.controllers import pos_controller as mod
            with patch.object(mod, "_fetch_qr_image", return_value=fake_png):
                self._call_initiate("qr_code")

        self.assertEqual(captured.get("userFlow"), "QR")


class TestCheckStatus(PosControllerBase):

    def test_authorized_state_mapped_correctly(self):
        """check_status must map Vipps 'AUTHORIZED' to POS status 'AUTHORIZED'."""
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_payment_status",
            return_value={
                "state": "AUTHORIZED",
                "aggregate": {"authorizedAmount": {"value": 100000}},
            },
        ):
            result = self._call_check_status("FAKE-PAYMENT-001")

        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "AUTHORIZED")
        self.assertEqual(result["amount"], 100000)

    def test_cancelled_state_mapped_correctly(self):
        """check_status must map Vipps 'CANCELLED' to POS status 'CANCELLED'."""
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_payment_status",
            return_value={"state": "CANCELLED", "aggregate": {}},
        ):
            result = self._call_check_status("FAKE-PAYMENT-002")

        self.assertEqual(result["status"], "CANCELLED")

    def test_captured_state_mapped_correctly(self):
        """check_status must map Vipps 'CAPTURED' to POS status 'CAPTURED'."""
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_payment_status",
            return_value={
                "state": "CAPTURED",
                "aggregate": {"capturedAmount": {"value": 50000}},
            },
        ):
            result = self._call_check_status("FAKE-PAYMENT-003")

        self.assertEqual(result["status"], "CAPTURED")
        self.assertEqual(result["amount"], 50000)


class TestCancelPayment(PosControllerBase):

    def test_cancel_returns_success(self):
        """cancel_payment must return {success: True} when the API call succeeds."""
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "cancel_payment",
            return_value=True,
        ):
            result = self._call_cancel("FAKE-PAYMENT-001")

        self.assertNotIn("error", result)
        self.assertTrue(result.get("success"))

    def test_cancel_returns_error_on_api_failure(self):
        """cancel_payment must return {error: ...} when the API raises."""
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "cancel_payment",
            side_effect=Exception("Network timeout"),
        ):
            result = self._call_cancel("FAKE-PAYMENT-001")

        self.assertIn("error", result)


class TestMissingProvider(PosControllerBase):

    def test_initiate_without_provider_returns_error(self):
        """If no provider is configured or found, initiate_payment must return an error dict."""
        # Detach provider from payment method
        self.payment_method.mobilepay_pos_provider_id = False
        # Also make sure no fallback provider exists
        self.provider.state = "disabled"

        result = self._call_initiate("qr_code")
        self.assertIn("error", result, "Expected an error when no provider is available.")

    def test_check_status_without_provider_returns_error(self):
        """check_status must return an error dict when no provider is found."""
        self.payment_method.mobilepay_pos_provider_id = False
        self.provider.state = "disabled"

        result = self._call_check_status("FAKE-ID")
        self.assertIn("error", result)

    def test_cancel_without_provider_returns_error(self):
        """cancel_payment must return an error dict when no provider is found."""
        self.payment_method.mobilepay_pos_provider_id = False
        self.provider.state = "disabled"

        result = self._call_cancel("FAKE-ID")
        self.assertIn("error", result)


class TestGetQr(PosControllerBase):

    def test_get_qr_returns_payload(self):
        """get_qr must return the base64 QR payload for an existing payment."""
        import base64
        fake_png = base64.b64encode(b"FAKE_QR_PNG").decode()

        from odoo.addons.mobilepay_payment.controllers import pos_controller as mod
        with patch.object(mod, "_fetch_qr_image", return_value=fake_png):
            result = self._call_get_qr("FAKE-PAYMENT-001")

        self.assertNotIn("error", result)
        self.assertEqual(result["qr_payload"], fake_png)

    def test_get_qr_returns_error_when_fetch_fails(self):
        """get_qr must return an error dict when the QR image cannot be fetched."""
        from odoo.addons.mobilepay_payment.controllers import pos_controller as mod
        with patch.object(mod, "_fetch_qr_image", return_value=None):
            result = self._call_get_qr("FAKE-PAYMENT-001")

        self.assertIn("error", result)
