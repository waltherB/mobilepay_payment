# MobilePay (Vipps) Payment Provider for Odoo

This module integrates the **Vipps MobilePay ePayment API v3** with Odoo, enabling secure and seamless payments for the **Danish market**.

## Features

*   **MobilePay Online**: Customers can pay using the MobilePay app on their phone.
*   **Phone Number Pre-fill**: Automatically pre-fills the customer's phone number if available in their profile.
*   **Advanced Capture Flows**:
    *   **Manual Capture**: Standard authorize and capture flow.
    *   **Capture on Delivery**: Automatically capture funds when the related delivery order is validated (integrated with Odoo Stock).
    *   **Automatic after Delay**: Capture automatically after a configurable number of hours.
*   **Secure**: Uses HMAC-SHA256 signature verification for webhooks and Fernet encryption for API credentials stored in the database.
*   **Order Management**: Supports Authorization, Capture, Voiding, and Full/Partial Refunds directly from Odoo.
*   **Diagnostic Tools**: Built-in tools for API connection testing and real-time webhook management.
*   **Localization**: Fully localized for Danish (da_DK).

## Installation

### 1. Python Dependencies
This module requires the `cryptography` library for secure credential encryption.
```bash
pip3 install cryptography
```

### 2. Module Installation
1.  Place the `mobilepay_payment` folder into your Odoo custom addons directory.
2.  Restart your Odoo service.
3.  Log in as Administrator and activate **Developer Mode**.
4.  Go to **Apps** → **Update Apps List**, then search for **MobilePay Payment Provider** and click **Activate**.

## Configuration

### 1. Prerequisites
You must have a **MobilePay Merchant Account**. Obtain your credentials from the [MobilePay Developer Portal](https://developer.vippsmobilepay.com/):
*   Client ID
*   Client Secret
*   Subscription Key
*   Merchant Serial Number

### 2. Setup in Odoo
1.  **Navigate to Payment Providers**: Go to **Accounting** → **Configuration** → **Payment Providers** and select **MobilePay**.
2.  **Configure Credentials**:
    *   The module supports separate credentials for **Test** and **Production** environments.
    *   Enter your credentials in the corresponding tabs.
    *   Credentials are encrypted automatically upon saving.
3.  **Test Connection**: Use the **Test API Connection** button in the Diagnostic Tools section to verify your credentials.
4.  **Register Webhook**: Click **Register Webhook** to automatically configure your Odoo instance to receive real-time payment updates.

## Usage

### Capture Flows
You can configure the capture behavior under the **Configuration** tab of the provider:
*   **Manual**: Transactions remain in 'Authorized' state until you manually click 'Capture' on the transaction.
*   **Capture on Delivery**: Ideal for physical goods. Odoo will capture the payment only when the delivery order is validated.
*   **Automatic after Delay**: Set a delay (e.g., 24 hours) after which Odoo will automatically capture authorized payments via a scheduled action.

### Order Management (Backend)
*   **Capture/Void**: Managed via the transaction form for authorized payments.
*   **Refund**: Full or partial refunds can be initiated from the captured transaction.

## Troubleshooting

*   **Missing "MobilePay" option**: Ensure the currency is set to **DKK**. MobilePay V3 only supports DKK for this integration.
*   **Webhook Error**: Ensure your `web.base.url` parameter is set to an **HTTPS** URL.
*   **Connection Error**: Verify your Client Secret and Subscription Key are correct for the selected environment (Test vs Production).

## Compatibility

This module is designed for **Odoo 17** (Enterprise and Community). It requires `stock` and `sale_stock` modules for the "Capture on Delivery" feature.
