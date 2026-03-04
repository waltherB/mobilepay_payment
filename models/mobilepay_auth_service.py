# -*- coding: utf-8 -*-

import logging
import requests
from datetime import datetime, timedelta, timezone
from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MobilePayAuthService(models.AbstractModel):
    """OAuth2 authentication service for MobilePay API integration."""

    _name = "mobilepay.auth.service"
    _description = "MobilePay Authentication Service"

    def _get_token_cache_key(self, provider_id):
        """Generate cache key for storing access tokens."""
        return f"mobilepay_token_{provider_id}"

    def _get_token_expiry_key(self, provider_id):
        """Generate cache key for storing token expiry time."""
        return f"mobilepay_token_expiry_{provider_id}"

    def _store_token(self, provider_id, access_token, expires_in):
        """Store access token and expiry time in secure configuration parameters."""
        # Calculate expiry time (subtract 60 seconds for safety margin)
        # Use UTC timezone-aware datetime for consistency
        expiry_time = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

        # Store token and expiry in ir.config_parameter
        self.env["ir.config_parameter"].sudo().set_param(
            self._get_token_cache_key(provider_id), access_token
        )
        self.env["ir.config_parameter"].sudo().set_param(
            self._get_token_expiry_key(provider_id), expiry_time.isoformat()
        )

        _logger.info(
            f"Stored access token for provider {provider_id}, expires at {expiry_time}"
        )

    def _get_cached_token(self, provider_id):
        """Retrieve cached access token if still valid."""
        token_key = self._get_token_cache_key(provider_id)
        expiry_key = self._get_token_expiry_key(provider_id)

        token = self.env["ir.config_parameter"].sudo().get_param(token_key)
        expiry_str = self.env["ir.config_parameter"].sudo().get_param(expiry_key)

        if not token or not expiry_str:
            return None

        try:
            expiry_time = datetime.fromisoformat(expiry_str)
            # Handle both timezone-aware and naive datetimes
            now = datetime.now(timezone.utc) if expiry_time.tzinfo else datetime.now()
            if now < expiry_time:
                _logger.debug(f"Using cached token for provider {provider_id}")
                return token
            else:
                _logger.debug(f"Cached token expired for provider {provider_id}")
                return None
        except ValueError:
            _logger.warning(f"Invalid expiry time format for provider {provider_id}")
            return None

    def _clear_cached_token(self, provider_id):
        """Clear cached token and expiry time."""
        self.env["ir.config_parameter"].sudo().set_param(
            self._get_token_cache_key(provider_id), False
        )
        self.env["ir.config_parameter"].sudo().set_param(
            self._get_token_expiry_key(provider_id), False
        )
        _logger.info(f"Cleared cached token for provider {provider_id}")

    def _sanitize_value(self, value):
        """Remove invisible characters and whitespace from credentials."""
        if not value:
            return value
        # specific fix for unicode line separator \u2028 which is common in copy-paste
        return (
            str(value)
            .strip()
            .replace("\u2028", "")
            .replace("\u2029", "")
            .replace("\xa0", "")
        )

    def _acquire_new_token(self, provider):
        """Acquire new access token from MobilePay OAuth2 endpoint."""
        # Ensure computed fields are computed by accessing them
        provider.ensure_one()

        # Use active credentials computed based on state
        client_id = provider.mobilepay_client_id
        client_secret = provider.mobilepay_client_secret

        # Sanitize inputs
        client_id = self._sanitize_value(client_id)
        client_secret = self._sanitize_value(client_secret)

        if not client_id or not client_secret:
            # Provide helpful error message based on provider state
            state_msg = "production" if provider.state == "enabled" else "test"
            raise UserError(
                _(
                    "MobilePay %s credentials are not configured properly. "
                    "Please fill in the %s Client ID and Client Secret fields in the payment provider configuration."
                )
                % (state_msg, state_msg.capitalize())
            )

        token_url = f"{provider._mobilepay_get_api_url()}/accesstoken/get"

        # Get subscription key and merchant serial from active credentials
        sub_key = provider.mobilepay_subscription_key
        merchant_serial = provider.mobilepay_merchant_serial

        # Sanitize these as well
        sub_key = self._sanitize_value(sub_key)
        merchant_serial = self._sanitize_value(merchant_serial)

        # Prepare OAuth2 request data - ensure all values are strings
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "ocp-apim-subscription-key": sub_key,
        }

        headers = {
            # Authentication
            "Content-Type": "application/json",
            "client_id": client_id,
            "client_secret": client_secret,
            "Ocp-Apim-Subscription-Key": sub_key,
            # Mandatory Vipps system headers (highly recommended for troubleshooting)
            "Merchant-Serial-Number": merchant_serial,
            "Vipps-System-Name": "Odoo",
            "Vipps-System-Version": "17.0",
            "Vipps-System-Plugin-Name": "mobilepay_payment",
            "Vipps-System-Plugin-Version": "1.0.0",
            "User-Agent": "Odoo/17.0 mobilepay_payment/1.0.0",
        }

        try:
            # MobilePay Vipps API uses headers for authentication on /accesstoken/get usually
            response = requests.post(token_url, json=data, headers=headers, timeout=30)

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")
                try:
                    expires_in = int(token_data.get("expires_in", 3600))
                except (ValueError, TypeError):
                    expires_in = 3600  # Default 1 hour if invalid format

                if access_token:
                    self._store_token(provider.id, access_token, expires_in)
                    return access_token
                else:
                    raise UserError(_("Invalid token response from MobilePay API."))
            else:
                error_msg = f"Token acquisition failed: {response.status_code} - {response.text}"
                _logger.error(error_msg)
                raise UserError(
                    _("Failed to acquire access token from MobilePay API: %s")
                    % response.text
                )

        except requests.RequestException as e:
            error_msg = f"Network error during token acquisition: {str(e)}"
            _logger.error(error_msg)
            raise UserError(
                _("Network error while connecting to MobilePay API: %s") % str(e)
            )

    def get_access_token(self, provider):
        """
        Get valid access token with automatic refresh.

        Args:
            provider: payment.provider record with MobilePay configuration

        Returns:
            str: Valid access token

        Raises:
            UserError: If token acquisition fails
        """
        # Try to get cached token first
        cached_token = self._get_cached_token(provider.id)
        if cached_token:
            return cached_token

        # Acquire new token if no valid cached token
        return self._acquire_new_token(provider)

    def refresh_token(self, provider):
        """
        Force refresh of access token.

        Args:
            provider: payment.provider record with MobilePay configuration

        Returns:
            str: New access token
        """
        _logger.info(f"Force refreshing token for provider {provider.id}")
        self._clear_cached_token(provider.id)
        return self._acquire_new_token(provider)

    def handle_401_response(self, provider):
        """
        Handle 401 Unauthorized response by refreshing token and retrying once.

        Args:
            provider: payment.provider record with MobilePay configuration

        Returns:
            str: Refreshed access token
        """
        _logger.warning(
            f"Handling 401 response for provider {provider.id}, refreshing token"
        )
        return self.refresh_token(provider)
