# Automated Fees Accounting Checklist

- [ ] Create `mobilepay.settlement` model in `models/mobilepay_settlement.py` and register it in `models/__init__.py`.
- [ ] Extend `payment.provider` in `models/payment_provider.py` with configuration fields.
- [ ] Implement `get_settlement_reports` in `models/mobilepay_api_client.py`.
- [ ] Add cron scheduled action in `data/ir_cron_data.xml`.
- [ ] Write settlement sync and reconciliation python logic in `models/payment_provider.py`.
- [ ] Expose configuration fields in `views/payment_provider_views.xml` and define views/menus for `mobilepay.settlement`.
- [ ] Write automated tests in `tests/test_fees_reconciliation.py`.
- [ ] Run verification tests and record a walkthrough.
