# -*- coding: utf-8 -*-
{
    "version": "17.0.1.1.37",
    "category": "Accounting/Payment Providers",
    "summary": "Payment Provider: MobilePay (Vipps) for Danish market",
    "description": """
MobilePay Payment Provider for Odoo 17

This module integrates Vipps MobilePay ePayment API v3 with Odoo, providing:
- Flexible Capture flows: Manual, Capture on Delivery (Stock integration), or Automatic after delay
- Immediate payments and refunds (Full/Partial)
- Real-time webhook processing with HMAC security
- Phone number pre-fill for enhanced UX
- Secure credential management with Fernet encryption
- Diagnostic tools: API connection test and Webhook management
- Danish market support (DKK currency)

Supports both Odoo Enterprise and Community editions.
    """,
    "author": "Wather",
    "website": "Not yet",
    "license": "LGPL-3",
    "depends": [
        "payment",
        "account",
        "website_sale",
        "stock",
        "sale_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/mobilepay_templates.xml",
        "data/payment_provider_data.xml",
        "data/system_parameters.xml",
        "data/ir_cron_data.xml",
        "views/payment_provider_views.xml",
        "views/payment_transaction_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "mobilepay_payment/static/src/js/payment_form.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "external_dependencies": {
        "python": ["requests", "cryptography"],
    },
}
