from unittest.mock import Mock, patch

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase


class TestOdoo18Migration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env.ref("mobilepay_payment.payment_provider_mobilepay")
        cls.provider.write({
            "state": "test",
            "capture_manually": True,
            "mobilepay_test_client_id": "test-client",
            "mobilepay_test_client_secret": "test-secret",
            "mobilepay_test_subscription_key": "test-subscription",
            "mobilepay_test_merchant_serial": "123456",
        })
        cls.method = cls.env.ref("mobilepay_payment.payment_method_mobilepay")
        cls.currency = cls.env.ref("base.DKK")
        cls.currency.active = True
        cls.partner = cls.env["res.partner"].create({
            "name": "Migration Test Customer",
            "email": "mobilepay-test@example.com",
            "phone": "+4512345678",
            "country_id": cls.env.ref("base.dk").id,
        })

    def _create_transaction(self, **values):
        return self.env["payment.transaction"].create({
            "provider_id": self.provider.id,
            "payment_method_id": self.method.id,
            "reference": "MOBILEPAY18-TEST",
            "amount": 100.0,
            "currency_id": self.currency.id,
            "partner_id": self.partner.id,
            "operation": "online_redirect",
            **values,
        })

    def test_dependencies_installed(self):
        for name in ("payment", "account", "website_sale", "stock", "sale_stock", "sale"):
            with self.subTest(module=name):
                module = self.env["ir.module.module"].search([("name", "=", name)])
                self.assertEqual(module.state, "installed")
        self.assertEqual(self.method.support_refund, "partial")

    def test_list_views_and_actions(self):
        view = self.env.ref("mobilepay_payment.mobilepay_settlement_view_tree")
        self.assertEqual(view.type, "list")
        self.assertEqual(etree.fromstring(view.arch_db).tag, "list")
        for xml_id in ("action_mobilepay_settlement", "action_mobilepay_transactions"):
            with self.subTest(action=xml_id):
                action = self.env.ref(f"mobilepay_payment.{xml_id}")
                self.assertEqual(action.view_mode, "list,form")

    def test_inherited_views_resolve(self):
        for model in ("payment.provider", "payment.transaction"):
            for view_type in ("form", "list"):
                with self.subTest(model=model, view_type=view_type):
                    view = self.env[model].get_view(view_type=view_type)
                    self.assertIn("show_mobilepay_fields", view["arch"])

    def test_scheduled_actions(self):
        expected = {
            "status_poll": (1, "minutes"),
            "capture_expiry": (6, "hours"),
            "cancel_on_order_cancel": (15, "minutes"),
            "reconcile_reports": (1, "days"),
            "auto_capture": (5, "minutes"),
        }
        for suffix, interval in expected.items():
            with self.subTest(cron=suffix):
                cron = self.env.ref(f"mobilepay_payment.ir_cron_mobilepay_{suffix}")
                self.assertTrue(cron.active)
                self.assertEqual((cron.interval_number, cron.interval_type), interval)
                compile(cron.code, f"cron:{suffix}", "exec")

    def test_credential_write_encrypts_and_reads(self):
        self.assertNotEqual(self.provider.mobilepay_test_client_secret_encrypted, "test-secret")
        self.assertEqual(self.provider.mobilepay_client_secret, "test-secret")
        self.assertEqual(self.provider.mobilepay_subscription_key, "test-subscription")
        self.assertEqual(self.provider._mobilepay_get_api_url(), "https://apitest.vipps.no")

    def test_production_credentials_required(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.provider.state = "enabled"

    def test_api_identifies_odoo18(self):
        auth = self.env["mobilepay.auth.service"]
        with patch.object(type(auth), "get_access_token", return_value="test-token"):
            headers = self.env["mobilepay.api.client"]._get_system_headers(self.provider)
        self.assertEqual(headers["Vipps-System-Version"], "18.0")
        self.assertEqual(headers["User-Agent"], "Odoo/18.0 mobilepay_payment/1.0.0")
        self.assertEqual(headers["Merchant-Serial-Number"], "123456")

    def test_oauth_identifies_odoo18(self):
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "test-token", "expires_in": 3600}
        with patch(
            "odoo.addons.mobilepay_payment.models.mobilepay_auth_service.requests.post",
            return_value=response,
        ) as post:
            token = self.env["mobilepay.auth.service"]._acquire_new_token(self.provider)
        self.assertEqual(token, "test-token")
        self.assertEqual(post.call_args.kwargs["headers"]["Vipps-System-Version"], "18.0")
        self.assertEqual(
            self.env["mobilepay.auth.service"]._get_cached_token(self.provider.id),
            "test-token",
        )

    def test_provider_currency_filter_uses_target_signature(self):
        args = (self.env.company.id, self.partner.id, 100.0)
        providers = self.env["payment.provider"]
        self.assertIn(
            self.provider, providers._get_compatible_providers(*args, currency_id=self.currency.id)
        )
        self.assertNotIn(
            self.provider,
            providers._get_compatible_providers(*args, currency_id=self.env.ref("base.USD").id),
        )

    def test_redirect_processing_creates_pending_payment(self):
        tx = self._create_transaction()
        client = self.env["mobilepay.api.client"]
        with patch.object(type(client), "create_payment", return_value={
            "reference": tx.reference,
            "redirectUrl": "https://apitest.vipps.no/checkout?token=test-token&extra=a%2Bb&empty=&tag=1&tag=2",
        }) as create, patch.object(
            type(self.provider), "get_base_url", return_value="https://sandbox.example.com"
        ):
            values = tx._get_processing_values()
        form = etree.fromstring(values["redirect_form_html"])
        self.assertEqual(form.attrib["action"], "https://apitest.vipps.no/checkout")
        self.assertEqual(form.xpath(".//input[@name='token']/@value"), ["test-token"])
        self.assertEqual(form.xpath(".//input[@name='extra']/@value"), ["a+b"])
        self.assertEqual(form.xpath(".//input[@name='empty']/@value"), [""])
        self.assertEqual(form.xpath(".//input[@name='tag']/@value"), ["1", "2"])
        self.assertEqual(tx.state, "pending")
        self.assertEqual(tx.provider_reference, tx.reference)
        self.assertEqual(tx.mobilepay_api_reference, tx.reference)
        payload = create.call_args.args[1]
        self.assertEqual(payload["amount"], {"currency": "DKK", "value": 10000})
        self.assertEqual(payload["userFlow"], "WEB_REDIRECT")
        self.assertEqual(payload["customer"]["phoneNumber"], "4512345678")

    def test_status_aggregate_updates_amounts(self):
        tx = self._create_transaction(state="pending")
        tx._mobilepay_process_status({
            "state": ["AUTHORIZED"],
            "aggregate": {"authorizedAmount": {"value": 10000}},
        })
        self.assertEqual(tx.state, "authorized")
        self.assertEqual(tx.authorized_amount, 100.0)
        tx._mobilepay_process_status({
            "state": "CAPTURED",
            "aggregate": {"capturedAmount": {"value": 10000}},
        })
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.captured_amount, 100.0)

    def test_full_capture_preserves_amounts(self):
        tx = self._create_transaction(
            state="authorized",
            mobilepay_status="AUTHORIZED",
            authorized_amount=100.0,
            mobilepay_api_reference="MOBILEPAY18-TEST",
        )
        client = self.env["mobilepay.api.client"]
        with patch.object(type(client), "capture_payment", return_value={
            "aggregate": {"capturedAmount": {"currency": "DKK", "value": 10000}},
        }) as capture:
            tx._send_capture_request()
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.captured_amount, 100.0)
        self.assertEqual(
            capture.call_args.args[2],
            {"modificationAmount": {"currency": "DKK", "value": 10000}},
        )
