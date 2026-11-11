import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from lxml import etree, html

from odoo.addons.website.tools import MockRequest
from odoo.tests import HttpCase, tagged
from odoo.tools.misc import hmac as hmac_tool


@tagged("post_install", "-at_install")
class TestMarketBranding(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env.ref("mobilepay_payment.payment_provider_mobilepay")
        cls.provider.write({
            "state": "test", "is_published": True,
            "mobilepay_sales_unit_region": "DK",
            "mobilepay_branding_market": "sales_unit", "mobilepay_branding_2027": False,
        })
        cls.method = cls.env.ref("mobilepay_payment.payment_method_mobilepay")
        cls.method.active = True
        cls.website = cls.env.ref("website.default_website")

    def _on_date(self, on_date):
        return patch(
            "odoo.addons.mobilepay_payment.models.payment_provider.datetime",
            **{"now.return_value": datetime.combine(on_date, datetime.min.time(), timezone.utc)},
        )

    def _render(self, on_date, template="payment.method_form"):
        with self._on_date(on_date), MockRequest(
            self.env(user=self.website.user_id), website=self.website,
        ):
            markup = self.env["ir.ui.view"]._render_template(template, {
                "provider_sudo": self.provider,
                "provider_id": self.provider.id,
                "pm_sudo": self.method,
                "providers_sudo": self.provider,
                "mode": "payment",
                "is_selected": True,
            })
        return html.fromstring(str(markup))

    def test_market_names_and_assets_before_cutover(self):
        for market, name, asset in (
            ("DK", "MobilePay", "mobilepay_logo.svg"),
            ("FI", "MobilePay", "mobilepay_logo.svg"),
            ("NO", "Vipps", "vipps_orange.svg"),
            ("SE", "Vipps", "vipps_orange.svg"),
        ):
            with self.subTest(market=market):
                self.provider.mobilepay_branding_market = market
                with self._on_date(date(2027, 1, 11)):
                    branding = self.provider._mobilepay_checkout_branding()
                self.assertEqual(branding["name"], name)
                self.assertTrue(branding["logo"].endswith(asset))
                self.assertEqual(branding["payment_label"], f"Pay with {name}")

    def test_cutover_requires_approval_and_never_switches_early(self):
        for market in ("DK", "FI"):
            self.provider.mobilepay_branding_market = market
            for approved, on_date, name, asset in (
                (False, date(2027, 1, 12), "MobilePay", "mobilepay_logo.svg"),
                (True, date(2027, 1, 11), "MobilePay", "mobilepay_logo.svg"),
                (True, date(2027, 1, 12), "Vipps", "vipps_blue.svg"),
                (True, date(2027, 1, 13), "Vipps", "vipps_blue.svg"),
                (False, date(2028, 1, 1), "MobilePay", "mobilepay_logo.svg"),
            ):
                with self.subTest(market=market, approved=approved, on_date=on_date):
                    self.provider.mobilepay_branding_2027 = approved
                    with self._on_date(on_date) as clock:
                        branding = self.provider._mobilepay_checkout_branding()
                        if approved:
                            clock.now.assert_called_once_with(timezone.utc)
                    self.assertEqual(branding["name"], name)
                    self.assertTrue(branding["logo"].endswith(asset))

    def test_orange_markets_do_not_become_blue(self):
        self.provider.mobilepay_branding_2027 = True
        for market in ("NO", "SE"):
            self.provider.mobilepay_branding_market = market
            with self._on_date(date(2027, 1, 12)):
                self.assertTrue(
                    self.provider._mobilepay_checkout_branding()["logo"].endswith("vipps_orange.svg")
                )

    def test_market_is_independent_of_currency_and_language(self):
        self.provider.mobilepay_branding_market = "SE"
        for language in ("sv_SE", "da_DK"):
            self.env["res.lang"]._activate_lang(language)
        for region, currency in (("DK", "DKK"), ("FI", "EUR"), ("NO", "NOK")):
            self.provider.mobilepay_sales_unit_region = region
            for language in ("en_US", "sv_SE", "da_DK"):
                with self.subTest(region=region, language=language):
                    provider = self.provider.with_context(lang=language)
                    self.assertEqual(provider._mobilepay_checkout_branding()["name"], "Vipps")
                    self.assertEqual(provider._mobilepay_currency_code(), currency)
                    self.assertEqual(provider._get_supported_currencies().name, currency)

    def test_default_market_follows_sales_unit(self):
        self.provider.mobilepay_branding_market = "sales_unit"
        for region, name in (("DK", "MobilePay"), ("FI", "MobilePay"), ("NO", "Vipps")):
            self.provider.mobilepay_sales_unit_region = region
            self.assertEqual(self.provider._mobilepay_checkout_branding()["name"], name)

    def test_public_checkout_label_inline_logo_and_secured_by_agree(self):
        for market, approved, on_date, name, asset in (
            ("DK", False, date(2026, 11, 11), "MobilePay", "mobilepay_logo.svg"),
            ("FI", True, date(2027, 1, 11), "MobilePay", "mobilepay_logo.svg"),
            ("FI", True, date(2027, 1, 12), "Vipps", "vipps_blue.svg"),
            ("DK", True, date(2027, 1, 12), "Vipps", "vipps_blue.svg"),
            ("NO", False, date(2026, 11, 11), "Vipps", "vipps_orange.svg"),
            ("SE", True, date(2027, 1, 12), "Vipps", "vipps_orange.svg"),
        ):
            with self.subTest(market=market, on_date=on_date):
                self.provider.write({
                    "mobilepay_branding_market": market, "mobilepay_branding_2027": approved,
                })
                document = self._render(on_date)
                self.assertEqual(
                    document.xpath("//label[contains(@class, 'o_payment_option_label')]")[0]
                    .text_content(), name,
                )
                self.assertEqual(
                    document.xpath("//p[@name='o_payment_secured_by']/span[last()]")[0]
                    .text_content(), name,
                )
                images = document.xpath("//img")
                self.assertEqual(len(images), 2)
                for image in images:
                    self.assertTrue(image.get("src").endswith(asset))
                    self.assertEqual(image.get("alt"), name)
                self.assertIn(f"Pay with {name}", document.text_content())
                radios = document.xpath("//input[@name='o_payment_radio']")
                self.assertEqual(radios[0].get("data-provider-code"), "mobilepay")
                self.assertEqual(radios[0].get("data-payment-method-code"), "mobilepay")

    def test_render_does_not_mutate_shared_names_images_or_credentials(self):
        self.provider.name = "Custom Merchant Provider"
        self.method.name = "Custom Wallet"
        self.provider.mobilepay_test_client_secret = "synthetic-branding-secret"
        before = (
            self.provider.name, self.method.name, self.provider.image_128,
            self.method.image, self.provider.mobilepay_test_client_secret_encrypted,
        )
        for market in ("NO", "DK", "SE", "FI"):
            self.provider.mobilepay_branding_market = market
            self._render(date(2027, 1, 12))
        after = (
            self.provider.name, self.method.name, self.provider.image_128,
            self.method.image, self.provider.mobilepay_test_client_secret_encrypted,
        )
        self.assertEqual(before, after)

    def test_other_payment_methods_keep_their_own_label_and_image(self):
        other = self.env["payment.provider"].create({"name": "Other", "code": "none"})
        method = self.method.copy({"name": "Other Wallet", "code": "other", "provider_ids": [(6, 0, other.ids)]})
        with MockRequest(self.env, website=self.website):
            document = html.fromstring(str(self.env["ir.ui.view"]._render_template(
                "payment.method_form", {
                    "provider_sudo": other, "providers_sudo": other, "pm_sudo": method,
                    "mode": "payment", "is_selected": True,
                },
            )))
        self.assertEqual(
            document.xpath("//label[contains(@class, 'o_payment_option_label')]")[0]
            .text_content(), "Other Wallet",
        )
        self.assertFalse(document.xpath("//img[contains(@src, '/mobilepay_payment/')]"))

    def test_official_paymarks_are_unmodified_and_valid_svg(self):
        image_dir = Path(__file__).parents[1] / "static" / "img"
        for asset, digest in (
            ("vipps_orange.svg", "69e3f60b5eb3c6f2b7213bdf5849329ec4840121da2f28c54e8e6f06ac2ca983"),
            ("vipps_blue.svg", "5b8936765bbd2ce164cea2bccd0410d46d537fae6def0b649eea367f40c05a4b"),
        ):
            content = (image_dir / asset).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), digest)
            self.assertEqual(etree.fromstring(content).tag, "{http://www.w3.org/2000/svg}svg")

    def test_guest_payment_page_uses_market_brand_and_serves_assets(self):
        partner = self.env["res.partner"].create({
            "name": "Branding Guest", "country_id": self.env.ref("base.dk").id,
        })
        currency = self.env.ref("base.DKK")
        currency.active = True
        token = hmac_tool(
            self.env(su=True), "generate_access_token", f"{partner.id}|100.0|{currency.id}",
        )
        url = "/payment/pay?" + urlencode({
            "amount": "100", "currency_id": currency.id,
            "partner_id": partner.id, "access_token": token,
        })
        for market, approved, on_date, name, asset in (
            ("DK", False, date(2026, 11, 11), "MobilePay", "mobilepay_logo.svg"),
            ("NO", False, date(2026, 11, 11), "Vipps", "vipps_orange.svg"),
            ("SE", False, date(2026, 11, 11), "Vipps", "vipps_orange.svg"),
            ("FI", True, date(2027, 1, 12), "Vipps", "vipps_blue.svg"),
        ):
            with self.subTest(market=market):
                self.provider.write({
                    "mobilepay_branding_market": market,
                    "mobilepay_branding_2027": approved,
                })
                with self._on_date(on_date):
                    response = self.url_open(url)
                self.assertEqual(response.status_code, 200)
                document = html.fromstring(response.text)
                radio = document.xpath(
                    f"//input[@name='o_payment_radio'][@data-provider-id='{self.provider.id}']"
                )
                self.assertEqual(len(radio), 1)
                label = document.xpath(f"//label[@for='{radio[0].get('id')}']")[0]
                self.assertEqual(label.text_content(), name)
                images = document.xpath(
                    f"//img[@src='/mobilepay_payment/static/img/{asset}'][@alt='{name}']"
                )
                self.assertEqual(len(images), 2)
                asset_response = self.url_open(images[0].get("src"))
                self.assertEqual(asset_response.status_code, 200)
                self.assertEqual(
                    etree.fromstring(asset_response.content).tag, "{http://www.w3.org/2000/svg}svg"
                )
