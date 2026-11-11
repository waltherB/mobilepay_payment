# -*- coding: utf-8 -*-
{
    "name": "MobilePay (Vipps) Payment Provider",
    "version": "18.0.1.2.0",
    "category": "Accounting/Payment Providers",
    "summary": "Vipps MobilePay payments for Nordic customers",
    "description": """
MobilePay Payment Provider for Odoo 18

Development integration with the Vipps MobilePay ePayment API:
- Payment creation, redirect, authorization, full and partial capture
- Credential management with Fernet encryption
- Webhook, status polling, delivery capture and settlement integration code
- Diagnostic tools for API connection and webhook management
- Nordic customers, Danish/DKK, Finnish/EUR and Norwegian/NOK sales units
- Danish, Finnish, Norwegian Bokmal and Swedish translations

Void/cancel, refund children, delayed capture and checkout phone transport have
local regression coverage. Odoo 18 Community installation, update, browser,
delivery and accounting workflows are tested with synthetic/mocked payments.
Not production-ready: live merchant/app/proxy acceptance is blocked, and the
legacy settlement API adapter still requires migration to the published API.
Enterprise has not been tested.
See README.md and MIGRATION-18.0.md for validation results and limitations.
    """,
    "author": "Walther",
    "website": "Not yet",
    "license": "LGPL-3",
    "depends": [
        "payment",
        "account",
        "website_sale",
        "stock",
        "sale_stock",
        "sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/mobilepay_templates.xml",
        "data/payment_provider_data.xml",
        "data/system_parameters.xml",
        "data/ir_cron_data.xml",
        "views/payment_provider_views.xml",
        "views/payment_transaction_views.xml",
        "views/mobilepay_settlement_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "mobilepay_payment/static/src/js/payment_form.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "uninstall_hook": "uninstall_hook",
    "external_dependencies": {
        "python": ["requests", "cryptography"],
    },
}
