# -*- coding: utf-8 -*-

import json
import logging
import requests
from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MobilePayApiClient(models.AbstractModel):
    """Base API client for MobilePay API integration with mandatory headers."""

    _name = "mobilepay.api.client"
    _description = "MobilePay API Client"

    def _sanitize_header(self, value):
        """Remove invisible characters and whitespace from header values."""
        if not value:
            return ""
        return (
            str(value)
            .strip()
            .replace("\u2028", "")
            .replace("\u2029", "")
            .replace("\xa0", "")
        )

    def _get_system_headers(self, provider):
        """
        Build mandatory Vipps system headers for all API requests.

        Args:
            provider: payment.provider record with MobilePay configuration

        Returns:
            dict: Headers dictionary with all mandatory system headers
        """
        # Get access token from auth service
        auth_service = self.env["mobilepay.auth.service"]
        access_token = auth_service.get_access_token(provider)

        headers = {
            # Authentication
            "Authorization": f"Bearer {access_token}",
            # Mandatory Vipps system headers
            "Vipps-System-Name": "Odoo",
            "Vipps-System-Version": "17.0",
            "Vipps-System-Plugin-Name": "mobilepay_payment",
            "Vipps-System-Plugin-Version": "1.0.0",
            "User-Agent": "Odoo/17.0 mobilepay_payment/1.0.0",
            # API subscription and merchant identification
            "Ocp-Apim-Subscription-Key": self._sanitize_header(
                provider.mobilepay_subscription_key
                or (
                    provider.mobilepay_test_subscription_key
                    if provider.state != "enabled"
                    else provider.mobilepay_prod_subscription_key
                )
            ),
            "Merchant-Serial-Number": self._sanitize_header(
                provider.mobilepay_merchant_serial
                or (
                    provider.mobilepay_test_merchant_serial
                    if provider.state != "enabled"
                    else provider.mobilepay_prod_merchant_serial
                )
            ),
            # Content type headers
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        return headers

    def _make_request(
        self,
        provider,
        method,
        endpoint,
        data=None,
        params=None,
        retry_on_401=True,
        idempotency_key=None,
    ):
        """
        Make HTTP request to MobilePay API with proper error handling.

        Args:
            provider: payment.provider record
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint path (e.g., '/epayment/v1/payments')
            data: Request body data (for POST/PUT requests)
            params: URL query parameters
            retry_on_401: Whether to retry once on 401 Unauthorized
            idempotency_key: Optional Idempotency-Key header value

        Returns:
            requests.Response: API response object

        Raises:
            UserError: If request fails or returns error status
        """
        base_url = provider._mobilepay_get_api_url()
        url = f"{base_url}{endpoint}"

        headers = self._get_system_headers(provider)

        # Add Idempotency-Key header if provided
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        # Prepare request data
        request_kwargs = {"headers": headers, "timeout": 30}

        if data is not None:
            request_kwargs["json"] = data
        if params is not None:
            request_kwargs["params"] = params

        try:
            _logger.info(f"Making {method} request to {url}")
            response = requests.request(method, url, **request_kwargs)

            # Handle 401 Unauthorized with token refresh and retry
            if response.status_code == 401 and retry_on_401:
                _logger.warning("Received 401 response, refreshing token and retrying")

                # Refresh token through auth service
                auth_service = self.env["mobilepay.auth.service"]
                auth_service.handle_401_response(provider)

                # Update headers with new token and retry once
                headers = self._get_system_headers(provider)
                if idempotency_key:
                    headers["Idempotency-Key"] = idempotency_key

                request_kwargs["headers"] = headers

                _logger.info(f"Retrying {method} request to {url} with refreshed token")
                response = requests.request(method, url, **request_kwargs)

            # Log response for debugging
            _logger.info(f"API response (HTTP {response.status_code}): {response.text}")
            if response.status_code >= 400:
                _logger.error(f"API error response body: {response.text}")

            return response

        except requests.RequestException as e:
            error_msg = f"Network error during API request to {url}: {str(e)}"
            _logger.error(error_msg)
            raise UserError(
                _("Network error while connecting to MobilePay API: %s") % str(e)
            )

    def _handle_response(self, response, expected_status=200):
        """
        Handle API response and extract JSON data with error checking.

        Args:
            response: requests.Response object
            expected_status: Expected HTTP status code (default: 200)

        Returns:
            dict: Parsed JSON response data

        Raises:
            UserError: If response status is not as expected or JSON parsing fails
        """
        if response.status_code != expected_status:
            try:
                error_data = response.json()
                error_message = error_data.get("message", response.text)
            except (ValueError, json.JSONDecodeError):
                error_message = response.text

            raise UserError(
                _("MobilePay API error (HTTP %s): %s")
                % (response.status_code, error_message)
            )

        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as e:
            _logger.error(f"Failed to parse JSON response: {str(e)}")
            raise UserError(_("Invalid JSON response from MobilePay API"))

    def get_payment_status(self, provider, payment_id):
        """
        Get payment status from MobilePay API.

        Args:
            provider: payment.provider record
            payment_id: MobilePay payment ID

        Returns:
            dict: Payment status data
        """
        endpoint = f"/epayment/v1/payments/{payment_id}"
        response = self._make_request(provider, "GET", endpoint)
        return self._handle_response(response)

    def get_payment_events(self, provider, payment_id):
        """
        Get payment events from MobilePay API.

        Args:
            provider: payment.provider record
            payment_id: MobilePay payment ID

        Returns:
            dict: Payment events data
        """
        endpoint = f"/epayment/v1/payments/{payment_id}/events"
        response = self._make_request(provider, "GET", endpoint)
        return self._handle_response(response)

    def create_payment(self, provider, payment_data, idempotency_key=None):
        """
        Create new payment via MobilePay API.

        Args:
            provider: payment.provider record
            payment_data: Payment creation data
            idempotency_key: Unique key for idempotency

        Returns:
            dict: Created payment data
        """
        endpoint = "/epayment/v1/payments"
        response = self._make_request(
            provider,
            "POST",
            endpoint,
            data=payment_data,
            idempotency_key=idempotency_key,
        )
        return self._handle_response(response, expected_status=201)

    def capture_payment(self, provider, payment_id, capture_data, idempotency_key=None):
        """
        Capture authorized payment via MobilePay API.

        Args:
            provider: payment.provider record
            payment_id: MobilePay payment ID
            capture_data: Capture request data
            idempotency_key: Unique key for idempotency

        Returns:
            dict: Capture response data
        """
        endpoint = f"/epayment/v1/payments/{payment_id}/capture"
        response = self._make_request(
            provider,
            "POST",
            endpoint,
            data=capture_data,
            idempotency_key=idempotency_key,
        )
        return self._handle_response(response, expected_status=200)

    def refund_payment(self, provider, payment_id, refund_data, idempotency_key=None):
        """
        Refund payment via MobilePay API.

        Args:
            provider: payment.provider record
            payment_id: MobilePay payment ID
            refund_data: Refund request data
            idempotency_key: Unique key for idempotency

        Returns:
            dict: Refund response data
        """
        endpoint = f"/epayment/v1/payments/{payment_id}/refund"
        response = self._make_request(
            provider,
            "POST",
            endpoint,
            data=refund_data,
            idempotency_key=idempotency_key,
        )
        return self._handle_response(response)

    def cancel_payment(self, provider, payment_id, idempotency_key=None):
        """
        Cancel payment via MobilePay API.

        Args:
            provider: payment.provider record
            payment_id: MobilePay payment ID
            idempotency_key: Unique key for idempotency

        Returns:
            dict: Cancel response data
        """
        endpoint = f"/epayment/v1/payments/{payment_id}/cancel"
        response = self._make_request(
            provider, "POST", endpoint, idempotency_key=idempotency_key
        )
        return self._handle_response(response)

    def register_webhook(self, provider, webhook_data):
        """
        Register webhook with MobilePay API.
        """
        endpoint = "/webhooks/v1/webhooks"
        response = self._make_request(provider, "POST", endpoint, data=webhook_data)
        return self._handle_response(response, expected_status=201)

    def unregister_webhook(self, provider, webhook_id):
        """
        Unregister webhook from MobilePay API.
        """
        endpoint = f"/webhooks/v1/webhooks/{webhook_id}"
        response = self._make_request(provider, "DELETE", endpoint)

        if response.status_code in [200, 204, 404]:
            return True
        else:
            self._handle_response(response, expected_status=200)

    def get_settlement_reports(self, provider, date_from, date_to):
        """
        Fetch settlement ledger entries from Vipps/MobilePay Report API.
        
        Args:
            provider: payment.provider record
            date_from (date/datetime): Start date
            date_to (date/datetime): End date
            
        Returns:
            list: List of raw ledger entries
        """
        # 1. Fetch ledgers to find the ledger ID for the provider's Merchant Serial Number (MSN)
        ledgers_endpoint = "/settlement/v1/ledgers"
        try:
            ledgers_response = self._make_request(provider, "GET", ledgers_endpoint)
            ledgers = self._handle_response(ledgers_response)
        except Exception as e:
            _logger.error("Failed to fetch MobilePay ledgers: %s", str(e))
            return []

        # Find the MSN of the provider
        provider_msn = provider.mobilepay_merchant_serial or (
            provider.mobilepay_test_merchant_serial
            if provider.state != "enabled"
            else provider.mobilepay_prod_merchant_serial
        )
        provider_msn = self._sanitize_header(provider_msn)

        ledger_id = None
        for ledger in ledgers:
            # Match by salesUnitId (which is the Merchant Serial Number / MSN)
            if self._sanitize_header(ledger.get("salesUnitId")) == provider_msn:
                ledger_id = ledger.get("ledgerId")
                break

        if not ledger_id:
            _logger.warning("No MobilePay ledger found matching Merchant Serial Number (MSN): %s", provider_msn)
            return []

        # 2. Fetch entries for the matched ledger
        entries_endpoint = f"/settlement/v1/ledgers/{ledger_id}/entries"
        params = {
            "from": date_from.strftime("%Y-%m-%dT00:00:00Z"),
            "to": date_to.strftime("%Y-%m-%dT23:59:59Z"),
        }

        try:
            entries_response = self._make_request(provider, "GET", entries_endpoint, params=params)
            entries_data = self._handle_response(entries_response)
            
            # The API returns a list of entries or an object containing an entries list
            if isinstance(entries_data, list):
                return entries_data
            elif isinstance(entries_data, dict):
                return entries_data.get("entries") or []
            return []
        except Exception as e:
            _logger.error("Failed to fetch MobilePay ledger entries for ledger %s: %s", ledger_id, str(e))
            return []
