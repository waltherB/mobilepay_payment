from odoo import Command, SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    method = env.ref("mobilepay_payment.payment_method_mobilepay").with_context(lang="en_US")
    # Only expand the old defaults; empty or customized restrictions are operator policy.
    if method.supported_country_ids == env.ref("base.dk"):
        method.supported_country_ids = [Command.set([
            env.ref(f"base.{code}").id for code in ("dk", "fi", "no", "se", "gl", "fo")
        ])]
    if method.supported_currency_ids == env.ref("base.DKK"):
        method.supported_currency_ids = [Command.set([
            env.ref(f"base.{code}").id for code in ("DKK", "EUR", "NOK")
        ])]
    provider = env.ref("mobilepay_payment.payment_provider_mobilepay").with_context(lang="en_US")
    for record in (method, provider):
        if record.name == "MobilePay":
            record.name = "Vipps / MobilePay"
