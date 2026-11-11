from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase
from odoo.tests.common import new_test_user


class TestMobilePayAcceptance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dkk = cls.env.ref("base.DKK")
        cls.dkk.active = True
        cls.company = cls.env["res.company"].create({
            "name": "MobilePay Acceptance Company",
            "currency_id": cls.dkk.id,
            "country_id": cls.env.ref("base.dk").id,
        })
        cls.env = cls.env(context={**cls.env.context, "allowed_company_ids": cls.company.ids})

        def account(name, code, kind, reconcile=False):
            return cls.env["account.account"].create({
                "name": name, "code": code, "account_type": kind,
                "company_ids": [Command.set(cls.company.ids)], "reconcile": reconcile,
            })

        cls.bank_account = account("Bank", "AC1000", "asset_cash")
        cls.clearing = account("MobilePay Clearing", "AC1010", "asset_current", True)
        cls.receivable = account("Receivable", "AC1100", "asset_receivable", True)
        cls.payable = account("Payable", "AC2000", "liability_payable", True)
        cls.income = account("Sales", "AC3000", "income")
        cls.fee = account("MobilePay Fees", "AC5000", "expense")
        cls.bank_journal = cls.env["account.journal"].create({
            "name": "MobilePay Bank", "code": "MPB", "type": "bank",
            "company_id": cls.company.id, "default_account_id": cls.bank_account.id,
        })
        cls.sale_journal = cls.env["account.journal"].create({
            "name": "Sales", "code": "MPS", "type": "sale",
            "company_id": cls.company.id, "default_account_id": cls.income.id,
        })
        cls.provider = cls.env["payment.provider"].create({
            "name": "Acceptance MobilePay", "code": "mobilepay",
            "company_id": cls.company.id, "state": "test", "capture_mode": "manual",
            "mobilepay_journal_id": cls.bank_journal.id,
            "mobilepay_clearing_account_id": cls.clearing.id,
            "mobilepay_fee_account_id": cls.fee.id,
        })
        cls.provider.journal_id = cls.bank_journal
        cls.partner = cls.env["res.partner"].create({
            "name": "Acceptance Customer",
            "country_id": cls.env.ref("base.dk").id,
            "property_account_receivable_id": cls.receivable.id,
            "property_account_payable_id": cls.payable.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Acceptance Goods", "type": "consu",
            "list_price": 100, "property_account_income_id": cls.income.id,
            "taxes_id": [Command.clear()],
        })
        cls.client = cls.env["mobilepay.api.client"]

    def _transaction(self, **values):
        return self.env["payment.transaction"].create({
            "provider_id": self.provider.id,
            "payment_method_id": self.env.ref("mobilepay_payment.payment_method_mobilepay").id,
            "partner_id": self.partner.id,
            "currency_id": self.dkk.id,
            "reference": self.env["payment.transaction"]._compute_reference("mobilepay", prefix="ACCEPT"),
            "amount": 100, "authorized_amount": 100,
            "state": "authorized", "mobilepay_status": "AUTHORIZED",
            "mobilepay_api_reference": "ACCEPT-REMOTE",
            "mobilepay_payment_id": "ACCEPT-REMOTE",
            "provider_reference": "ACCEPT-REMOTE",
            "operation": "online_redirect",
            **values,
        })

    def test_accounting_user_can_configure_journal_when_method_is_missing(self):
        user = new_test_user(
            self.env, login="mobilepay-accounting-setup",
            groups="base.group_system,account.group_account_manager",
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
        )
        methods = self.env["account.payment.method"]
        self.assertFalse(methods.with_user(user).has_access("create"))
        methods.search([("code", "=", "mobilepay")]).write({
            "code": "mobilepay_setup_fixture",
        })
        journal = self.env["account.journal"].create({
            "name": "MobilePay Setup Bank", "code": "MPSB", "type": "bank",
            "company_id": self.company.id, "default_account_id": self.bank_account.id,
        })
        self.provider.with_user(user).write({"mobilepay_journal_id": journal.id})
        method = self.provider._get_provider_payment_method("mobilepay")
        self.assertTrue(method)
        line = journal.inbound_payment_method_line_ids.filtered(
            lambda record: record.payment_provider_id == self.provider
            and record.payment_method_id == method
        )
        self.assertEqual(len(line), 1)
        self.assertEqual(line.payment_account_id, self.clearing)
        self.provider.with_user(user).write({"mobilepay_journal_id": journal.id})
        self.assertEqual(len(journal.inbound_payment_method_line_ids.filtered(
            lambda record: record.payment_method_id == method
        )), 1)

    def _aggregate(self, captured=100, refunded=0, cancelled=0):
        return {"aggregate": {
            key: {"currency": "DKK", "value": int(round(value * 100))}
            for key, value in (
                ("authorizedAmount", 100), ("capturedAmount", captured),
                ("refundedAmount", refunded), ("cancelledAmount", cancelled),
            )
        }}

    def _invoice(self, move_type="out_invoice", amount=100):
        invoice = self.env["account.move"].create({
            "move_type": move_type, "partner_id": self.partner.id,
            "journal_id": self.sale_journal.id, "currency_id": self.dkk.id,
            "invoice_date": fields.Date.today(),
            "invoice_line_ids": [Command.create({
                "name": "Acceptance Sale", "account_id": self.income.id,
                "quantity": 1, "price_unit": amount, "tax_ids": [Command.clear()],
            })],
        })
        invoice.action_post()
        return invoice

    def _capture(self, tx, amount=None, total=100):
        with patch.object(type(self.client), "capture_payment", return_value=self._aggregate(total)):
            child = tx._send_capture_request(amount)
        (child or tx)._post_process()
        return child or tx

    def _settlement_entries(self, payout_id="ACCEPT-PAYOUT", refund=0):
        entries = [
            {"payoutId": payout_id, "entryType": "capture", "amount": 10000,
             "pspReference": "ACCEPT-REMOTE", "currency": "DKK", "date": "2026-11-11"},
            {"payoutId": payout_id, "entryType": "fee", "amount": 100,
             "currency": "DKK", "date": "2026-11-11"},
            {"payoutId": payout_id, "entryType": "payout", "amount": 9900 - refund * 100,
             "currency": "DKK", "date": "2026-11-11"},
        ]
        if refund:
            entries.append({
                "payoutId": payout_id, "entryType": "refund", "amount": -refund * 100,
                "pspReference": "ACCEPT-REMOTE", "currency": "DKK", "date": "2026-11-11",
            })
        return entries

    def _sync(self, entries):
        with patch.object(type(self.client), "get_settlement_reports", return_value=entries):
            self.provider._mobilepay_sync_settlements()

    def test_capture_posts_payment_and_reconciles_invoice(self):
        invoice = self._invoice()
        tx = self._transaction(invoice_ids=[Command.set(invoice.ids)])
        self._capture(tx)
        self.assertEqual(tx.payment_id.move_id.state, "posted")
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(tx.payment_id.journal_id, self.bank_journal)
        clearing_lines = tx.payment_id.move_id.line_ids.filtered(lambda l: l.account_id == self.clearing)
        self.assertEqual(sum(clearing_lines.mapped("balance")), 100)

    def test_two_partial_capture_payments_no_parent_double_payment(self):
        invoice = self._invoice()
        tx = self._transaction(invoice_ids=[Command.set(invoice.ids)])
        first = self._capture(tx, 40, 40)
        self.assertEqual(invoice.amount_residual, 60)
        second = self._capture(tx, 60, 100)
        tx._post_process()
        self.assertFalse(tx.payment_id)
        self.assertEqual(first.payment_id.amount + second.payment_id.amount, 100)
        self.assertEqual(invoice.amount_residual, 0)

    def test_refund_posts_outbound_payment_and_reconciles_credit_note(self):
        tx = self._transaction(invoice_ids=[Command.set(self._invoice().ids)])
        self._capture(tx)
        credit = self._invoice("out_refund", 25)
        with patch.object(type(self.client), "refund_payment", return_value=self._aggregate(100, 25)):
            refund = tx._send_refund_request(25)
        refund.invoice_ids = credit
        refund._post_process()
        self.assertEqual(refund.payment_id.payment_type, "outbound")
        self.assertEqual(refund.payment_id.source_payment_id, tx.payment_id)
        self.assertEqual(refund.payment_id.move_id.state, "posted")
        self.assertEqual(credit.amount_residual, 0)
        self.assertEqual(tx.payment_id.amount_available_for_refund, 75)

    def test_backend_refund_wizard_supports_partial_refunds(self):
        tx = self._transaction(invoice_ids=[Command.set(self._invoice().ids)])
        self._capture(tx)
        wizard = self.env["payment.refund.wizard"].create({
            "payment_id": tx.payment_id.id, "amount_to_refund": 25,
        })
        self.assertEqual(wizard.support_refund, "partial")
        with patch.object(type(self.client), "refund_payment", return_value=self._aggregate(100, 25)):
            wizard.action_refund()
        self.assertEqual(tx.child_transaction_ids.amount, -25)
        self.assertEqual(tx.child_transaction_ids.state, "done")

    def test_settlement_reconciles_real_clearing_lines_and_is_idempotent(self):
        tx = self._transaction(invoice_ids=[Command.set(self._invoice().ids)])
        self._capture(tx)
        entries = self._settlement_entries()
        self._sync(entries)
        settlement = self.env["mobilepay.settlement"].search([("payout_id", "=", "ACCEPT-PAYOUT")])
        self.assertEqual(settlement.state, "reconciled", settlement.note)
        self.assertEqual(settlement.journal_entry_id.state, "posted")
        clearing = (tx.payment_id.move_id + settlement.journal_entry_id).line_ids.filtered(
            lambda l: l.account_id == self.clearing
        )
        self.assertTrue(all(clearing.mapped("reconciled")))
        count = self.env["account.move"].search_count([("ref", "=", "ACCEPT-PAYOUT")])
        self._sync(entries)
        self.assertEqual(self.env["account.move"].search_count([("ref", "=", "ACCEPT-PAYOUT")]), count)
        self.assertEqual(settlement.net_amount, 99)

    def test_draft_settlement_repeat_does_not_duplicate_journal_entry(self):
        self.provider.mobilepay_auto_post_settlements = False
        self._sync(self._settlement_entries())
        self._sync(self._settlement_entries())
        self.assertEqual(self.env["account.move"].search_count([("ref", "=", "ACCEPT-PAYOUT")]), 1)

    def test_settlement_including_refund_reconciles_both_payments(self):
        tx = self._transaction(invoice_ids=[Command.set(self._invoice().ids)])
        self._capture(tx)
        with patch.object(type(self.client), "refund_payment", return_value=self._aggregate(100, 25)):
            refund = tx._send_refund_request(25)
        refund.invoice_ids = self._invoice("out_refund", 25)
        refund._post_process()
        self._sync(self._settlement_entries(refund=25))
        settlement = self.env["mobilepay.settlement"].search([("payout_id", "=", "ACCEPT-PAYOUT")])
        self.assertEqual(settlement.state, "reconciled", settlement.note)
        lines = (tx.payment_id.move_id | refund.payment_id.move_id | settlement.journal_entry_id
                 ).line_ids.filtered(lambda line: line.account_id == self.clearing)
        self.assertTrue(all(lines.mapped("reconciled")))
        self.assertEqual(settlement.net_amount, 74)

    def test_unmatched_settlement_retries_same_posted_move_after_payment_arrives(self):
        self._sync(self._settlement_entries())
        settlement = self.env["mobilepay.settlement"].search([("payout_id", "=", "ACCEPT-PAYOUT")])
        move = settlement.journal_entry_id
        self.assertEqual(settlement.state, "error")
        tx = self._transaction(invoice_ids=[Command.set(self._invoice().ids)])
        self._capture(tx)
        self._sync(self._settlement_entries())
        self.assertEqual(settlement.journal_entry_id, move)
        self.assertEqual(settlement.state, "reconciled", settlement.note)

    def test_foreign_currency_settlement_is_explicitly_blocked(self):
        self.env.ref("base.EUR").active = True
        entries = self._settlement_entries()
        for entry in entries:
            entry["currency"] = "EUR"
        self._sync(entries)
        settlement = self.env["mobilepay.settlement"].search([("payout_id", "=", "ACCEPT-PAYOUT")])
        self.assertEqual(settlement.state, "error")
        self.assertIn("Foreign-currency", settlement.note)
        self.assertFalse(settlement.journal_entry_id)

    def _order(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "product_uom_qty": 1, "price_unit": 100, "tax_id": [Command.clear()],
            })],
        })
        order.action_confirm()
        return order

    def test_delivery_validation_captures_once(self):
        self.provider.capture_mode = "delivery"
        order = self._order()
        tx = self._transaction(sale_order_ids=[Command.set(order.ids)])
        picking = order.picking_ids
        picking.move_ids.write({"quantity": 1, "picked": True})
        with patch.object(type(self.client), "capture_payment", return_value=self._aggregate()) as capture:
            picking.button_validate()
            picking._mobilepay_auto_capture_payments()
        self.assertEqual(picking.state, "done")
        self.assertEqual(tx.state, "done")
        capture.assert_called_once()

    def test_delivery_failure_keeps_authorization_and_notifies_operator(self):
        self.provider.capture_mode = "delivery"
        order = self._order()
        tx = self._transaction(sale_order_ids=[Command.set(order.ids)])
        picking = order.picking_ids
        picking.move_ids.write({"quantity": 1, "picked": True})
        with patch.object(type(self.client), "capture_payment", side_effect=UserError("Offline")):
            picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual(tx.state, "authorized")
        self.assertTrue(any("Offline" in (message.body or "") for message in picking.message_ids))

    def test_partial_delivery_backorder_preserves_full_first_delivery_capture(self):
        self.provider.capture_mode = "delivery"
        order = self._order()
        order.order_line.product_uom_qty = 2
        tx = self._transaction(sale_order_ids=[Command.set(order.ids)])
        picking = order.picking_ids
        picking.move_ids.write({"quantity": 1, "picked": True})
        with patch.object(type(self.client), "capture_payment", return_value=self._aggregate()) as capture:
            action = picking.button_validate()
            self.assertEqual(action["res_model"], "stock.backorder.confirmation")
            capture.assert_not_called()
            wizard = self.env[action["res_model"]].with_context(action["context"]).create({})
            wizard.process()
            backorder = order.picking_ids - picking
            self.assertEqual(len(backorder), 1)
            backorder.move_ids.write({"quantity": 1, "picked": True})
            backorder.button_validate()
        self.assertEqual(tx.captured_amount, 100)
        capture.assert_called_once()

    def test_cancel_warning_wizard_does_not_void_until_confirmed(self):
        order = self._order()
        tx = self._transaction(sale_order_ids=[Command.set(order.ids)])
        with patch.object(type(self.client), "cancel_payment") as cancel:
            action = order.action_cancel()
        self.assertEqual(action["res_model"], "sale.order.cancel")
        cancel.assert_not_called()
        self.assertEqual(tx.state, "authorized")
        wizard = self.env[action["res_model"]].with_context(action["context"]).create({})
        with patch.object(type(self.client), "cancel_payment", return_value=self._aggregate(
            captured=0, cancelled=100
        )) as cancel:
            wizard.action_cancel()
        cancel.assert_called_once()
        self.assertEqual(tx.state, "cancel")

    def test_order_cancellation_calls_remote_void_without_transaction_chatter(self):
        order = self._order()
        tx = self._transaction(sale_order_ids=[Command.set(order.ids)])
        with patch.object(type(self.client), "cancel_payment", return_value=self._aggregate(
            captured=0, cancelled=100
        )) as cancel:
            order.with_context(disable_cancel_warning=True).action_cancel()
        cancel.assert_called_once()
        self.assertEqual(order.state, "cancel")
        self.assertEqual(tx.state, "cancel")
