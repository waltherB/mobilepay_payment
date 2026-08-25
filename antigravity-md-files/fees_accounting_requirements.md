# MobilePay Automated Fees Accounting Requirements (Hybrid Flow)

This document outlines the technical requirements, architecture, and Odoo 17 development patterns needed to extend the `mobilepay_payment` module to support automated transaction fee accounting compatible with Odoo Community Edition (CE) using a **Hybrid Flow**.

---

## 1. Accounting Architecture (Hybrid Flow)

The Hybrid Flow combines real-time gross sales tracking with batch settlement reconciliation to ensure easy bank statement matching and exact fee accuracy.

```
 [ Customer Purchase ]
         │ (Real-time)
         ▼
 [ Capture Full Gross Amount ] ➔ Debits: MobilePay Clearing Account ($1000)
                                 Credits: Sales Income Account ($1000)
 
 [ Daily/Weekly Bank Settlement ]
         │ (Report API Cron)
         ▼
 [ Generate Payout Entry ] (account.move)
         ├── Debit: Bank Account                    ($985 - Net Payout)
         ├── Debit: MobilePay Fee Expense Account   ($15  - Exact Fees)
         └── Credit: MobilePay Clearing Account     ($1000 - Gross Payout)
                     │
         [ Reconcile Credit Line ] (account.move.line)
                     ▼
      [ Matches & Reconciles Outstanding ]
      [ Customer Payment Clearing Lines  ] (from original POS/Sales transactions)
```

### A. Configuration Models (`payment.provider`)
Extend `payment.provider` with settings to handle CE accounting entries:
- `mobilepay_fee_account_id` (`many2one` -> `account.account`): The expense account used to record transaction fees (e.g., "Bank and Merchant Fees").
- `mobilepay_clearing_account_id` (`many2one` -> `account.account`): Transit/Clearing asset account where gross customer payments are temporarily collected.
- `mobilepay_journal_id` (`many2one` -> `account.journal`): The Misc/Bank journal where settlement entries are posted.

### B. Report API Integration Client
Extend [`mobilepay_api_client.py`](file:///Users/waba/github/mobilepay_payment/models/mobilepay_api_client.py) to fetch reports:
- Fetch daily or weekly settlement reports using the `GET /settlements/v1` endpoint.
- Parse reports to retrieve:
  - **Gross Amount** (sum of payments processed).
  - **Fee Amount** (total commissions/fees charged by MobilePay).
  - **Net Amount** (the cash actually transferred to the merchant's bank).

### C. Settlement Post & Reconciliation Logic (Cron Job)
1. **Create Cron Job**:
   - Add a scheduled action in [ir_cron_data.xml](file:///Users/waba/github/mobilepay_payment/data/ir_cron_data.xml) that executes daily:
     ```xml
     <record id="ir_cron_mobilepay_reconcile_reports" model="ir.cron">
         <field name="name">MobilePay: Fetch Settlements and Reconcile Fees (CE)</field>
         <field name="model_id" ref="model_payment_provider"/>
         <field name="state">code</field>
         <field name="code">model._mobilepay_sync_settlements()</field>
         <field name="interval_number">1</field>
         <field name="interval_type">days</field>
     </record>
     ```
2. **Python Entry Creation & Matching**:
   - For each new settlement report downloaded:
     - Check if a journal entry (`account.move`) has already been generated for the settlement reference. If not:
     - Generate a new `account.move` with the following lines:
       - **Debit**: Bank Account (representing the incoming Net Payout)
       - **Debit**: Fee Expense Account (representing the Fee Amount)
       - **Credit**: MobilePay Clearing Account (representing the Gross Amount)
     - Post the journal entry.
     - Automatically find the outstanding payment lines matching the gross transaction references in the `mobilepay_clearing_account_id` and reconcile them with the Credit line to mark the sales invoices/POS orders as fully settled.

---

## 2. Recommended Flow Improvements (Accounting & Reconciliation)

To ensure the accounting reconciliation is production-ready and error-tolerant, the following flows should be implemented:

1. **Refund Deductions Handling**:
   - The Report API parser must identify refund transaction lines in the settlement report. Instead of just creating a credit line for the gross payment, Odoo should create a debit line to the *MobilePay Clearing Account* (or refund transit account) to offset and reconcile corresponding customer refund transactions.
2. **"Draft" vs. "Auto-Post" Safety Switch**:
   - Add a configuration field `mobilepay_auto_post_settlements` (`boolean`) to the provider settings.
   - If enabled, the cron posts and reconciles the entries automatically.
   - If disabled, the `account.move` is created in `draft` status, allowing the accountant to verify the amounts, post it manually, and run Odoo's native reconciliation action.
3. **Rounding Discrepancy Tolerance**:
   - Implement a tiny rounding difference write-off logic (e.g. < 0.05 DKK/EUR). If minor rounding differences exist between the Odoo transaction amounts and the API settlement report totals, write them off to a rounding account to prevent reconciliation blockages.
4. **Exchange Difference Processing**:
   - If the payout bank account currency differs from the transaction currency, ensure any exchange rate discrepancy (FX markup) is automatically booked to a Foreign Exchange Loss/Gain account.
