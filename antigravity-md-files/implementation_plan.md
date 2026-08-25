# Implementation Plan - Automated Fees Accounting (Hybrid Flow)

Implement automated transaction fees accounting and payout reconciliation using the **Hybrid Flow** (real-time gross payment capture + batch settlement fee reconciliation) for the MobilePay integration, compatible with Odoo 17 Community Edition (CE).

---

## Proposed Changes

We will group the changes into clean components: models, API client, cron task, database tracking, and UI configuration.

### 1. Database Tracking & Configuration

#### [NEW] [mobilepay_settlement.py](file:///Users/waba/github/mobilepay_payment/models/mobilepay_settlement.py)
Create a tracking model `mobilepay.settlement` to prevent duplicate payout entries and provide auditable records of settlement reconciliations.
- Fields:
  - `payout_id` (Char, unique index): The unique payout/settlement transfer reference from MobilePay.
  - `settlement_date` (Date): The date the settlement was paid.
  - `gross_amount` (Monetary): The total customer payments processed in this batch.
  - `fee_amount` (Monetary): The total commissions deducted.
  - `net_amount` (Monetary): The net bank transfer amount.
  - `currency_id` (Many2one -> `res.currency`): Currency of the settlement.
  - `journal_entry_id` (Many2one -> `account.move`): The generated Odoo Journal Entry.
  - `state` (Selection): `'draft'`, `'reconciled'`, or `'error'`.

#### [MODIFY] [payment_provider.py](file:///Users/waba/github/mobilepay_payment/models/payment_provider.py)
Extend `payment.provider` to include accounting configuration fields:
- `mobilepay_fee_account_id` (Many2one -> `account.account`): Expense account for transaction fees.
- `mobilepay_clearing_account_id` (Many2one -> `account.account`): Asset account where gross customer payments are cleared in real-time.
- `mobilepay_journal_id` (Many2one -> `account.journal`): Bank/Misc journal to post payout entries.
- `mobilepay_auto_post_settlements` (Boolean, default `True`): Toggles whether entries post immediately or save as draft.
- `mobilepay_fee_tax_id` (Many2one -> `account.tax`): Optional tax/VAT code to apply to transaction fees.

---

### 2. API Client Integration

#### [MODIFY] [mobilepay_api_client.py](file:///Users/waba/github/mobilepay_payment/models/mobilepay_api_client.py)
Add support for the Vipps MobilePay Report API (Settlements v1/v2):
- Implement `get_settlement_reports(self, provider, start_date, end_date)`:
  - Fetches payout ledger summaries from the `/settlement` endpoints.
  - Parses individual payout structures including gross receipts, refund deductions, and fee breakdowns.

---

### 3. Cron Task & Reconciliation Logic

#### [MODIFY] [ir_cron_data.xml](file:///Users/waba/github/mobilepay_payment/data/ir_cron_data.xml)
[NEW] Add a cron task to run daily:
- Name: "MobilePay: Fetch Settlements and Reconcile Fees (CE)"
- Method: `model.env['payment.provider']._cron_mobilepay_sync_settlements()`

#### [MODIFY] [payment_provider.py](file:///Users/waba/github/mobilepay_payment/models/payment_provider.py)
Implement `_cron_mobilepay_sync_settlements(self)` and reconciliation helper methods for the Hybrid Flow:
1. **Real-time baseline**: Confirm Odoo's standard payment flow captures the full gross payment (e.g., `$1000`) and posts it directly to `mobilepay_clearing_account_id` upon transaction completion (`done`).
2. **Settlement Sync**: Periodically query the Report API for the last `X` days of payouts.
3. For each unseen `payout_id`:
   - Create a draft `account.move` with the following structure:
     - **Debit**: Bank Account (Net Amount, matching the bank statement)
     - **Debit**: Fee Expense Account (Fee Amount, matching MobilePay invoice)
     - **Credit**: MobilePay Clearing Account (Gross Amount)
     *If refunds are present in the settlement report:*
     - **Debit**: MobilePay Clearing Account (Gross Refund Amount)
     *If tax/VAT is mapped on fees:*
     - Apply tax lines to the fee line using standard `account.move.line` tax helpers.
   - If `mobilepay_auto_post_settlements` is True, post the journal entry.
   - Query outstanding `account.move.line` entries on `mobilepay_clearing_account_id` that match the `pspReference` (`mobilepay_payment_id`) of the settled transactions.
   - Call Odoo's native `reconcile()` method on matched lines to close out the clearing account balance.
   - Register the `mobilepay.settlement` record linking to the posted move.

---

### 4. UI Configurations

#### [MODIFY] [payment_provider_views.xml](file:///Users/waba/github/mobilepay_payment/views/payment_provider_views.xml)
Expose the configuration fields in the payment provider settings form:
- Place under a new group/page: "MobilePay Settlement & Fees".
- Render the `mobilepay_fee_account_id`, `mobilepay_clearing_account_id`, `mobilepay_journal_id`, `mobilepay_auto_post_settlements`, and `mobilepay_fee_tax_id` when `code == 'mobilepay'`.

---

## Verification Plan

### Automated Tests
- Build a Python test in `tests/test_fees_reconciliation.py`:
  - Create a transaction in `done` state, posting `$1000` to the clearing account.
  - Mock the Report API response to return a payout containing this transaction's `pspReference` with a `$10` fee.
  - Execute `_cron_mobilepay_sync_settlements()`.
  - Assert that Odoo creates the `account.move` with correct debit/credit sums.
  - Verify that the matching transaction lines in the clearing account are successfully reconciled (`reconciled = True`).

### Manual Verification
- Deploy to test database, set up fake accounting journals/accounts.
- Use mock data to run the Sync cron job.
- Open the generated Journal Entry in Odoo accounting module, inspect ledger postings, tax distributions, and matching state.
