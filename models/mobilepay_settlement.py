# -*- coding: utf-8 -*-

from odoo import models, fields

class MobilePaySettlement(models.Model):
    _name = "mobilepay.settlement"
    _description = "MobilePay Payout Settlement Tracker"
    _order = "settlement_date desc, id desc"

    payout_id = fields.Char(
        string="Payout ID",
        required=True,
        index=True,
        copy=False,
        help="Unique payout/settlement transfer reference from MobilePay/Vipps API.",
    )
    settlement_date = fields.Date(
        string="Settlement Date",
        required=True,
        index=True,
        copy=False,
    )
    gross_amount = fields.Monetary(
        string="Gross Amount",
        required=True,
        currency_field="currency_id",
        copy=False,
        help="Total customer payments processed in this batch.",
    )
    fee_amount = fields.Monetary(
        string="Fee Amount",
        required=True,
        currency_field="currency_id",
        copy=False,
        help="Total commissions and transaction fees deducted.",
    )
    net_amount = fields.Monetary(
        string="Net Payout Amount",
        required=True,
        currency_field="currency_id",
        copy=False,
        help="The net cash amount transferred to the merchant's bank account (Gross - Fees).",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    journal_entry_id = fields.Many2one(
        "account.move",
        string="Journal Entry",
        copy=False,
        help="The Odoo Journal Entry generated for this payout reconciliation.",
    )
    state = fields.Selection(
        [
            ("draft", "Draft Entry"),
            ("reconciled", "Posted & Reconciled"),
            ("error", "Error"),
        ],
        string="Status",
        default="draft",
        required=True,
        copy=False,
        index=True,
    )
    note = fields.Text(
        string="Notes / Traceback",
        copy=False,
    )

    _sql_constraints = [
        (
            "payout_id_unique",
            "unique(payout_id)",
            "The Payout ID must be unique. This settlement has already been logged.",
        )
    ]
