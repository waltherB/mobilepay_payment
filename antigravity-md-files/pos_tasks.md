# POS Integration — Task Checklist

---

## Phase 1 — Backend

- [ ] **1.1** Create `models/pos_payment_method.py`: extend `pos.payment.method` with `mobilepay_pos_default_mode`, `mobilepay_pos_provider_id`, `mobilepay_pos_timeout`, and add `mobilepay` to `use_payment_terminal` selection.
- [ ] **1.2** Register `pos_payment_method` in `models/__init__.py`.
- [ ] **1.3** Create `controllers/pos_controller.py` with three JSON-RPC routes:
  - `POST /mobilepay/pos/initiate_payment`
  - `POST /mobilepay/pos/check_status`
  - `POST /mobilepay/pos/cancel_payment`
- [ ] **1.4** Register `pos_controller` in `controllers/__init__.py`.
- [ ] **1.5** Create `views/pos_payment_method_views.xml`: extend `pos.payment.method` form with MobilePay settings group.
- [ ] **1.6** Update `__manifest__.py`:
  - Add `"point_of_sale"` to `depends`.
  - Add `"views/pos_payment_method_views.xml"` to `data`.
  - Add `point_of_sale._assets_pos` bundle with JS and XML assets.

---

## Phase 2 — JavaScript / POS Frontend

- [ ] **2.1** Create `static/src/js/payment_mobilepay.js`:
  - `PaymentMobilePay` class extending `PaymentInterface`.
  - `sendPaymentRequest`, `sendPaymentCancel` overrides.
  - `_initiatePhonePush`, `_initiateQr` helpers.
  - `_startPolling` with 3-second interval and `mobilepay_pos_timeout` ceiling.
  - `_resolvePayment` and `_handleFailure` state handlers.
  - `_switchToQr` mid-flight mode switch.
- [ ] **2.2** Create `static/src/xml/MobilePayPaymentScreen.xml` with OWL templates:
  - `MobilePayModeDialog` — choose phone push or QR.
  - `MobilePayPhoneDialog` — phone input with pre-fill from POS partner.
  - `MobilePayQrDisplay` — QR image, countdown, status text, fallback + cancel buttons.

---

## Phase 3 — Tests

- [ ] **3.1** Create `tests/test_pos_payment.py` with automated tests:
  - `test_pos_payment_method_fields`
  - `test_pos_controller_initiate_phone_push`
  - `test_pos_controller_initiate_qr`
  - `test_pos_controller_check_status_authorized`
  - `test_pos_controller_cancel`
  - `test_pos_controller_missing_provider`
- [ ] **3.2** Register `test_pos_payment` in `tests/__init__.py`.

---

## Phase 4 — Manual Verification

- [ ] **4.1** Install on test DB; verify no import or manifest errors.
- [ ] **4.2** Configure a POS payment method with MobilePay terminal (backend UI).
- [ ] **4.3** Open POS session, test Phone Push flow end-to-end (Vipps test environment).
- [ ] **4.4** Open POS session, test QR Code flow end-to-end.
- [ ] **4.5** Test operator cancel mid-flow.
- [ ] **4.6** Test timeout expiry (set `mobilepay_pos_timeout = 10` temporarily).
- [ ] **4.7** Test `_switchToQr` fallback (initiate phone push, hit "Generate QR Code").
- [ ] **4.8** (Optional) Test Customer Facing Display QR passthrough with IoT Box.
