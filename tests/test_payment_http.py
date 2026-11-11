import base64
import hashlib
import hmac
import json
from email.utils import formatdate
from unittest.mock import patch
from urllib.parse import urlparse

from odoo.tests import HttpCase, tagged
from odoo.tools.misc import hmac as hmac_tool


@tagged("post_install", "-at_install")
class TestMobilePayHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env.ref("mobilepay_payment.payment_provider_mobilepay")
        cls.provider.write({
            "state": "test", "capture_mode": "manual",
            "mobilepay_webhook_secret": "synthetic-webhook-secret",
        })
        cls.currency = cls.env.ref("base.DKK")
        cls.currency.active = True
        cls.method = cls.env.ref("mobilepay_payment.payment_method_mobilepay")
        cls.method.active = True
        cls.partner = cls.env["res.partner"].create({
            "name": "HTTP Test Customer", "phone": "+4587654321",
            "country_id": cls.env.ref("base.dk").id,
        })
        cls.client = cls.env["mobilepay.api.client"]

    def _params(self, **values):
        return {
            "provider_id": self.provider.id,
            "payment_method_id": self.method.id,
            "token_id": None, "amount": 100.0,
            "currency_id": self.currency.id, "partner_id": self.partner.id,
            "flow": "redirect", "tokenization_requested": False,
            "landing_route": "/payment/confirmation",
            "access_token": hmac_tool(
                self.env(su=True), "generate_access_token",
                f"{self.partner.id}|100.0|{self.currency.id}",
            ),
            **values,
        }

    def _create_response(self, provider, data, **kwargs):
        self.payload = data
        return {
            "reference": data["reference"],
            "redirectUrl": "https://apitest.vipps.no/checkout?token=synthetic-token",
        }

    def _json_request(self, route, params):
        return self.url_open(
            route,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params, "id": 1}),
            headers={"Content-Type": "application/json"},
        ).json()

    def test_generic_checkout_phone_reaches_transaction_context(self):
        with patch.object(type(self.client), "create_payment", side_effect=self._create_response), \
             patch.object(type(self.provider), "get_base_url", return_value="https://sandbox.example.com"):
            result = self._json_request("/payment/transaction", self._params(
                mobilepay_phone="+45 12 34 56 78"
            ))
        self.assertIn("result", result, result)
        tx = self.env["payment.transaction"].search([
            ("reference", "=", result["result"]["reference"]),
        ])
        self.assertEqual(tx.state, "pending")
        self.assertEqual(tx.partner_id, self.partner)
        self.assertEqual(self.payload["customer"]["phoneNumber"], "4512345678")

    def test_nordic_local_phone_reaches_api_without_danish_rewrite(self):
        for region, currency in (("DK", "DKK"), ("FI", "EUR"), ("NO", "NOK")):
            self.provider.mobilepay_sales_unit_region = region
            currency_record = self.env.ref(f"base.{currency}")
            currency_record.active = True
            for country, phone, expected in (
                ("no", "91234567", "4791234567"),
                ("fi", "0401234567", "358401234567"),
                ("se", "0701234567", "46701234567"),
                ("gl", "123456", "299123456"),
                ("fo", "12345678", "4512345678"),
            ):
                with self.subTest(region=region, customer=country):
                    self.partner.country_id = self.env.ref(f"base.{country}")
                    params = self._params(currency_id=currency_record.id, mobilepay_phone=phone)
                    params["access_token"] = hmac_tool(
                        self.env(su=True), "generate_access_token",
                        f"{self.partner.id}|100.0|{currency_record.id}",
                    )
                    with patch.object(type(self.client), "create_payment",
                                      side_effect=self._create_response), patch.object(
                        type(self.provider), "get_base_url", return_value="https://sandbox.example.com"
                    ):
                        result = self._json_request("/payment/transaction", params)
                    self.assertIn("result", result, result)
                    self.assertEqual(self.payload["customer"]["phoneNumber"], expected)
                    self.assertEqual(self.payload["amount"], {"currency": currency, "value": 10000})

    def test_production_phone_payload_uses_edited_value_without_changing_partner(self):
        self.provider.write({
            "mobilepay_prod_client_id": "synthetic",
            "mobilepay_prod_client_secret": "synthetic",
            "mobilepay_prod_subscription_key": "synthetic",
            "mobilepay_prod_merchant_serial": "123456",
        })
        self.provider.state = "enabled"
        with patch.object(type(self.client), "create_payment", side_effect=self._create_response), \
             patch.object(type(self.provider), "get_base_url", return_value="https://sandbox.example.com"):
            result = self._json_request("/payment/transaction", self._params(
                mobilepay_phone="+4512345678",
            ))
        self.assertIn("result", result, result)
        self.assertEqual(self.payload["customer"]["phoneNumber"], "4512345678")
        with patch.object(type(self.client), "create_payment", side_effect=self._create_response), \
             patch.object(type(self.provider), "get_base_url", return_value="https://sandbox.example.com"):
            result = self._json_request("/payment/transaction", self._params(mobilepay_phone=""))
        self.assertIn("result", result, result)
        self.assertNotIn("phoneNumber", self.payload["customer"])
        self.assertEqual(self.partner.phone, "+4587654321")

    def test_invalid_phone_and_invalid_token_are_rejected(self):
        with patch.object(type(self.client), "create_payment") as create:
            for overrides in (
                {"mobilepay_phone": "call12345678"},
                {"mobilepay_phone": {"unexpected": True}},
                {"mobilepay_phone": "+4512345678", "access_token": "invalid"},
                {"mobilepay_phone": "+4512345678", "custom_create_values": {"amount": 1}},
            ):
                with self.subTest(overrides=overrides):
                    result = self._json_request("/payment/transaction", self._params(**overrides))
                    self.assertIn("error", result)
        create.assert_not_called()

    def test_http_base_url_blocks_payment_before_remote_request(self):
        with patch.object(type(self.client), "create_payment") as create, \
             patch.object(type(self.provider), "get_base_url", return_value="http://localhost:18080"):
            result = self._json_request("/payment/transaction", self._params(
                mobilepay_phone="+4512345678",
            ))
        self.assertIn("error", result)
        self.assertIn("HTTPS", result["error"]["data"]["message"])
        create.assert_not_called()

    def test_website_sale_route_accepts_phone_with_order_access_checks(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "pricelist_id": self.env["product.pricelist"].create({
                "name": "HTTP DKK", "currency_id": self.currency.id,
            }).id,
            "order_line": [(0, 0, {
                "product_id": self.env["product.product"].create({
                    "name": "HTTP Test Service", "type": "service",
                }).id,
                "product_uom_qty": 1, "price_unit": 100, "tax_id": [(5, 0, 0)],
            })],
        })
        order._portal_ensure_token()
        params = self._params(mobilepay_phone="+4512345678")
        params.pop("partner_id")
        params.pop("currency_id")
        params["access_token"] = order.access_token
        with patch.object(type(self.client), "create_payment", side_effect=self._create_response), \
             patch.object(type(self.provider), "get_base_url", return_value="https://sandbox.example.com"):
            result = self._json_request(f"/shop/payment/transaction/{order.id}", params)
        self.assertIn("result", result, result)
        self.assertEqual(order.transaction_ids.state, "pending")

    def _webhook_transaction(self):
        return self.env["payment.transaction"].create({
            "provider_id": self.provider.id, "payment_method_id": self.method.id,
            "partner_id": self.partner.id, "currency_id": self.currency.id,
            "reference": "HTTP-WEBHOOK", "mobilepay_api_reference": "HTTP-WEBHOOK",
            "mobilepay_payment_id": "HTTP-WEBHOOK", "amount": 100.0,
            "state": "pending", "operation": "online_redirect",
        })

    def _signed_webhook(self, tx, path="/payment/mobilepay/webhook"):
        body = json.dumps({
            "reference": tx.mobilepay_api_reference,
            "name": "epayments.payment.authorized.v1",
        }).encode()
        digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
        date = formatdate(usegmt=True)
        host = urlparse(self.base_url()).netloc
        signature = base64.b64encode(hmac.new(
            b"synthetic-webhook-secret",
            f"POST\n{path}\n{date};{host};{digest}".encode(), hashlib.sha256,
        ).digest()).decode()
        headers = {
            "Content-Type": "application/json", "Host": host,
            "x-ms-date": date, "x-ms-content-sha256": digest,
            "Authorization": (
                "HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256"
                f"&Signature={signature}"
            ),
        }
        return body, headers

    def test_signed_webhook_duplicates_and_return_do_not_duplicate_capture(self):
        tx = self._webhook_transaction()
        body, headers = self._signed_webhook(tx)
        status = {
            "state": "AUTHORIZED",
            "aggregate": {"authorizedAmount": {"currency": "DKK", "value": 10000}},
        }
        with patch.object(type(self.client), "get_payment_status", return_value=status), \
             patch.object(type(self.client), "get_payment_events", return_value=[]), \
             patch.object(type(self.client), "capture_payment") as capture:
            for _ in range(2):
                response = self.url_open("/payment/mobilepay/webhook", data=body, headers=headers)
                self.assertEqual(response.status_code, 200)
            response = self.url_open(f"/payment/mobilepay/return?reference={tx.reference}")
            self.assertEqual(response.status_code, 200)
        tx.invalidate_recordset()
        self.assertEqual(tx.state, "authorized")
        self.assertFalse(tx.child_transaction_ids)
        capture.assert_not_called()

    def test_tampered_body_and_missing_auth_rejected(self):
        tx = self._webhook_transaction()
        body, headers = self._signed_webhook(tx)
        with patch.object(type(self.client), "get_payment_status") as poll:
            response = self.url_open("/payment/mobilepay/webhook", data=body + b" ", headers=headers)
            self.assertEqual(response.status_code, 403)
            response = self.url_open("/payment/mobilepay/webhook", data=body)
            self.assertEqual(response.status_code, 403)
        poll.assert_not_called()

    def test_webhook_status_failure_requests_retry(self):
        from odoo.exceptions import UserError
        tx = self._webhook_transaction()
        body, headers = self._signed_webhook(tx)
        with patch.object(type(self.client), "get_payment_status", side_effect=UserError("Offline")):
            response = self.url_open("/payment/mobilepay/webhook", data=body, headers=headers)
        self.assertEqual(response.status_code, 503)

    def test_vipps_alias_signs_actual_path_and_query(self):
        tx = self._webhook_transaction()
        path = "/payment/vipps/webhook?source=acceptance"
        body, headers = self._signed_webhook(tx, path)
        with patch.object(type(self.client), "get_payment_status", return_value={
            "state": "AUTHORIZED",
            "aggregate": {"authorizedAmount": {"currency": "DKK", "value": 10000}},
        }), patch.object(type(self.client), "get_payment_events", return_value=[]):
            response = self.url_open(path, data=body, headers=headers)
        self.assertEqual(response.status_code, 200)
