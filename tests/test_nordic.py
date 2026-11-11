import runpy
from pathlib import Path
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestNordicCoverage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env.ref("mobilepay_payment.payment_provider_mobilepay")
        cls.provider.write({"state": "test", "is_published": True})
        cls.method = cls.env.ref("mobilepay_payment.payment_method_mobilepay")
        cls.method.active = True
        cls.currencies = cls.env["res.currency"].with_context(active_test=False).search([
            ("name", "in", ["DKK", "EUR", "NOK", "SEK", "USD"]),
        ])
        cls.currencies.active = True
        cls.partner = cls.env["res.partner"].create({
            "name": "Nordic Test Customer",
            "country_id": cls.env.ref("base.dk").id,
        })

    def _transaction(self, currency="DKK"):
        return self.env["payment.transaction"].create({
            "provider_id": self.provider.id,
            "payment_method_id": self.method.id,
            "partner_id": self.partner.id,
            "reference": self.env["payment.transaction"]._compute_reference(
                "mobilepay", prefix="NORDIC-TEST"
            ),
            "currency_id": self.env.ref(f"base.{currency}").id,
            "amount": 100.0,
            "operation": "online_redirect",
        })

    def test_seeded_nordic_countries_and_currencies(self):
        self.assertEqual(set(self.method.supported_country_ids.mapped("code")),
                         {"DK", "FI", "NO", "SE", "GL", "FO"})
        self.assertEqual(set(self.method.supported_currency_ids.mapped("name")),
                         {"DKK", "EUR", "NOK"})

    def test_cross_border_provider_and_payment_method_availability(self):
        for region, currency in (("DK", "DKK"), ("FI", "EUR"), ("NO", "NOK")):
            self.provider.mobilepay_sales_unit_region = region
            for country in ("dk", "fi", "no", "se", "gl", "fo"):
                with self.subTest(region=region, customer=country):
                    self.partner.country_id = self.env.ref(f"base.{country}")
                    providers = self.env["payment.provider"]._get_compatible_providers(
                        self.env.company.id, self.partner.id, 100,
                        self.env.ref(f"base.{currency}").id,
                    )
                    self.assertIn(self.provider, providers)
                    methods = self.env["payment.method"]._get_compatible_payment_methods(
                        providers.ids, self.partner.id,
                        currency_id=self.env.ref(f"base.{currency}").id,
                    )
                    self.assertIn(self.method, methods)

    def test_sales_unit_currency_is_enforced_even_with_empty_operator_filter(self):
        for region, currency in (("DK", "DKK"), ("FI", "EUR"), ("NO", "NOK")):
            self.provider.mobilepay_sales_unit_region = region
            self.assertEqual(self.provider._get_supported_currencies().name, currency)
            self.assertEqual(self.provider.available_currency_ids.name, currency)
            self.provider.available_currency_ids = [Command.clear()]
            for other in self.currencies:
                with self.subTest(region=region, currency=other.name):
                    providers = self.env["payment.provider"]._get_compatible_providers(
                        self.env.company.id, self.partner.id, 100, currency_id=other.id,
                    )
                    self.assertEqual(self.provider in providers, other.name == currency)

    def test_wrong_currency_cannot_create_remote_payment(self):
        client = self.env["mobilepay.api.client"]
        self.provider.mobilepay_sales_unit_region = "DK"
        with patch.object(type(client), "create_payment") as create:
            with self.assertRaisesRegex(UserError, "DKK"):
                self._transaction("EUR")._send_payment_request()
        create.assert_not_called()

    def test_capture_void_and_refund_preserve_each_merchant_currency(self):
        client = self.env["mobilepay.api.client"]
        self.provider.capture_mode = "manual"
        for region, currency in (("DK", "DKK"), ("FI", "EUR"), ("NO", "NOK")):
            with self.subTest(region=region):
                self.provider.mobilepay_sales_unit_region = region
                tx = self._transaction(currency)
                tx.write({
                    "state": "authorized", "authorized_amount": 100,
                    "mobilepay_status": "AUTHORIZED",
                    "mobilepay_api_reference": tx.reference,
                })
                with patch.object(type(client), "capture_payment", return_value={
                    "aggregate": {"capturedAmount": {"currency": currency, "value": 4000}},
                }) as capture:
                    captured = tx._send_capture_request(40)
                self.assertEqual(capture.call_args.args[2], {
                    "modificationAmount": {"currency": currency, "value": 4000},
                })
                with patch.object(type(client), "cancel_payment", return_value={
                    "aggregate": {"cancelledAmount": {"currency": currency, "value": 6000}},
                }):
                    voided = tx._send_void_request(60)
                with patch.object(type(client), "refund_payment", return_value={
                    "aggregate": {"refundedAmount": {"currency": currency, "value": 1500}},
                }) as refund:
                    refunded = captured._send_refund_request(15)
                self.assertEqual(refund.call_args.args[2], {
                    "modificationAmount": {"currency": currency, "value": 1500},
                })
                self.assertEqual(tx.state, "done")
                self.assertEqual(captured.state, "done")
                self.assertEqual(voided.state, "cancel")
                self.assertEqual(refunded.state, "done")
                self.assertEqual(refunded.amount, -15)
                self.assertEqual((captured | voided | refunded).currency_id, tx.currency_id)
                self.assertEqual(tx.refunded_amount, 15)

    def test_operator_country_restrictions_remain_effective(self):
        self.provider.available_country_ids = [Command.set(self.env.ref("base.dk").ids)]
        self.partner.country_id = self.env.ref("base.no")
        providers = self.env["payment.provider"]._get_compatible_providers(
            self.env.company.id, self.partner.id, 100, currency_id=self.env.ref("base.DKK").id,
        )
        self.assertNotIn(self.provider, providers)
        self.provider.available_country_ids = [Command.clear()]
        self.method.supported_country_ids = [Command.set(self.env.ref("base.dk").ids)]
        methods = self.env["payment.method"]._get_compatible_payment_methods(
            self.provider.ids, self.partner.id, currency_id=self.env.ref("base.DKK").id,
        )
        self.assertNotIn(self.method, methods)

    def test_other_provider_currency_support_is_unchanged(self):
        other = self.env["payment.provider"].create({"name": "Other Nordic Test", "code": "none"})
        self.assertIn(self.env.ref("base.USD"), other._get_supported_currencies())
        self.assertIn(self.env.ref("base.SEK"), other._get_supported_currencies())

    def test_customer_country_phone_normalization(self):
        for country, local, expected in (
            ("dk", "12 34 56 78", "4512345678"),
            ("no", "91 23 45 67", "4791234567"),
            ("fi", "040 123 4567", "358401234567"),
            ("se", "070 123 45 67", "46701234567"),
            ("gl", "12 34 56", "299123456"),
            ("fo", "12 34 56 78", "4512345678"),
        ):
            self.partner.country_id = self.env.ref(f"base.{country}")
            tx = self._transaction()
            with self.subTest(country=country):
                self.assertEqual(tx._format_phone_number_v3(local), expected)
                self.assertEqual(tx._format_phone_number_v3("+" + expected), expected)
                self.assertEqual(tx._format_phone_number_v3("00" + expected), expected)
                self.assertEqual(tx._format_phone_number_v3(expected), expected)
                # The customer may use a phone from a different Nordic country.
                self.assertEqual(tx._format_phone_number_v3("+47 91234567"), "4791234567")
                self.assertEqual(tx._format_phone_number_v3("491234567890"), "491234567890")

    def test_invalid_phone_formats_are_rejected(self):
        tx = self._transaction()
        for phone in ("+0123456789", "12+3456789", "++4512345678", "１２３４５６７８",
                      "+1234567890123456", "call12345678", "+45", "0000000000"):
            with self.subTest(phone=phone):
                self.assertIsNone(tx._format_phone_number_v3(phone))

    def _migrate(self):
        path = Path(__file__).parents[1] / "migrations" / "18.0.1.2.0" / "post-migrate.py"
        runpy.run_path(str(path))["migrate"](self.cr, "18.0.1.1.0")
        self.env.invalidate_all()

    def test_upgrade_expands_legacy_defaults_idempotently(self):
        self.method.write({
            "supported_country_ids": [Command.set(self.env.ref("base.dk").ids)],
            "supported_currency_ids": [Command.set(self.env.ref("base.DKK").ids)],
            "name": "MobilePay",
        })
        self.provider.name = "MobilePay"
        self.provider.write({
            "capture_mode": "delivery",
            "mobilepay_test_client_secret": "synthetic-preserved-nordic-secret",
        })
        ciphertext = self.provider.mobilepay_test_client_secret_encrypted
        self._migrate()
        self._migrate()
        self.test_seeded_nordic_countries_and_currencies()
        self.assertEqual(self.method.name, "Vipps / MobilePay")
        self.assertEqual(self.provider.name, "Vipps / MobilePay")
        self.assertEqual(self.provider.mobilepay_sales_unit_region, "DK")
        self.assertEqual(self.provider.capture_mode, "delivery")
        self.assertEqual(self.provider.mobilepay_test_client_secret_encrypted, ciphertext)

    def test_upgrade_preserves_custom_restrictions_and_names(self):
        for countries, currencies in (([], []), (["fi"], ["EUR"])):
            self.method.write({
                "supported_country_ids": [Command.set([
                    self.env.ref(f"base.{code}").id for code in countries
                ])],
                "supported_currency_ids": [Command.set([
                    self.env.ref(f"base.{code}").id for code in currencies
                ])],
                "name": "Custom Wallet",
            })
            self.provider.name = "My Wallet"
            self._migrate()
            self.assertEqual(set(self.method.supported_country_ids.mapped("code")),
                             {c.upper() for c in countries})
            self.assertEqual(self.method.supported_currency_ids.mapped("name"), currencies)
            self.assertEqual(self.method.name, "Custom Wallet")
            self.assertEqual(self.provider.name, "My Wallet")
