import json
import re
from collections import Counter
from pathlib import Path
from types import MethodType

import polib
from lxml import etree, html

from odoo.addons.http_routing.controllers.main import Routing
from odoo.addons.website.tools import MockRequest
from odoo.http import Request
from odoo.tests import TransactionCase, tagged
from odoo.tools.translate import code_translations, get_po_paths


ADDON = Path(__file__).resolve().parents[1]
LANGUAGES = {"da": "da_DK", "fi": "fi_FI", "nb": "nb_NO", "sv": "sv_SE"}
PLACEHOLDER = re.compile(
    r"%(?:\([^)]+\))?[#0 +\-]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa%]"
)
MARKUP = re.compile(r"</?[A-Za-z][^>]*>")
JS_TERMS = (
    "Invalid phone number",
    "Enter a valid phone number, preferably with its country code, or leave it blank.",
)
BACKEND_TERM = "Please enter a valid Vipps or MobilePay phone number with country code."


def term_key(entry):
    return entry.msgctxt, entry.msgid, entry.msgid_plural


@tagged("post_install", "-at_install")
class TestNordicLocalization(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = polib.pofile(str(ADDON / "i18n/mobilepay_payment.pot"))
        cls.catalogs = {
            code: polib.pofile(str(ADDON / f"i18n/{code}.po"))
            for code in LANGUAGES
        }

    def test_complete_current_catalog_inventory(self):
        expected = {term_key(entry): entry for entry in self.template}
        self.assertEqual(len(expected), 258)
        self.assertEqual(len(expected), len(self.template), "Duplicate POT terms")
        for code, catalog in self.catalogs.items():
            with self.subTest(language=code):
                actual = {term_key(entry): entry for entry in catalog}
                self.assertEqual(len(catalog), len(actual), "Duplicate PO terms")
                self.assertEqual(set(actual), set(expected))
                self.assertEqual(catalog.metadata["Language"], code)
                self.assertIn("Odoo Server 18.0", catalog.metadata["Project-Id-Version"])
                self.assertEqual(catalog.metadata["Content-Type"], "text/plain; charset=UTF-8")
                self.assertEqual(
                    catalog.metadata["Plural-Forms"], "nplurals=2; plural=(n != 1);"
                )
                self.assertFalse(catalog.metadata_is_fuzzy)
                for key, entry in actual.items():
                    with self.subTest(term=entry.msgid):
                        self.assertFalse(entry.obsolete)
                        self.assertNotIn("fuzzy", entry.flags)
                        self.assertTrue(entry.msgstr.strip(), "Missing translation")
                        self.assertEqual(entry.occurrences, expected[key].occurrences)
                        self.assertEqual(entry.comment, expected[key].comment)
                        self.assertEqual(entry.tcomment, expected[key].tcomment)
                        self.assertEqual(entry.flags, expected[key].flags)
                        if entry.msgstr == entry.msgid:
                            allowed_shared_terms = {
                                "MobilePay",
                                "Vipps / MobilePay",
                                "ID",
                                "Status",
                                "Finland (EUR)",
                            }
                            if code in {"da", "nb", "sv"}:
                                allowed_shared_terms.add("Finland")
                            self.assertIn(
                                entry.msgid,
                                allowed_shared_terms,
                                "Untranslated English source",
                            )

    def test_translation_placeholders_markup_and_brands(self):
        for code, catalog in self.catalogs.items():
            for entry in catalog:
                with self.subTest(language=code, term=entry.msgid):
                    self.assertEqual(
                        Counter(PLACEHOLDER.findall(entry.msgid)),
                        Counter(PLACEHOLDER.findall(entry.msgstr)),
                    )
                    self.assertEqual(
                        MARKUP.findall(entry.msgid), MARKUP.findall(entry.msgstr)
                    )
                    self.assertEqual(entry.msgid.count("\n"), entry.msgstr.count("\n"))
                    self.assertEqual(entry.msgid.startswith(" "), entry.msgstr.startswith(" "))
                    for brand in ("MobilePay", "Vipps", "Ocp-Apim-Subscription-Key", "web.base.url"):
                        if brand in entry.msgid:
                            self.assertEqual(entry.msgid.count(brand), entry.msgstr.count(brand))

    def test_current_checkout_backend_and_javascript_references(self):
        template = self.template
        phone = template.find("Phone Number")
        self.assertIn(
            ("model_terms:ir.ui.view,arch_db:mobilepay_payment.mobilepay_inline_form", ""),
            phone.occurrences,
        )
        checkout = etree.parse(str(ADDON / "views/mobilepay_templates.xml"))
        self.assertTrue(checkout.xpath("//template[@id='mobilepay_inline_form']//label"))
        self.assertFalse(checkout.xpath("//template[@id='inline_form']"))
        for entry in template:
            for reference, _line in entry.occurrences:
                self.assertNotEqual(
                    reference, "model_terms:ir.ui.view,arch_db:mobilepay_payment.inline_form"
                )
        for term in JS_TERMS:
            entry = template.find(term)
            self.assertIsNotNone(entry)
            self.assertIn("odoo-javascript", entry.comment)
            self.assertIn(
                ("code:addons/mobilepay_payment/static/src/js/payment_form.js", "0"),
                entry.occurrences,
            )
            self.assertIn(term, (ADDON / "static/src/js/payment_form.js").read_text())
        backend = template.find(BACKEND_TERM)
        self.assertIn("odoo-python", backend.comment)
        self.assertIn(
            ("code:addons/mobilepay_payment/controllers/payment_portal.py", "0"),
            backend.occurrences,
        )
        self.assertIn(
            ("code:addons/mobilepay_payment/models/payment_transaction.py", "0"),
            backend.occurrences,
        )

    def test_odoo_language_aliases_and_python_translation_loading(self):
        for code, locale in LANGUAGES.items():
            with self.subTest(language=locale):
                self.assertIn(
                    ADDON / f"i18n/{code}.po",
                    [Path(path).resolve() for path in get_po_paths("mobilepay_payment", locale)],
                )
                translated = code_translations.get_python_translations("mobilepay_payment", locale)
                self.assertEqual(
                    translated[BACKEND_TERM], self.catalogs[code].find(BACKEND_TERM).msgstr
                )

    def test_public_frontend_translation_payload(self):
        website = self.env.ref("website.default_website")
        public = website.user_id
        self.assertTrue(public._is_public())
        for code, locale in LANGUAGES.items():
            with self.subTest(language=locale):
                self.env["res.lang"]._activate_lang(locale)
                # Exercise the public website controller without changing a user's language.
                with MockRequest(
                    self.env(user=public), website=website, context={"lang": locale}
                ) as request:
                    request.make_response = MethodType(Request.make_response, request)
                    request.make_json_response = MethodType(
                        Request.make_json_response, request
                    )
                    response = Routing().get_website_translations(
                        "nordic-test", lang=locale
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "application/json")
                payload = json.loads(response.get_data(as_text=True))
                self.assertEqual(payload["lang"], locale)
                messages = {
                    item["id"]: item["string"]
                    for item in payload["modules"]["mobilepay_payment"]["messages"]
                }
                for term in JS_TERMS:
                    self.assertEqual(messages[term], self.catalogs[code].find(term).msgstr)

    def test_translated_checkout_rendering_and_backend_fields(self):
        website = self.env.ref("website.default_website")
        provider = self.env.ref("mobilepay_payment.payment_provider_mobilepay")
        source_help = self.template.find(
            '<small class="form-text text-muted">Enter your Vipps or MobilePay phone '
            "number with country code, or leave it blank. Local numbers use your billing "
            "country.</small>"
        ).msgid
        provider.write(
            {"mobilepay_branding_market": "DK", "mobilepay_branding_2027": False}
        )
        for code, locale in LANGUAGES.items():
            with self.subTest(language=locale):
                self.env["res.lang"]._activate_lang(locale)
                self.env["ir.module.module"]._load_module_terms(
                    ["mobilepay_payment"], [locale], overwrite=True
                )
                public_env = self.env(
                    user=website.user_id, context=dict(self.env.context, lang=locale)
                )
                provider_sudo = provider.with_env(public_env).sudo()
                with MockRequest(public_env, website=website, context={"lang": locale}):
                    rendered = public_env["ir.ui.view"]._render_template(
                        "mobilepay_payment.mobilepay_inline_form",
                        {"provider_id": provider.id, "provider_sudo": provider_sudo},
                    )
                document = html.fromstring(str(rendered))
                catalog = self.catalogs[code]
                self.assertEqual(
                    document.xpath("//label")[0].text_content(),
                    catalog.find("Phone Number").msgstr,
                )
                self.assertEqual(
                    document.xpath("//input[@name='mobilepay_phone']")[0].get("placeholder"),
                    catalog.find("Phone number with country code").msgstr,
                )
                self.assertEqual(
                    document.xpath("//small")[0].text_content(),
                    html.fromstring(catalog.find(source_help).msgstr).text_content(),
                )
                self.assertEqual(
                    document.xpath("//span")[0].text_content(),
                    catalog.find("Pay with MobilePay").msgstr,
                )
                provider.write({"mobilepay_branding_market": "SE"})
                provider_sudo = provider.with_env(public_env).sudo()
                with MockRequest(public_env, website=website, context={"lang": locale}):
                    vipps_rendered = public_env["ir.ui.view"]._render_template(
                        "mobilepay_payment.mobilepay_inline_form",
                        {"provider_id": provider.id, "provider_sudo": provider_sudo},
                    )
                vipps_document = html.fromstring(str(vipps_rendered))
                self.assertEqual(
                    vipps_document.xpath("//span")[0].text_content(),
                    catalog.find("Pay with Vipps").msgstr,
                )
                provider.write({"mobilepay_branding_market": "DK"})
                fields = self.env["payment.provider"].with_context(lang=locale).fields_get(
                    ["mobilepay_sales_unit_region"]
                )
                self.assertEqual(
                    fields["mobilepay_sales_unit_region"]["string"],
                    catalog.find("Sales Unit Region").msgstr,
                )
