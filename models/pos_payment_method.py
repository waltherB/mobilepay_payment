# -*- coding: utf-8 -*-

from odoo import fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    use_payment_terminal = fields.Selection(
        selection_add=[("mobilepay", "MobilePay")],
        ondelete={"mobilepay": "set default"},
    )

    # -------------------------------------------------------------------------
    # MobilePay-specific POS terminal configuration
    # -------------------------------------------------------------------------
    mobilepay_pos_provider_id = fields.Many2one(
        "payment.provider",
        string="MobilePay Provider",
        domain=[("code", "=", "mobilepay")],
        help=(
            "The MobilePay payment.provider whose API credentials will be used "
            "for this POS payment method. Leave empty to auto-select the first "
            "active MobilePay provider for the current company."
        ),
    )
    mobilepay_pos_default_mode = fields.Selection(
        [
            ("prompt", "Ask operator each time"),
            ("phone_push", "Always use Phone Push"),
            ("qr_code", "Always show QR Code"),
        ],
        string="Default Payment Mode",
        default="prompt",
        required=True,
        help=(
            "'Ask operator each time' shows a dialog on every payment.\n"
            "'Always use Phone Push' skips the dialog and immediately sends "
            "a push notification (customer phone number is still requested).\n"
            "'Always show QR Code' skips the dialog and immediately generates "
            "a QR code."
        ),
    )
    mobilepay_pos_timeout = fields.Integer(
        string="Payment Timeout (seconds)",
        default=60,
        help=(
            "Number of seconds the POS will poll for a payment confirmation "
            "before automatically cancelling the request. Minimum 10, maximum 300."
        ),
    )
