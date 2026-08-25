# MobilePay POS Payment Terminal Integration Requirements

This document outlines the technical requirements, architecture, and Odoo 17 development patterns needed to extend the `mobilepay_payment` module to support Point of Sale (POS) Payment Terminal Integration.

---

## 1. Architecture Overview

Odoo 17 POS uses a decoupled, event-driven JavaScript architecture. Custom payment terminals are integrated via a JS interface subclassing `PaymentInterface` in combination with backend models mapping to `pos.payment.method`.

### A. Manifest & Metadata Configuration
- **Dependency**: Add `point_of_sale` to the `"depends"` list in [__manifest__.py](file:///Users/waba/github/mobilepay_payment/__manifest__.py).
- **Assets Registration**: Register a new JavaScript asset bundle under `web.assets_backend` or `point_of_sale.assets` in [__manifest__.py](file:///Users/waba/github/mobilepay_payment/__manifest__.py):
  ```python
  "assets": {
      "point_of_sale._assets_pos": [
          "mobilepay_payment/static/src/js/payment_mobilepay.js",
          "mobilepay_payment/static/src/xml/payment_mobilepay.xml",
      ],
  }
  ```

### B. Python / Backend Models
1. **Payment Method (`pos.payment.method`)**:
   - Extend the model to add `mobilepay` as a selection in `use_payment_terminal`.
   - Add configurations for the POS-specific terminal, such as default Merchant Serial Number (MSN) or provider references if distinct from e-commerce providers.
2. **POS Session / Order Controllers**:
   - Define a JSON-RPC endpoint (`/mobilepay/pos/initiate_payment`) to:
     - Generate a new payment request using the MobilePay/Vipps ePayment API or the Vipps Mobile QR API.
     - Accept parameters: `amount`, `payment_mode` (either `'phone_push'` or `'qr_code'`), `phone_number` (if `'phone_push'`), and `pos_reference`.
     - Return the payment session details, including the `qr_code_url` or raw QR graphics.
   - Define status check endpoint (`/mobilepay/pos/check_status`) to poll payment status (`RESERVED` / `CAPTURED`).

### C. JS / POS Frontend Interface
Implement `@mobilepay_payment/js/payment_mobilepay` extending `PaymentInterface` from `@point_of_sale/app/payment/payment_interface`:

1. **Operator Choice Dialog**:
   - When the operator selects MobilePay as the payment method, show a popup dialog:
     - **Button A**: Phone Number Push (prompts for the customer's phone number).
     - **Button B**: QR Code (generates a QR code immediately).
2. **Execution Flow**:
   - If **Phone Number Push** is chosen, capture the phone number, invoke the API push endpoint, and display a loader/spinner while polling.
   - If **QR Code** is chosen:
     - Call the backend to generate the QR payload.
     - Display the QR code in an operator modal (so they can show their screen/tablet to the customer).
     - Send the QR image/payload to the Customer Facing Screen (via POS display services/IoT box).
     - Start polling.
3. **Fail-Safe / Operator Cancel**:
   - If payment is cancelled (by customer, operator, or timeout), POS returns to the payment selection screen allowing fallback to cash/debit.

---

## 2. Recommended Flow Improvements (POS UX/UI)

To ensure optimal speed, privacy, and flexibility in active retail settings, the following enhancements should be implemented:

1. **Auto-prefilling Phone Numbers**:
   - If a customer profile is already linked to the POS order (e.g. loyalty customer, loyalty card scan), the JS terminal interface should automatically pre-fill the customer's phone number, bypassing the manual numeric input step.
2. **Default Payment Mode Configuration**:
   - Add a configuration field to `pos.payment.method` in the Odoo backend (`Default MobilePay Mode`: `'prompt'`, `'phone_push'`, or `'qr_code'`).
   - If set to `'phone_push'` or `'qr_code'`, Odoo POS automatically initiates the payment using that method without prompt clicks. The selection prompt will only show if the operator overrides it or hits a "Change Payment Mode" option.
3. **Customer Facing Display (CFD) / QR-on-Receipt**:
   - Ensure the generated QR payload is sent directly to the Odoo POS Customer Facing Screen (CFS) for self-scanning, eliminating the need to physically tilt or share the main POS operator terminal.
   - For table-service/restaurant operations, allow printing a temporary bill slip with the payment QR code so customers can scan and pay directly at the table, automatically updating the POS state.
4. **On-the-Fly Payment Mode Switching**:
   - If the operator sends a Push notification and it fails or is not received, the POS polling UI should show a prominent `"Generate QR Code"` button. This allows the operator to switch instantly to QR payment mode without cancelling the transaction or starting over.
5. **Countdown & Live Polling UI**:
   - Provide a clear countdown timer (e.g., 60 seconds) and live progress indicators (*"Sending push..."*, *"Waiting for customer authorization..."*) to reassure both the employee and customer during the transaction.
