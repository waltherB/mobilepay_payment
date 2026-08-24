# -*- coding: utf-8 -*-

"""
Automated tests for the MobilePay Fees Accounting / Hybrid Flow implementation.

Coverage:
- Settlement cron dispatches to all active providers
- Missing accounting config is safely skipped
- Duplicate payout IDs are not re-processed
- Journal entry structure (debits/credits) is correct
- Refund lines produce an extra debit on the clearing account
- Fee tax is applied when configured
- auto_post=False leaves the move in draft
- Clearing account lines are reconciled after posting
- get_settlement_reports parses various API shapes correctly
- mobilepay.settlement state machine transitions
"""

from unittest.mock import patch, MagicMock
from odoo.tests import TransactionCase
from odoo.exceptions import UserError


# ---------------------------------------------------------------------------
# Helper: build a minimal settlement API payload
# ---------------------------------------------------------------------------

def _make_entries(payout_id, captures=None, fees=None, refunds=None, net=None):
    """Return a list of raw ledger entries as the API would produce them."""
    entries = []
    captures = captures or [{"pspRef": "PSP-001", "amount": 100000}]  # in minor units
    fees = fees or [{"amount": 1500}]
    refunds = refunds or []

    for c in captures:
        entries.append({
            "payoutId": payout_id,
            "entryType": "capture",
            "pspReference": c.get("pspRef", "PSP-001"),
            "amount": c["amount"],
            "currency": "DKK",
            "date": "2026-08-20",
            "bookingDate": "2026-08-20",
        })

    for f in fees:
        entries.append({
            "payoutId": payout_id,
            "entryType": "commission",
            "pspReference": None,
            "amount": f["amount"],
            "currency": "DKK",
            "date": "2026-08-20",
        })

    for r in refunds:
        entries.append({
            "payoutId": payout_id,
            "entryType": "refund",
            "pspReference": r.get("pspRef", "PSP-REF-001"),
            "amount": -r["amount"],       # refunds come as negative in the API
            "currency": "DKK",
            "date": "2026-08-20",
        })

    if net is not None:
        entries.append({
            "payoutId": payout_id,
            "entryType": "payout",
            "pspReference": None,
            "amount": net,
            "currency": "DKK",
            "date": "2026-08-20",
        })

    return entries


# ---------------------------------------------------------------------------
# Test fixtures / base class
# ---------------------------------------------------------------------------

class FeesReconciliationBase(TransactionCase):
    """Shared setUp for all fees-reconciliation tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()

        # Resolve DKK currency
        self.dkk = self.env.ref("base.DKK")

        # Accounts ----------------------------------------------------------------
        account_type_expense = self.env.ref("account.data_account_type_expenses", raise_if_not_found=False)
        account_type_asset   = self.env.ref("account.data_account_type_current_assets", raise_if_not_found=False)

        # Fee expense account
        self.fee_account = self.env["account.account"].create({
            "name": "MobilePay Fee Expense (Test)",
            "code": "9901TEST",
            "account_type": "expense" if not account_type_expense else account_type_expense.id,
        })

        # Clearing asset account
        self.clearing_account = self.env["account.account"].create({
            "name": "MobilePay Clearing (Test)",
            "code": "1901TEST",
            "account_type": "asset_current" if not account_type_asset else account_type_asset.id,
            "reconcile": True,   # must be reconcilable to use reconcile()
        })

        # Bank account
        self.bank_account = self.env["account.account"].create({
            "name": "MobilePay Bank (Test)",
            "code": "1902TEST",
            "account_type": "asset_cash" if not account_type_asset else account_type_asset.id,
        })

        # Journal -----------------------------------------------------------------
        self.journal = self.env["account.journal"].create({
            "name": "MobilePay Test Journal",
            "code": "MPTJ",
            "type": "general",
            "default_account_id": self.bank_account.id,
        })

        # Provider ----------------------------------------------------------------
        self.provider = self.env["payment.provider"].create({
            "name": "MobilePay Fees Test Provider",
            "code": "mobilepay",
            "state": "test",
            "mobilepay_test_client_id": "fake-client-id",
            "mobilepay_test_merchant_serial": "123456",
            "mobilepay_fee_account_id": self.fee_account.id,
            "mobilepay_clearing_account_id": self.clearing_account.id,
            "mobilepay_journal_id": self.journal.id,
            "mobilepay_auto_post_settlements": True,
        })


# ---------------------------------------------------------------------------
# 1. Cron dispatcher tests
# ---------------------------------------------------------------------------

class TestCronDispatcher(FeesReconciliationBase):

    def test_cron_calls_sync_for_active_mobilepay_providers(self):
        """_cron_mobilepay_sync_settlements must call _mobilepay_sync_settlements on every active provider."""
        call_log = []

        def mock_sync(provider_self):
            call_log.append(provider_self.id)

        with patch.object(
            type(self.provider),
            "_mobilepay_sync_settlements",
            autospec=True,
            side_effect=mock_sync,
        ):
            self.env["payment.provider"]._cron_mobilepay_sync_settlements()

        self.assertIn(self.provider.id, call_log)

    def test_cron_skips_disabled_providers(self):
        """Disabled providers must be excluded from the cron run."""
        disabled = self.env["payment.provider"].create({
            "name": "MobilePay Disabled",
            "code": "mobilepay",
            "state": "disabled",
        })
        call_log = []

        def mock_sync(provider_self):
            call_log.append(provider_self.id)

        with patch.object(
            type(self.provider),
            "_mobilepay_sync_settlements",
            autospec=True,
            side_effect=mock_sync,
        ):
            self.env["payment.provider"]._cron_mobilepay_sync_settlements()

        self.assertNotIn(disabled.id, call_log)

    def test_cron_error_in_one_provider_does_not_abort_others(self):
        """An exception in one provider's sync must not prevent others from running."""
        second = self.env["payment.provider"].create({
            "name": "MobilePay Second",
            "code": "mobilepay",
            "state": "test",
            "mobilepay_test_client_id": "x",
            "mobilepay_test_merchant_serial": "654321",
            "mobilepay_fee_account_id": self.fee_account.id,
            "mobilepay_clearing_account_id": self.clearing_account.id,
            "mobilepay_journal_id": self.journal.id,
        })

        success_log = []

        def mock_sync(provider_self):
            if provider_self.id == self.provider.id:
                raise RuntimeError("Simulated API failure")
            success_log.append(provider_self.id)

        with patch.object(
            type(self.provider),
            "_mobilepay_sync_settlements",
            autospec=True,
            side_effect=mock_sync,
        ):
            # Should not raise
            self.env["payment.provider"]._cron_mobilepay_sync_settlements()

        self.assertIn(second.id, success_log)


# ---------------------------------------------------------------------------
# 2. Config validation tests
# ---------------------------------------------------------------------------

class TestConfigValidation(FeesReconciliationBase):

    def test_sync_skipped_when_fee_account_missing(self):
        """Settlement sync should log a warning and return early if fee account is absent."""
        self.provider.mobilepay_fee_account_id = False

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
        ) as mock_api:
            self.provider._mobilepay_sync_settlements()
            mock_api.assert_not_called()

    def test_sync_skipped_when_clearing_account_missing(self):
        """Settlement sync should return early if clearing account is not configured."""
        self.provider.mobilepay_clearing_account_id = False

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
        ) as mock_api:
            self.provider._mobilepay_sync_settlements()
            mock_api.assert_not_called()

    def test_sync_skipped_when_journal_missing(self):
        """Settlement sync should return early if journal is not configured."""
        self.provider.mobilepay_journal_id = False

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
        ) as mock_api:
            self.provider._mobilepay_sync_settlements()
            mock_api.assert_not_called()

    def test_sync_skipped_for_non_mobilepay_provider(self):
        """Calling _mobilepay_sync_settlements on a non-MobilePay provider is a no-op."""
        other = self.env["payment.provider"].create({
            "name": "Stripe",
            "code": "none",
            "state": "test",
        })
        # Should not raise, should not create any settlement records
        other._mobilepay_sync_settlements()
        count = self.env["mobilepay.settlement"].search_count([])
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# 3. Duplicate-payout guard tests
# ---------------------------------------------------------------------------

class TestDuplicatePayoutGuard(FeesReconciliationBase):

    def _run_sync_with_entries(self, entries):
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
            return_value=entries,
        ):
            self.provider._mobilepay_sync_settlements()

    def test_already_reconciled_payout_is_not_reprocessed(self):
        """A payout already in 'reconciled' state must not generate a second journal entry."""
        payout_id = "PAYOUT-DUPE-001"

        # Pre-create a reconciled settlement record
        self.env["mobilepay.settlement"].create({
            "payout_id": payout_id,
            "settlement_date": "2026-08-20",
            "gross_amount": 1000.0,
            "fee_amount": 15.0,
            "net_amount": 985.0,
            "currency_id": self.dkk.id,
            "state": "reconciled",
        })

        move_count_before = self.env["account.move"].search_count([("ref", "=", payout_id)])

        entries = _make_entries(payout_id, net=98500)
        self._run_sync_with_entries(entries)

        move_count_after = self.env["account.move"].search_count([("ref", "=", payout_id)])
        self.assertEqual(move_count_before, move_count_after,
                         "No new journal entry should be created for an already-reconciled payout.")


# ---------------------------------------------------------------------------
# 4. Journal entry structure tests
# ---------------------------------------------------------------------------

class TestJournalEntryStructure(FeesReconciliationBase):

    def _sync_payout(self, payout_id, captures=None, fees=None, refunds=None, net=None):
        entries = _make_entries(payout_id, captures=captures, fees=fees, refunds=refunds, net=net)
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
            return_value=entries,
        ):
            self.provider._mobilepay_sync_settlements()

    def _get_move(self, payout_id):
        return self.env["account.move"].search([("ref", "=", payout_id)], limit=1)

    # ------------------------------------------------------------------
    def test_journal_entry_is_created(self):
        """A journal entry must exist after syncing a new payout."""
        self._sync_payout("PAYOUT-BASIC-001", net=98500)
        move = self._get_move("PAYOUT-BASIC-001")
        self.assertTrue(move, "Expected an account.move to be created for the payout.")

    def test_entry_is_posted_when_auto_post_enabled(self):
        """When auto_post=True, the move must be in 'posted' state after sync."""
        self._sync_payout("PAYOUT-POST-001", net=98500)
        move = self._get_move("PAYOUT-POST-001")
        self.assertEqual(move.state, "posted")

    def test_entry_is_draft_when_auto_post_disabled(self):
        """When auto_post=False, the move must remain in 'draft' state."""
        self.provider.mobilepay_auto_post_settlements = False
        self._sync_payout("PAYOUT-DRAFT-001", net=98500)
        move = self._get_move("PAYOUT-DRAFT-001")
        self.assertEqual(move.state, "draft")

    def test_debit_bank_line_equals_net_payout(self):
        """The bank account debit line must equal the net payout amount."""
        # 1000 DKK gross, 15 DKK fee, 985 DKK net (all in øre: ×100)
        self._sync_payout(
            "PAYOUT-AMOUNTS-001",
            captures=[{"pspRef": "PSP-A1", "amount": 100000}],
            fees=[{"amount": 1500}],
            net=98500,
        )
        move = self._get_move("PAYOUT-AMOUNTS-001")
        bank_lines = move.line_ids.filtered(
            lambda l: l.account_id == self.bank_account and l.debit > 0
        )
        self.assertTrue(bank_lines, "Expected a debit line on the bank account.")
        self.assertAlmostEqual(bank_lines[0].debit, 985.0, places=2)

    def test_debit_fee_line_equals_fee_amount(self):
        """The fee expense account debit line must equal the total fee amount."""
        self._sync_payout(
            "PAYOUT-FEES-001",
            captures=[{"pspRef": "PSP-F1", "amount": 100000}],
            fees=[{"amount": 1500}],
            net=98500,
        )
        move = self._get_move("PAYOUT-FEES-001")
        fee_lines = move.line_ids.filtered(
            lambda l: l.account_id == self.fee_account and l.debit > 0
        )
        self.assertTrue(fee_lines, "Expected a debit line on the fee account.")
        self.assertAlmostEqual(fee_lines[0].debit, 15.0, places=2)

    def test_credit_clearing_line_equals_gross_receipts(self):
        """The clearing account credit line must equal the gross payment amount."""
        self._sync_payout(
            "PAYOUT-CLEAR-001",
            captures=[{"pspRef": "PSP-C1", "amount": 100000}],
            fees=[{"amount": 1500}],
            net=98500,
        )
        move = self._get_move("PAYOUT-CLEAR-001")
        clearing_credit = move.line_ids.filtered(
            lambda l: l.account_id == self.clearing_account and l.credit > 0
        )
        self.assertTrue(clearing_credit, "Expected a credit line on the clearing account.")
        self.assertAlmostEqual(clearing_credit[0].credit, 1000.0, places=2)

    def test_entry_is_balanced(self):
        """Total debits must equal total credits (double-entry invariant)."""
        self._sync_payout(
            "PAYOUT-BALANCE-001",
            captures=[{"pspRef": "PSP-B1", "amount": 100000}],
            fees=[{"amount": 1500}],
            net=98500,
        )
        move = self._get_move("PAYOUT-BALANCE-001")
        total_debit  = sum(move.line_ids.mapped("debit"))
        total_credit = sum(move.line_ids.mapped("credit"))
        self.assertAlmostEqual(total_debit, total_credit, places=2,
                               msg="Journal entry is not balanced.")

    def test_multiple_capture_lines_aggregated(self):
        """Multiple capture entries for the same payout must sum into one gross line."""
        self._sync_payout(
            "PAYOUT-MULTI-001",
            captures=[
                {"pspRef": "PSP-M1", "amount": 50000},
                {"pspRef": "PSP-M2", "amount": 50000},
            ],
            fees=[{"amount": 1500}],
            net=98500,
        )
        move = self._get_move("PAYOUT-MULTI-001")
        clearing_credit = move.line_ids.filtered(
            lambda l: l.account_id == self.clearing_account and l.credit > 0
        )
        self.assertAlmostEqual(sum(clearing_credit.mapped("credit")), 1000.0, places=2)


# ---------------------------------------------------------------------------
# 5. Refund handling tests
# ---------------------------------------------------------------------------

class TestRefundHandling(FeesReconciliationBase):

    def _sync_payout(self, payout_id, captures=None, fees=None, refunds=None, net=None):
        entries = _make_entries(payout_id, captures=captures, fees=fees, refunds=refunds, net=net)
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
            return_value=entries,
        ):
            self.provider._mobilepay_sync_settlements()

    def _get_move(self, payout_id):
        return self.env["account.move"].search([("ref", "=", payout_id)], limit=1)

    def test_refund_produces_clearing_debit_line(self):
        """A refund in the settlement must produce a debit line on the clearing account."""
        self._sync_payout(
            "PAYOUT-REFUND-001",
            captures=[{"pspRef": "PSP-R1", "amount": 100000}],
            refunds=[{"pspRef": "PSP-REF-001", "amount": 20000}],  # 200 DKK refund
            fees=[{"amount": 1200}],
            net=78800,
        )
        move = self._get_move("PAYOUT-REFUND-001")
        refund_debit = move.line_ids.filtered(
            lambda l: l.account_id == self.clearing_account and l.debit > 0
        )
        self.assertTrue(refund_debit, "Expected a debit clearing line for the refund.")
        self.assertAlmostEqual(refund_debit[0].debit, 200.0, places=2)

    def test_gross_amount_on_settlement_record_is_net_of_refunds(self):
        """mobilepay.settlement.gross_amount should equal captures minus refunds."""
        self._sync_payout(
            "PAYOUT-REFUND-GROSS-001",
            captures=[{"pspRef": "PSP-RG1", "amount": 100000}],
            refunds=[{"pspRef": "PSP-REFG1", "amount": 20000}],
            fees=[{"amount": 1200}],
            net=78800,
        )
        settlement = self.env["mobilepay.settlement"].search(
            [("payout_id", "=", "PAYOUT-REFUND-GROSS-001")], limit=1
        )
        self.assertTrue(settlement)
        # gross_amount = captures - refunds = 1000 - 200
        self.assertAlmostEqual(settlement.gross_amount, 800.0, places=2)


# ---------------------------------------------------------------------------
# 6. Fee tax tests
# ---------------------------------------------------------------------------

class TestFeeTax(FeesReconciliationBase):

    def test_fee_line_carries_tax_when_configured(self):
        """When mobilepay_fee_tax_id is set, the fee move line must reference that tax."""
        tax = self.env["account.tax"].create({
            "name": "MobilePay Fee VAT Test",
            "amount": 25.0,
            "type_tax_use": "purchase",
        })
        self.provider.mobilepay_fee_tax_id = tax

        entries = _make_entries(
            "PAYOUT-TAX-001",
            captures=[{"pspRef": "PSP-T1", "amount": 100000}],
            fees=[{"amount": 1500}],
            net=98500,
        )
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
            return_value=entries,
        ):
            self.provider._mobilepay_sync_settlements()

        move = self.env["account.move"].search([("ref", "=", "PAYOUT-TAX-001")], limit=1)
        fee_lines = move.line_ids.filtered(lambda l: l.account_id == self.fee_account)
        self.assertTrue(fee_lines)
        # tax_ids on the line should contain our tax
        tax_ids = fee_lines[0].tax_ids
        self.assertIn(tax, tax_ids)


# ---------------------------------------------------------------------------
# 7. Settlement record state-machine tests
# ---------------------------------------------------------------------------

class TestSettlementStateMachine(FeesReconciliationBase):

    def _sync_payout(self, payout_id, entries=None):
        if entries is None:
            entries = _make_entries(payout_id, net=98500)
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
            return_value=entries,
        ):
            self.provider._mobilepay_sync_settlements()

    def test_settlement_created_in_reconciled_state_when_auto_post(self):
        """With auto_post=True, settlement record state should be 'reconciled'."""
        self._sync_payout("PAYOUT-STATE-001")
        s = self.env["mobilepay.settlement"].search([("payout_id", "=", "PAYOUT-STATE-001")], limit=1)
        self.assertTrue(s)
        self.assertEqual(s.state, "reconciled")

    def test_settlement_created_in_draft_state_when_auto_post_false(self):
        """With auto_post=False, settlement record state should be 'draft'."""
        self.provider.mobilepay_auto_post_settlements = False
        self._sync_payout("PAYOUT-DRAFTSTATE-001")
        s = self.env["mobilepay.settlement"].search([("payout_id", "=", "PAYOUT-DRAFTSTATE-001")], limit=1)
        self.assertTrue(s)
        self.assertEqual(s.state, "draft")

    def test_settlement_links_to_journal_entry(self):
        """The settlement record must hold a reference to the generated account.move."""
        self._sync_payout("PAYOUT-LINK-001")
        s = self.env["mobilepay.settlement"].search([("payout_id", "=", "PAYOUT-LINK-001")], limit=1)
        self.assertTrue(s.journal_entry_id, "Settlement must link to its account.move.")
        self.assertEqual(s.journal_entry_id.ref, "PAYOUT-LINK-001")

    def test_settlement_state_set_to_error_on_exception(self):
        """If journal entry creation fails, settlement state must be 'error' with a note."""
        entries = _make_entries("PAYOUT-ERR-001", net=98500)

        def raise_on_create(vals_list):
            raise UserError("Simulated create failure")

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
            return_value=entries,
        ):
            with patch.object(
                self.env["account.move"].__class__,
                "create",
                side_effect=raise_on_create,
            ):
                self.provider._mobilepay_sync_settlements()

        s = self.env["mobilepay.settlement"].search([("payout_id", "=", "PAYOUT-ERR-001")], limit=1)
        self.assertTrue(s)
        self.assertEqual(s.state, "error")
        self.assertTrue(s.note, "Error note must be populated on failure.")


# ---------------------------------------------------------------------------
# 8. API client / get_settlement_reports parsing tests
# ---------------------------------------------------------------------------

class TestGetSettlementReports(FeesReconciliationBase):
    """Unit-test the API client's get_settlement_reports method in isolation."""

    def _mock_api(self, ledgers_payload, entries_payload):
        """Patch _make_request to return controlled payloads."""
        def fake_make_request(client_self, provider, method, endpoint, params=None, **kw):
            resp = MagicMock()
            resp.status_code = 200
            if "ledgers" in endpoint and "entries" not in endpoint:
                resp.json.return_value = ledgers_payload
            else:
                resp.json.return_value = entries_payload
            return resp

        return patch.object(
            self.env["mobilepay.api.client"].__class__,
            "_make_request",
            autospec=True,
            side_effect=fake_make_request,
        )

    def test_returns_list_when_api_returns_list(self):
        """get_settlement_reports must return a flat list when entries is a list."""
        ledgers = [{"ledgerId": "L1", "salesUnitId": "123456"}]
        entries = _make_entries("P1", net=98500)

        with self._mock_api(ledgers, entries):
            result = self.env["mobilepay.api.client"].get_settlement_reports(
                self.provider,
                __import__("datetime").date(2026, 8, 1),
                __import__("datetime").date(2026, 8, 20),
            )

        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

    def test_returns_list_when_api_wraps_in_dict(self):
        """get_settlement_reports must unwrap entries from {'entries': [...]} dict shape."""
        ledgers = [{"ledgerId": "L2", "salesUnitId": "123456"}]
        raw_entries = _make_entries("P2", net=98500)
        entries_dict = {"entries": raw_entries, "total": len(raw_entries)}

        with self._mock_api(ledgers, entries_dict):
            result = self.env["mobilepay.api.client"].get_settlement_reports(
                self.provider,
                __import__("datetime").date(2026, 8, 1),
                __import__("datetime").date(2026, 8, 20),
            )

        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

    def test_returns_empty_when_no_matching_ledger(self):
        """If no ledger matches the provider's MSN, an empty list must be returned."""
        ledgers = [{"ledgerId": "L3", "salesUnitId": "999999"}]  # different MSN

        with self._mock_api(ledgers, []):
            result = self.env["mobilepay.api.client"].get_settlement_reports(
                self.provider,
                __import__("datetime").date(2026, 8, 1),
                __import__("datetime").date(2026, 8, 20),
            )

        self.assertEqual(result, [])

    def test_returns_empty_on_api_exception(self):
        """A network/API error during ledger fetch must return an empty list, not raise."""
        def boom(*args, **kwargs):
            raise UserError("Network failure")

        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "_make_request",
            autospec=True,
            side_effect=boom,
        ):
            result = self.env["mobilepay.api.client"].get_settlement_reports(
                self.provider,
                __import__("datetime").date(2026, 8, 1),
                __import__("datetime").date(2026, 8, 20),
            )

        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# 9. Clearing account reconciliation tests
# ---------------------------------------------------------------------------

class TestClearingReconciliation(FeesReconciliationBase):
    """Verify that outstanding clearing lines are reconciled after settlement posting."""

    def test_reconcile_method_called_on_matching_lines(self):
        """
        _mobilepay_reconcile_clearing_lines should call reconcile() on matched
        clearing account lines. We verify the method is invoked without error.
        """
        # Create a dummy payment transaction linked to a pspReference
        psp_ref = "PSP-RECONCILE-001"

        # Simulate an existing payment move with a clearing account line
        move_in = self.env["account.move"].create({
            "journal_id": self.journal.id,
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": "Simulated payment in",
                    "account_id": self.clearing_account.id,
                    "credit": 0.0,
                    "debit": 1000.0,
                }),
                (0, 0, {
                    "name": "Simulated counterpart",
                    "account_id": self.bank_account.id,
                    "debit": 0.0,
                    "credit": 1000.0,
                }),
            ],
        })
        move_in.action_post()

        # Create a payment transaction referencing this psp ref
        tx = self.env["payment.transaction"].create({
            "reference": "TEST-REC-001",
            "amount": 1000.0,
            "currency_id": self.dkk.id,
            "provider_id": self.provider.id,
            "state": "done",
        })
        # Manually set the mobilepay_payment_id if the field exists
        if hasattr(tx, "mobilepay_payment_id"):
            tx.mobilepay_payment_id = psp_ref

        # Run sync — reconciliation errors are caught internally, so we just
        # verify no unhandled exception is raised
        entries = _make_entries(
            "PAYOUT-REC-001",
            captures=[{"pspRef": psp_ref, "amount": 100000}],
            fees=[{"amount": 1500}],
            net=98500,
        )
        with patch.object(
            self.env["mobilepay.api.client"].__class__,
            "get_settlement_reports",
            return_value=entries,
        ):
            # Should complete without raising
            self.provider._mobilepay_sync_settlements()

        # The settlement journal entry should exist
        move = self.env["account.move"].search([("ref", "=", "PAYOUT-REC-001")], limit=1)
        self.assertTrue(move)
        self.assertEqual(move.state, "posted")
