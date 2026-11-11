from odoo import _
from odoo.exceptions import ValidationError

from odoo.addons.payment.controllers.portal import PaymentPortal


class MobilePayPaymentPortal(PaymentPortal):
    def _validate_transaction_kwargs(self, kwargs, additional_allowed_keys=()):
        return super()._validate_transaction_kwargs(
            kwargs, additional_allowed_keys=(*additional_allowed_keys, "mobilepay_phone")
        )

    def _create_transaction(self, *args, mobilepay_phone=None, **kwargs):
        if mobilepay_phone is not None and (
            not isinstance(mobilepay_phone, str) or len(mobilepay_phone) > 64
        ):
            raise ValidationError(_("Please enter a valid MobilePay phone number."))
        tx = super()._create_transaction(*args, **kwargs)
        if tx.provider_code == "mobilepay" and mobilepay_phone is not None:
            phone = mobilepay_phone.strip()
            if phone and not tx._format_phone_number_v3(phone):
                raise ValidationError(_("Please enter a valid MobilePay phone number."))
            return tx.with_context(mobilepay_phone=phone)
        return tx
