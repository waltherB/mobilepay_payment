# Implementation Plan — MobilePay POS Terminal Integration

Integrate MobilePay/Vipps ePayment into the Odoo 17 Point of Sale (POS) terminal as a custom payment interface, supporting both **Phone Number Push** and **QR Code** payment modes. The implementation follows Odoo 17's decoupled JS/Python POS architecture and reuses the existing API client, auth service, and encryption infrastructure already present in this module.

---

## Guiding Principles

- **Reuse first**: the `mobilepay.api.client`, `mobilepay.auth.service`, and credential encryption on `payment.provider` are not touched. The POS integration calls the same ePayment API endpoints already used by the e-commerce flow.
- **Single module**: everything lives inside `mobilepay_payment`; no new module or sub-module.
- **CE-compatible**: no dependency on Odoo Enterprise POS features (IoT Box is optional).
- **Non-breaking**: all changes are additive. Existing e-commerce, webhook, and settlement flows are unaffected.

---

## Component Overview

```
[ POS Operator Screen ]
        │
        ▼
[ PaymentMobilePay (JS) ]     ← extends PaymentInterface
        │  JSON-RPC
        ▼
[ MobilePayPosController ]    ← new: /mobilepay/pos/* routes
        │
        ▼
[ mobilepay.api.client ]      ← existing: create_payment, get_payment_status
        │
        ▼
[ Vipps/MobilePay ePayment API ]
```

---

## 1. Python / Backend

### 1.1 `pos.payment.method` — extend with POS-specific config

**File**: `models/pos_payment_method.py` *(new)*

Add to the `pos.payment.method` model:

| Field | Type | Description |
|---|---|---|
| `mobilepay_pos_default_mode` | Selection(`'prompt'`, `'phone_push'`, `'qr_code'`) | Default payment initiation mode; `'prompt'` shows the operator dialog |
| `mobilepay_pos_provider_id` | Many2one → `payment.provider` | The MobilePay provider to use for this payment method |
| `mobilepay_pos_timeout` | Integer (default 60) | Seconds to wait before auto-cancelling a pending payment |

Add `mobilepay` to the `use_payment_terminal` selection extension.

**File**: `views/pos_payment_method_views.xml` *(new)*

Expose the three fields under a `"MobilePay Terminal"` group, visible only when `use_payment_terminal == 'mobilepay'`.

**File**: `security/ir.model.access.csv` *(modify)*

`pos.payment.method` is a core POS model — no new access rules needed. Only ensure the new fields are added via `_inherit`.

---

### 1.2 JSON-RPC POS Controller

**File**: `controllers/pos_controller.py` *(new)*

Two endpoints consumed by the JS interface via `useService('orm')` / `fetch`:

#### `POST /mobilepay/pos/initiate_payment`

```
Input:
  pos_session_id  int        Active POS session ID (for provider lookup)
  amount          int        Amount in minor units (øre / cents)
  currency        str        ISO currency code (e.g. "DKK")
  pos_reference   str        Unique POS order reference
  payment_mode    str        "phone_push" | "qr_code"
  phone_number    str|null   E.164 phone number (phone_push only)
  
Output (success):
  payment_id      str        MobilePay payment ID
  qr_payload      str|null   Base64 PNG or SVG string (qr_code mode)
  status          str        "CREATED"

Output (error):
  error           str        Human-readable message
```

Logic:
1. Resolve the `payment.provider` via `pos.payment.method.mobilepay_pos_provider_id` (or fall back to first active MobilePay provider for the session's company).
2. Build the ePayment `create_payment` payload:
   - `userFlow`: `"PUSH_MESSAGE"` for phone push; `"QR"` for QR code.
   - `phoneNumber`: included only when `payment_mode == "phone_push"`.
   - `reference`: `pos_reference` (max 50 chars, alphanum + hyphen).
3. Call `mobilepay.api.client.create_payment(provider, payload)`.
4. For QR mode, call the QR endpoint (`/epayment/v1/payments/{id}/qr`) and return the image.
5. Return `payment_id` and optional `qr_payload`.

#### `POST /mobilepay/pos/check_status`

```
Input:
  payment_id      str        MobilePay payment ID from initiate_payment
  pos_session_id  int

Output:
  status          str        "CREATED" | "AUTHORIZED" | "CAPTURED" | "CANCELLED" | "EXPIRED"
  amount          int|null   Confirmed amount in minor units
```

Logic:
1. Call `mobilepay.api.client.get_payment_status(provider, payment_id)`.
2. Map the API state to the simplified status enum the JS layer understands.

#### `POST /mobilepay/pos/cancel_payment`

```
Input:
  payment_id      str
  pos_session_id  int

Output:
  success         bool
```

Logic: call `mobilepay.api.client.cancel_payment(provider, payment_id)`.

All three routes:
- `type="json"`, `auth="user"`, `csrf=False`
- Wrapped in `try/except`; errors return `{"error": "..."}` with HTTP 200 (standard Odoo JSON-RPC error convention).

---

### 1.3 `__manifest__.py` — add POS dependency and assets

- Add `"point_of_sale"` to `depends`.
- Add new asset bundle entries:
  ```python
  "point_of_sale._assets_pos": [
      "mobilepay_payment/static/src/js/payment_mobilepay.js",
      "mobilepay_payment/static/src/xml/MobilePayPaymentScreen.xml",
  ],
  ```
- Add new data files:
  ```python
  "views/pos_payment_method_views.xml",
  ```

---

## 2. JavaScript / POS Frontend

### 2.1 `PaymentMobilePay` — main payment interface

**File**: `static/src/js/payment_mobilepay.js`

Extends `PaymentInterface` from `@point_of_sale/app/payment/payment_interface`.

#### Key Methods

| Method | Responsibility |
|---|---|
| `sendPaymentRequest(cid)` | Entry point; reads `default_mode`, branches to `_initiatePhonePush` or `_initiateQr`, or shows mode dialog |
| `sendPaymentCancel(order, cid)` | Cancels via `/mobilepay/pos/cancel_payment`, resets UI state |
| `_initiatePhonePush(line, phone)` | Calls initiate endpoint with `phone_push` mode, starts polling |
| `_initiateQr(line)` | Calls initiate endpoint with `qr_code` mode, renders QR in popup, starts polling |
| `_startPolling(paymentId, line)` | `setInterval`-based poller (every 3 s); handles `AUTHORIZED`/`CAPTURED` → `_resolvePayment`, `CANCELLED`/`EXPIRED` → `_handleFailure` |
| `_resolvePayment(line)` | Sets line approved, calls `this.pos.showScreen("ReceiptScreen")` path |
| `_handleFailure(line, reason)` | Resets line state, shows error banner, re-enables payment method selection |
| `_switchToQr(paymentId, line)` | Mid-flight mode switch: calls QR endpoint for existing `paymentId`, shows QR popup |

#### State tracked per payment line
```js
{
  paymentId: null,       // MobilePay payment ID
  pollingTimer: null,    // setInterval handle
  elapsed: 0,           // seconds since initiation
  mode: "prompt",       // current active mode
}
```

#### Operator dialog flow (mode = "prompt")
Open `MobilePayModeDialog`; on selection:
- **Phone Number Push** → open `MobilePayPhoneDialog` (numeric keypad, pre-fills from `this.pos.get_order().get_partner()?.phone`) → `_initiatePhonePush`
- **QR Code** → `_initiateQr` immediately

---

### 2.2 OWL Components

**File**: `static/src/xml/MobilePayPaymentScreen.xml`

Three OWL templates:

#### `MobilePayModeDialog`
- Modal with two large buttons: "Send Push to Phone" and "Show QR Code".
- Cancel button.

#### `MobilePayPhoneDialog`
- Phone number input (pre-filled if partner has phone).
- Numeric keypad.
- "Send" / "Cancel" buttons.

#### `MobilePayQrDisplay`
- Full-screen overlay showing:
  - The QR image (`<img>` from base64 payload).
  - Countdown timer (`{timeout - elapsed}s remaining`).
  - Status line: *"Waiting for customer to scan..."*
  - `"Switch to Phone Push"` fallback button (inverts the flow).
  - "Cancel Payment" button.

---

## 3. Customer Facing Display (optional, phase 2)

When an IoT Box / CFS is configured on the POS session, `_initiateQr` should additionally:
1. Push the QR image payload to the CFS via `pos.customerFacingDisplayService.sendMessage({ type: "mobilepay_qr", payload: qrBase64 })`.
2. A CFS template `MobilePayQrCustomerScreen.xml` renders the QR full-screen.

This is decoupled from phase 1 — the QR always renders on the operator screen regardless.

---

## 4. File Map

| File | Status | Description |
|---|---|---|
| `models/pos_payment_method.py` | **NEW** | Extends `pos.payment.method` with 3 fields |
| `models/__init__.py` | **MODIFY** | Import `pos_payment_method` |
| `controllers/pos_controller.py` | **NEW** | 3 JSON-RPC POS endpoints |
| `controllers/__init__.py` | **MODIFY** | Import `pos_controller` |
| `views/pos_payment_method_views.xml` | **NEW** | Backend form extension for MobilePay fields |
| `static/src/js/payment_mobilepay.js` | **NEW** | `PaymentMobilePay` JS interface |
| `static/src/xml/MobilePayPaymentScreen.xml` | **NEW** | OWL templates for dialogs and QR display |
| `__manifest__.py` | **MODIFY** | Add dependency, assets, data file |

---

## 5. Verification Plan

### Manual

1. Install module on a test DB with `point_of_sale` installed.
2. Open **Point of Sale → Configuration → Payment Methods**, create a method with terminal = MobilePay, set provider, default mode = `'prompt'`.
3. Open a POS session, add a product, proceed to payment, select MobilePay.
4. Verify mode dialog appears (if `prompt`) or initiates directly.
5. **Phone push**: enter a real test-env phone, verify API push is sent (check Vipps test app or logs), confirm polling resolves.
6. **QR code**: verify QR renders, scan with MobilePay test app, confirm payment resolves.
7. **Cancel**: cancel mid-flow, verify POS returns to payment selection.
8. **Timeout**: let timer expire (set to 10 s in test), verify failure handling and re-enablement.

### Automated Tests

**File**: `tests/test_pos_payment.py`

| Test | What it covers |
|---|---|
| `test_pos_controller_initiate_phone_push` | Mocks `create_payment`, verifies response shape and `userFlow == "PUSH_MESSAGE"` |
| `test_pos_controller_initiate_qr` | Mocks `create_payment` + QR endpoint, verifies `qr_payload` returned |
| `test_pos_controller_check_status_authorized` | Mocks `get_payment_status` returning AUTHORIZED |
| `test_pos_controller_cancel` | Mocks `cancel_payment`, verifies `{"success": True}` |
| `test_pos_controller_missing_provider` | No provider configured → returns `{"error": "..."}`, no exception |
| `test_pos_payment_method_fields` | Model-level: fields exist, `use_payment_terminal` includes `mobilepay` |
