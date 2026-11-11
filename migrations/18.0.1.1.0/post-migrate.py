from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env.ref("mobilepay_payment.payment_method_mobilepay").support_refund = "partial"
