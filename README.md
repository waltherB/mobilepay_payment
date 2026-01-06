# MobilePay (Vipps) Payment Provider for Odoo

This module integrates the **Vipps MobilePay ePayment API v3** with Odoo, enabling secure and seamless payments for the Danish market.

## Features

*   **MobilePay Online**: Customers can pay using the MobilePay app on their phone.
*   **Phone Number Pre-fill**: Automatically pre-fills the customer's phone number if available in their profile.
*   **Secure**: Uses HMAC-SHA256 signature verification for webhooks and encryption for API credentials.
*   **Order Management**: Supports Authorization, Manual Capture, and Full/Partial Refunds directly from Odoo.
*   **Localization**: Fully localized for Danish (da_DK).

## Installation

### 1. Python Dependencies
This module strictly requires the `cryptography` library to handle secure credential encryption.
```bash
pip3 install cryptography
```

### 2. Module Installation
1.  Place the `mobilepay_payment` folder into your Odoo custom addons directory.
2.  Restart your Odoo service.
3.  Log in to Odoo as an Administrator.
4.  Activate **Developer Mode**.
5.  Go to **Apps** and click **Update Apps List**.
6.  Search for **MobilePay Payment Provider** and click **Activate**.

## Configuration

### 1. Prerequisites
You must have a **MobilePay Merchant Account**. You will need the following credentials from the [MobilePay Developer Portal](https://developer.vippsmobilepay.com/):
*   Client ID
*   Client Secret
*   Subscription Key
*   Merchant Serial Number

### 2. Setup in Odoo
1.  **Navigate to Payment Providers**:
    *   Go to **Accounting** → **Configuration** → **Payment Providers**.
    *   Find or create a **MobilePay** provider.

2.  **Configure Credentials**:
    *   The module supports **separate credentials** for Test and Production environments.
    *   **Test Mode**: When the provider State is set to "Test Mode", configure:
        *   Test Client ID
        *   Test Client Secret
        *   Test Subscription Key (Ocp-Apim-Subscription-Key)
        *   Test Merchant Serial Number
    *   **Production Mode**: When the provider State is set to "Enabled", configure:
        *   Production Client ID
        *   Production Client Secret
        *   Production Subscription Key (Ocp-Apim-Subscription-Key)
        *   Production Merchant Serial Number
    *   The module automatically uses the correct credentials based on the provider State.

3.  **Register Webhook**:
    *   Ensure your Odoo instance is accessible via **HTTPS**.
    *   Click **Register Webhook** to automatically register your webhook URL with MobilePay.
    *   The webhook secret will be stored securely and used to verify incoming notifications.
    *   You should see a success notification.

## Usage

### Paying with MobilePay
1.  On the checkout page, select **MobilePay**.
2.  Enter your phone number (pre-filled if logged in).
3.  Click **Pay**.
4.  Accept the payment in the MobilePay app on your phone.
5.  You will be redirected back to Odoo upon success.

### Order Management (Backend)
*   **Capture**: By default, payments are authorized (reserved). To capture funds:
    *   Go to the **Sales Order** or **Invoice**.
    *   Navigate to the **Transaction**.
    *   Click **Capture Transaction**.
*   **Cancel**:
    *   Go to the transaction of an authorized (but not captured) payment.
    *   Click **Void Transaction**.
    *   This will release the reservation in MobilePay and cancel the transaction in Odoo.
*   **Refund**:
    *   Go to the transaction of a captured payment.
    *   Click **Refund**.
    *   Enter the amount (supports partial refunds) and confirm.

## Troubleshooting

*   **Missing "MobilePay" option**: Ensure the currency is set to **DKK**. MobilePay V3 only supports DKK for this integration.
*   **Webhook Error**: Ensure your `web.base.url` parameter is set to an **HTTPS** URL.
*   **Connection Error**: Verify your Client Secret and Subscription Key are correct for the selected environment (Test vs Production).
