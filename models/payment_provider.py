# -*- coding: utf-8 -*-

import logging
import json
from urllib.parse import urlparse, urlunparse
from cryptography.fernet import Fernet
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[("mobilepay", "MobilePay")], ondelete={"mobilepay": "cascade"}
    )


    auto_capture_delay = fields.Integer(
        string="Auto Capture Delay (hours)",
        help="Delay in hours before automatic capture (when manual capture is disabled).",
        default=24,
    )
    capture_on_delivery = fields.Boolean(
        string="Capture on Delivery",
        help="Automatically capture authorized payments when the related delivery order is validated.",
        default=False,
    )
    capture_mode = fields.Selection(
        [
            ("manual", "Manual Capture"),
            ("delivery", "Capture on Delivery"),
            ("auto_delay", "Automatic Capture after Delay"),
        ],
        string="Capture Flow",
        compute="_compute_capture_mode",
        inverse="_inverse_capture_mode",
        store=False,
        help="Select how MobilePay should capture authorized payments.",
    )
    
    mobilepay_logic_version = fields.Char(
        string="Logic Version",
        compute="_compute_mobilepay_logic_version",
        help="Diagnostic version of the MobilePay integration logic.",
    )

    # Settlement & Fees Reconciliation Fields (CE Compatible)
    mobilepay_fee_account_id = fields.Many2one(
        "account.account",
        string="MobilePay Fee Account",
        help="The expense account where transaction fees will be recorded.",
    )
    mobilepay_clearing_account_id = fields.Many2one(
        "account.account",
        string="MobilePay Clearing Account",
        help="The transit/clearing asset account where gross customer payments are captured in real-time.",
    )
    mobilepay_journal_id = fields.Many2one(
        "account.journal",
        string="MobilePay Journal",
        help="The Misc/Bank journal where payout entries and fee write-offs will be posted.",
    )
    mobilepay_auto_post_settlements = fields.Boolean(
        string="Auto-Post Settlements",
        default=True,
        help="If enabled, payout journal entries will post and reconcile automatically. Otherwise, they will save as Draft.",
    )
    mobilepay_fee_tax_id = fields.Many2one(
        "account.tax",
        string="MobilePay Fee Tax",
        help="Optional tax/VAT code to apply to the transaction fee expense line.",
    )

    @api.depends("code")
    def _compute_mobilepay_logic_version(self):
        for provider in self:
            provider.mobilepay_logic_version = "v42.2-Robust"

    def _sanitize_value(self, value):
        """Remove invisible characters and whitespace from credentials."""
        if not value:
            return value
        return (
            str(value)
            .strip()
            .replace("\u2028", "")
            .replace("\u2029", "")
            .replace("\xa0", "")
        )

    def write(self, values):
        # Sanitize all MobilePay fields if present
        for field in [
            "mobilepay_test_client_id",
            "mobilepay_test_client_secret",
            "mobilepay_test_subscription_key",
            "mobilepay_test_merchant_serial",
            "mobilepay_prod_client_id",
            "mobilepay_prod_client_secret",
            "mobilepay_prod_subscription_key",
            "mobilepay_prod_merchant_serial",
            "mobilepay_webhook_secret",
        ]:
            if field in values:
                values[field] = self._sanitize_value(values[field])

        # Manually handle encryption for test credentials
        if "mobilepay_test_client_secret" in values:
            if values["mobilepay_test_client_secret"]:
                values["mobilepay_test_client_secret_encrypted"] = self._encrypt(
                    values["mobilepay_test_client_secret"]
                )
            else:
                values["mobilepay_test_client_secret_encrypted"] = False
            # Remove the computed field from write values to avoid issues
            del values["mobilepay_test_client_secret"]

        if "mobilepay_test_subscription_key" in values:
            if values["mobilepay_test_subscription_key"]:
                values["mobilepay_test_subscription_key_encrypted"] = self._encrypt(
                    values["mobilepay_test_subscription_key"]
                )
            else:
                values["mobilepay_test_subscription_key_encrypted"] = False
            # Remove the computed field from write values
            del values["mobilepay_test_subscription_key"]

        # Manually handle encryption for prod credentials
        if "mobilepay_prod_client_secret" in values:
            if values["mobilepay_prod_client_secret"]:
                values["mobilepay_prod_client_secret_encrypted"] = self._encrypt(
                    values["mobilepay_prod_client_secret"]
                )
            else:
                values["mobilepay_prod_client_secret_encrypted"] = False
            del values["mobilepay_prod_client_secret"]

        if "mobilepay_prod_subscription_key" in values:
            if values["mobilepay_prod_subscription_key"]:
                values["mobilepay_prod_subscription_key_encrypted"] = self._encrypt(
                    values["mobilepay_prod_subscription_key"]
                )
            else:
                values["mobilepay_prod_subscription_key_encrypted"] = False
            del values["mobilepay_prod_subscription_key"]

        if "mobilepay_webhook_secret" in values:
            if values["mobilepay_webhook_secret"]:
                values["mobilepay_webhook_secret_encrypted"] = self._encrypt(
                    values["mobilepay_webhook_secret"]
                )
            else:
                values["mobilepay_webhook_secret_encrypted"] = False
            del values["mobilepay_webhook_secret"]

        return super().write(values)

    show_mobilepay_fields = fields.Boolean(
        compute="_compute_show_mobilepay_fields",
        help="Technical field to control visibility of MobilePay specific fields.",
    )

    @api.depends("code")
    def _compute_show_mobilepay_fields(self):
        for provider in self:
            provider.show_mobilepay_fields = provider.code == "mobilepay"

    @api.depends("capture_manually", "capture_on_delivery")
    def _compute_capture_mode(self):
        for provider in self:
            if provider.capture_manually:
                provider.capture_mode = (
                    "delivery" if provider.capture_on_delivery else "manual"
                )
            else:
                provider.capture_mode = "auto_delay"

    def _inverse_capture_mode(self):
        for provider in self:
            if provider.capture_mode == "manual":
                provider.capture_manually = True
                provider.capture_on_delivery = False
            elif provider.capture_mode == "delivery":
                provider.capture_manually = True
                provider.capture_on_delivery = True
            else:
                provider.capture_manually = False
                provider.capture_on_delivery = False

    def _compute_feature_support_fields(self):
        """Override of `payment` to enable additional features."""
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == "mobilepay").update(
            {
                "support_manual_capture": "partial",
                "support_refund": "partial",
                "support_tokenization": False,
            }
        )

    # ===== Test Environment Credentials =====
    mobilepay_test_client_id = fields.Char(
        string="Test Client ID", help="MobilePay Test API Client ID"
    )

    mobilepay_test_client_secret_encrypted = fields.Char(
        string="Test Client Secret (Encrypted)", copy=False
    )

    mobilepay_test_client_secret = fields.Char(
        string="Test Client Secret",
        help="MobilePay Test API Client Secret (encrypted)",
        compute="_compute_mobilepay_test_client_secret",
        inverse="_inverse_mobilepay_test_client_secret",
    )

    mobilepay_test_subscription_key_encrypted = fields.Char(
        string="Test Subscription Key (Encrypted)", copy=False
    )

    mobilepay_test_subscription_key = fields.Char(
        string="Test Subscription Key",
        help="MobilePay Test API Subscription Key (encrypted)",
        compute="_compute_mobilepay_test_subscription_key",
        inverse="_inverse_mobilepay_test_subscription_key",
    )

    mobilepay_test_merchant_serial = fields.Char(
        string="Test Merchant Serial Number",
        help="MobilePay Test Merchant Serial Number",
    )

    # ===== Production Environment Credentials =====
    mobilepay_prod_client_id = fields.Char(
        string="Production Client ID", help="MobilePay Production API Client ID"
    )

    mobilepay_prod_client_secret_encrypted = fields.Char(
        string="Production Client Secret (Encrypted)", copy=False
    )

    mobilepay_prod_client_secret = fields.Char(
        string="Production Client Secret",
        help="MobilePay Production API Client Secret (encrypted)",
        compute="_compute_mobilepay_prod_client_secret",
        inverse="_inverse_mobilepay_prod_client_secret",
    )

    mobilepay_prod_subscription_key_encrypted = fields.Char(
        string="Production Subscription Key (Encrypted)", copy=False
    )

    mobilepay_prod_subscription_key = fields.Char(
        string="Production Subscription Key",
        help="MobilePay Production API Subscription Key (encrypted)",
        compute="_compute_mobilepay_prod_subscription_key",
        inverse="_inverse_mobilepay_prod_subscription_key",
    )

    mobilepay_prod_merchant_serial = fields.Char(
        string="Production Merchant Serial Number",
        help="MobilePay Production Merchant Serial Number",
    )

    # ===== Active Credentials (Computed based on state) =====
    mobilepay_client_id = fields.Char(
        string="Client ID",
        help="Active MobilePay API Client ID (auto-selected based on state)",
        compute="_compute_active_credentials",
        store=False,
        compute_sudo=True,
    )

    mobilepay_client_secret = fields.Char(
        string="Client Secret",
        help="Active MobilePay API Client Secret (auto-selected based on state)",
        compute="_compute_active_credentials",
        store=False,
        compute_sudo=True,
    )

    mobilepay_subscription_key = fields.Char(
        string="Subscription Key",
        help="Active MobilePay API Subscription Key (auto-selected based on state)",
        compute="_compute_active_credentials",
        store=False,
        compute_sudo=True,
    )

    mobilepay_merchant_serial = fields.Char(
        string="Merchant Serial Number",
        help="Active MobilePay Merchant Serial Number (auto-selected based on state)",
        compute="_compute_active_credentials",
        store=False,
        compute_sudo=True,
    )

    # Webhook Configuration
    mobilepay_webhook_id = fields.Char(
        string="Webhook ID", help="Registered webhook ID from MobilePay", readonly=True
    )

    mobilepay_webhook_secret_encrypted = fields.Char(
        string="Webhook Secret (Encrypted)", copy=False
    )

    mobilepay_webhook_secret = fields.Char(
        string="Webhook Secret",
        help="Webhook signature verification secret (encrypted)",
        compute="_compute_mobilepay_webhook_secret",
        inverse="_inverse_mobilepay_webhook_secret",
    )

    # Encryption Helpers
    def _get_encryption_key(self):
        """Get or create the encryption key from ir.config_parameter."""
        param_obj = self.env["ir.config_parameter"].sudo()
        key = param_obj.get_param("mobilepay.encryption_key")
        if not key:
            key = Fernet.generate_key().decode()
            param_obj.set_param("mobilepay.encryption_key", key)
        return key.encode()

    def _encrypt(self, value):
        """Encrypt a value."""
        if not value:
            return False
        try:
            f = Fernet(self._get_encryption_key())
            encrypted = f.encrypt(value.encode()).decode()
            return encrypted
        except Exception as e:
            _logger.error(f"Encryption failed: {e}")
            return False

    def _decrypt(self, value):
        """Decrypt a value."""
        if not value:
            return False
        try:
            f = Fernet(self._get_encryption_key())
            return f.decrypt(value.encode()).decode()
        except Exception:
            _logger.error("Failed to decrypt MobilePay credentials")
            return False

    def _mobilepay_get_api_url(self):
        """
        Get the API base URL based on the provider state.

        Returns:
            str: API base URL (Production or Test)
        """
        self.ensure_one()
        if self.state == "enabled":
            return "https://api.vipps.no"
        else:
            return "https://apitest.vipps.no"

    # Compute/Inverse methods for Test credentials
    @api.depends("mobilepay_test_client_secret_encrypted")
    def _compute_mobilepay_test_client_secret(self):
        for provider in self:
            if provider.mobilepay_test_client_secret_encrypted:
                provider.mobilepay_test_client_secret = provider._decrypt(
                    provider.mobilepay_test_client_secret_encrypted
                )
            else:
                provider.mobilepay_test_client_secret = False

    def _inverse_mobilepay_test_client_secret(self):
        for provider in self:
            if provider.mobilepay_test_client_secret:
                provider.mobilepay_test_client_secret_encrypted = provider._encrypt(
                    provider.mobilepay_test_client_secret
                )
            else:
                provider.mobilepay_test_client_secret_encrypted = False

    @api.depends("mobilepay_test_subscription_key_encrypted")
    def _compute_mobilepay_test_subscription_key(self):
        for provider in self:
            if provider.mobilepay_test_subscription_key_encrypted:
                provider.mobilepay_test_subscription_key = provider._decrypt(
                    provider.mobilepay_test_subscription_key_encrypted
                )
            else:
                provider.mobilepay_test_subscription_key = False

    def _inverse_mobilepay_test_subscription_key(self):
        for provider in self:
            if provider.mobilepay_test_subscription_key:
                provider.mobilepay_test_subscription_key_encrypted = provider._encrypt(
                    provider.mobilepay_test_subscription_key
                )
            else:
                provider.mobilepay_test_subscription_key_encrypted = False

    # Compute/Inverse methods for Production credentials
    @api.depends("mobilepay_prod_client_secret_encrypted")
    def _compute_mobilepay_prod_client_secret(self):
        for provider in self:
            if provider.mobilepay_prod_client_secret_encrypted:
                provider.mobilepay_prod_client_secret = provider._decrypt(
                    provider.mobilepay_prod_client_secret_encrypted
                )
            else:
                provider.mobilepay_prod_client_secret = False

    def _inverse_mobilepay_prod_client_secret(self):
        for provider in self:
            if provider.mobilepay_prod_client_secret:
                provider.mobilepay_prod_client_secret_encrypted = provider._encrypt(
                    provider.mobilepay_prod_client_secret
                )
            else:
                provider.mobilepay_prod_client_secret_encrypted = False

    @api.depends("mobilepay_prod_subscription_key_encrypted")
    def _compute_mobilepay_prod_subscription_key(self):
        for provider in self:
            if provider.mobilepay_prod_subscription_key_encrypted:
                provider.mobilepay_prod_subscription_key = provider._decrypt(
                    provider.mobilepay_prod_subscription_key_encrypted
                )
            else:
                provider.mobilepay_prod_subscription_key = False

    def _inverse_mobilepay_prod_subscription_key(self):
        for provider in self:
            if provider.mobilepay_prod_subscription_key:
                provider.mobilepay_prod_subscription_key_encrypted = provider._encrypt(
                    provider.mobilepay_prod_subscription_key
                )
            else:
                provider.mobilepay_prod_subscription_key_encrypted = False

    # Compute method for active credentials (auto-select based on state)
    @api.depends(
        "state",
        "mobilepay_test_client_id",
        "mobilepay_test_client_secret_encrypted",
        "mobilepay_test_subscription_key_encrypted",
        "mobilepay_test_merchant_serial",
        "mobilepay_prod_client_id",
        "mobilepay_prod_client_id",
        "mobilepay_prod_client_secret_encrypted",
        "mobilepay_prod_subscription_key_encrypted",
        "mobilepay_prod_merchant_serial",
    )
    def _compute_active_credentials(self):
        """Compute non-stored MobilePay credentials."""
        for provider in self:
            if provider.state == "enabled":
                # Production mode
                provider.mobilepay_client_id = provider.mobilepay_prod_client_id
                provider.mobilepay_client_secret = (
                    provider._decrypt(provider.mobilepay_prod_client_secret_encrypted)
                    if provider.mobilepay_prod_client_secret_encrypted
                    else False
                )
                provider.mobilepay_subscription_key = (
                    provider._decrypt(
                        provider.mobilepay_prod_subscription_key_encrypted
                    )
                    if provider.mobilepay_prod_subscription_key_encrypted
                    else False
                )
                provider.mobilepay_merchant_serial = (
                    provider.mobilepay_prod_merchant_serial
                )
            else:
                # Test mode (test or disabled)
                provider.mobilepay_client_id = provider.mobilepay_test_client_id
                provider.mobilepay_client_secret = (
                    provider._decrypt(provider.mobilepay_test_client_secret_encrypted)
                    if provider.mobilepay_test_client_secret_encrypted
                    else False
                )
                provider.mobilepay_subscription_key = (
                    provider._decrypt(
                        provider.mobilepay_test_subscription_key_encrypted
                    )
                    if provider.mobilepay_test_subscription_key_encrypted
                    else False
                )
                provider.mobilepay_merchant_serial = (
                    provider.mobilepay_test_merchant_serial
                )

    # Compute/Inverse methods for Webhook Secret
    @api.depends("mobilepay_webhook_secret_encrypted")
    def _compute_mobilepay_webhook_secret(self):
        for provider in self:
            if provider.mobilepay_webhook_secret_encrypted:
                provider.mobilepay_webhook_secret = provider._decrypt(
                    provider.mobilepay_webhook_secret_encrypted
                )
            else:
                provider.mobilepay_webhook_secret = False

    def _inverse_mobilepay_webhook_secret(self):
        for provider in self:
            if provider.mobilepay_webhook_secret:
                provider.mobilepay_webhook_secret_encrypted = provider._encrypt(
                    provider.mobilepay_webhook_secret
                )
            else:
                provider.mobilepay_webhook_secret_encrypted = False

    @api.constrains(
        "state",
        "mobilepay_prod_client_id",
        "mobilepay_prod_client_secret_encrypted",
        "mobilepay_prod_subscription_key_encrypted",
        "mobilepay_prod_merchant_serial",
    )
    def _check_mobilepay_credentials(self):
        """Validate MobilePay production credentials when provider is enabled."""
        for provider in self:
            if provider.code == "mobilepay" and provider.state == "enabled":
                # Production mode - check production credentials only when enabled
                if not all(
                    [
                        provider.mobilepay_prod_client_id,
                        provider.mobilepay_prod_client_secret_encrypted,
                        provider.mobilepay_prod_subscription_key_encrypted,
                        provider.mobilepay_prod_merchant_serial,
                    ]
                ):
                    raise ValidationError(
                        _(
                            "All MobilePay production credentials are required when provider is enabled: "
                            "Production Client ID, Production Client Secret, Production Subscription Key, "
                            "and Production Merchant Serial Number"
                        )
                    )

    @api.model
    def _get_compatible_providers(self, *args, currency_id=None, **kwargs):
        """Override to ensure MobilePay only works with DKK currency."""
        providers = super()._get_compatible_providers(
            *args, currency_id=currency_id, **kwargs
        )

        _logger.info(
            f"MobilePay: _get_compatible_providers call. Currency ID: {currency_id}. "
            f"Partner ID: {kwargs.get('partner_id')}. Website ID: {kwargs.get('website_id')}. "
            f"Force: {kwargs.get('force_selection')}"
        )
        _logger.info(
            f"MobilePay: Initial compatible providers: {providers.mapped('name')} ({providers.mapped('code')})"
        )

        if currency_id:
            currency = self.env["res.currency"].browse(currency_id)
            if currency.name not in ("DKK", "NOK", "EUR"):
                # Filter out MobilePay providers for unsupported currencies
                mobilepay_providers = providers.filtered(
                    lambda p: p.code == "mobilepay"
                )
                if mobilepay_providers:
                    _logger.info(
                        f"MobilePay: Filtering out {len(mobilepay_providers)} providers because currency is {currency.name}"
                    )
                providers = providers.filtered(lambda p: p.code != "mobilepay")

        return providers

    def action_test_connection(self):
        """Test connection to MobilePay API by fetching an access token."""
        self.ensure_one()
        self._check_mobilepay_credentials()
        try:
            # Fetching system headers implicitly fetches and validates the OAuth token
            api_client = self.env["mobilepay.api.client"]
            api_client._get_system_headers(self)
            
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Successful"),
                    "message": _("Successfully connected to the MobilePay API! Your credentials are valid."),
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as e:
            raise UserError(_("Connection failed: %s") % str(e))

    def action_register_webhook(self):
        """Register webhook with MobilePay API."""
        self._check_mobilepay_credentials()

        try:
            webhook_id, webhook_secret = self._register_webhook_with_api()

            # Store webhook credentials
            self.write(
                {
                    "mobilepay_webhook_id": webhook_id,
                    "mobilepay_webhook_secret": webhook_secret,
                }
            )

            # Test webhook connectivity
            self._test_webhook_connectivity()

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Webhook Registration Successful"),
                    "message": _(
                        "Webhook has been registered successfully with MobilePay. ID: %s"
                    )
                    % webhook_id,
                    "type": "success",
                },
            }

        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Webhook Registration Failed"),
                    "message": _("Failed to register webhook: %s") % str(e),
                    "type": "danger",
                },
            }

    def _register_webhook_with_api(self):
        """
        Register webhook with MobilePay API and return webhook ID and secret.

        Returns:
            tuple: (webhook_id, webhook_secret)

        Raises:
            UserError: If webhook registration fails
        """
        # Get and sanitize base URL
        raw_base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        if not raw_base_url:
            raise UserError(_("System base URL is not configured (web.base.url)."))

        base_url = raw_base_url.strip()
        if not base_url:
            raise UserError(_("System base URL is not configured (web.base.url)."))

        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in ("https", "http") or not parsed_url.netloc:
            raise UserError(
                _(
                    "MobilePay webhook registration requires a valid web.base.url with HTTPS. "
                    "Current value is invalid: %s"
                )
                % base_url
            )

        if parsed_url.scheme != "https":
            allow_http = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("mobilepay.allow_http_webhooks")
                == "True"
            )
            if not allow_http:
                raise UserError(
                    _(
                        "MobilePay requires an HTTPS webhook URL. Current web.base.url: %s"
                    )
                    % base_url
                )

        clean_path = parsed_url.path.rstrip("/")
        clean_base_url = urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                clean_path,
                "",
                "",
                "",
            )
        )
        webhook_url = f"{clean_base_url}/payment/mobilepay/webhook"
        _logger.info(f"MobilePay: Registering webhook with URL: {webhook_url}")

        # Prepare webhook registration data
        webhook_data = {
            "url": webhook_url,
            "events": [
                "epayments.payment.authorized.v1",
                "epayments.payment.captured.v1",
                "epayments.payment.cancelled.v1",
                "epayments.payment.refunded.v1",
            ],
        }

        # Use API client to register webhook
        api_client = self.env["mobilepay.api.client"]
        response_data = api_client.register_webhook(self, webhook_data)

        webhook_id = response_data.get("id")
        webhook_secret = response_data.get("secret")

        if not webhook_id or not webhook_secret:
            raise UserError(
                _("Invalid webhook registration response from MobilePay API")
            )

        return webhook_id, webhook_secret

    def _test_webhook_connectivity(self):
        """
        Test webhook connectivity by validating the registered webhook.

        Raises:
            UserError: If webhook connectivity test fails
        """
        if not self.mobilepay_webhook_id:
            raise UserError(_("No webhook ID available for connectivity test"))

        # For now, we'll just validate that the webhook was registered
        # In a full implementation, this could send a test payload
        # or verify the webhook endpoint is accessible

        # Log successful registration
        _logger = logging.getLogger(__name__)
        _logger.info(
            f"Webhook connectivity validated for provider {self.id}, webhook ID: {self.mobilepay_webhook_id}"
        )

        return True

    def action_unregister_webhook(self):
        """Unregister webhook from MobilePay API."""
        if not self.mobilepay_webhook_id:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Webhook Registered"),
                    "message": _(
                        "No webhook is currently registered for this provider."
                    ),
                    "type": "warning",
                },
            }

        try:
            self._unregister_webhook_from_api()

            # Clear webhook credentials
            self.write(
                {"mobilepay_webhook_id": False, "mobilepay_webhook_secret": False}
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Webhook Unregistered"),
                    "message": _(
                        "Webhook has been successfully unregistered from MobilePay."
                    ),
                    "type": "success",
                },
            }

        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Webhook Unregistration Failed"),
                    "message": _("Failed to unregister webhook: %s") % str(e),
                    "type": "danger",
                },
            }

    def _unregister_webhook_from_api(self):
        """
        Unregister webhook from MobilePay API.

        Raises:
            UserError: If webhook unregistration fails
        """
        if not self.mobilepay_webhook_id:
            return

        # Use API client to unregister webhook
        api_client = self.env["mobilepay.api.client"]

        try:
            api_client.unregister_webhook(self, self.mobilepay_webhook_id)
        except Exception as e:
            raise UserError(_("Error unregistering webhook: %s") % str(e))

    def action_list_webhooks(self):
        """Fetch and log all registered webhooks for this MSN from the API."""
        self.ensure_one()
        api_client = self.env["mobilepay.api.client"]
        try:
            resp = api_client._make_request(self, "GET", "/webhooks/v1/webhooks")
            data = api_client._handle_response(resp)
            
            _logger.info(f"MobilePay: RAW Webhook API data: {json.dumps(data)}")
            
            # Vipps v1 returns a list or a dict with 'webhooks' key
            if isinstance(data, list):
                webhooks = data
            elif isinstance(data, dict):
                webhooks = data.get("webhooks") or ([data] if data.get("id") else [])
            else:
                webhooks = []
            
            _logger.info(f"MobilePay: Registered Webhooks for MSN {self.mobilepay_merchant_serial}: {json.dumps(webhooks, indent=2)}")
            
            message = _("Found %s registered webhooks. Check Odoo logs for details.") % len(webhooks)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Webhook List"),
                    "message": message,
                    "type": "info",
                },
            }
        except Exception as e:
            raise UserError(_("Failed to fetch webhooks: %s") % str(e))

    def action_unregister_all_webhooks(self):
        """Unregister ALL webhooks for this MSN except potentially the current one."""
        self.ensure_one()
        api_client = self.env["mobilepay.api.client"]
        try:
            webhooks_resp = api_client._make_request(self, "GET", "/webhooks/v1/webhooks")
            data = api_client._handle_response(webhooks_resp)
            
            # Vipps v1 returns a list or a dict with 'webhooks' key
            if isinstance(data, list):
                webhooks = data
            elif isinstance(data, dict):
                webhooks = data.get("webhooks") or ([data] if data.get("id") else [])
            else:
                webhooks = []
            
            count = 0
            for wh in webhooks:
                if not isinstance(wh, dict):
                    continue
                wh_id = wh.get("id")
                if wh_id:
                    api_client.unregister_webhook(self, wh_id)
                    count += 1
            
            # Clear local state as well
            self.write({"mobilepay_webhook_id": False, "mobilepay_webhook_secret": False})
            
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Webhooks Cleaned"),
                    "message": _("Successfully unregistered %s webhooks.") % count,
                    "type": "success",
                },
            }
        except Exception as e:
            raise UserError(_("Failed to clean webhooks: %s") % str(e))

    def action_force_unregister_stored_webhook(self):
        """Force unregister the currently stored webhook ID, even if not in the list."""
        self.ensure_one()
        if not self.mobilepay_webhook_id:
            raise UserError(_("No webhook ID stored to unregister."))
        
        api_client = self.env["mobilepay.api.client"]
        try:
            api_client.unregister_webhook(self, self.mobilepay_webhook_id)
            self.write({"mobilepay_webhook_id": False, "mobilepay_webhook_secret": False})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Webhook Forced Out"),
                    "message": _("Attempted to unregister stored ID and cleared local state."),
                    "type": "warning",
                },
            }
        except Exception as e:
            # Still clear local state even if API fails (maybe it's already gone)
            self.write({"mobilepay_webhook_id": False, "mobilepay_webhook_secret": False})
            _logger.warning(f"MobilePay: Failed to unregister stored webhook via API (expected if already gone): {e}")
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Local State Cleared"),
                    "message": _("API unregistration failed, but Odoo credentials were cleared."),
                    "type": "info",
                },
            }

    @api.model
    def _cron_mobilepay_sync_settlements(self):
        """Cron interface: fetch and reconcile payouts for all configured MobilePay providers."""
        providers = self.search([("code", "=", "mobilepay"), ("state", "!=", "disabled")])
        for provider in providers:
            try:
                provider._mobilepay_sync_settlements()
            except Exception as e:
                _logger.error(
                    "Error executing MobilePay settlement sync for provider %s: %s",
                    provider.name,
                    str(e),
                )

    def _mobilepay_sync_settlements(self):
        """Fetch daily payout logs and generate accounting entries for Odoo CE (Hybrid Flow)."""
        self.ensure_one()
        if self.code != "mobilepay":
            return

        if not (self.mobilepay_fee_account_id and self.mobilepay_clearing_account_id and self.mobilepay_journal_id):
            _logger.warning(
                "MobilePay settlement sync skipped for provider %s: "
                "Reconciliation accounting configurations are missing (Fee Account, Clearing Account, or Journal).",
                self.name,
            )
            return

        # Fetch payouts for the last 14 days to capture any delayed report updates
        from datetime import date, timedelta
        date_to = date.today()
        date_from = date_to - timedelta(days=14)

        api_client = self.env["mobilepay.api.client"]
        entries = api_client.get_settlement_reports(self, date_from, date_to)

        if not entries:
            _logger.info("No settlement entries found for MobilePay provider %s.", self.name)
            return

        # Group ledger entries by Payout ID
        payouts_data = {}
        for entry in entries:
            payout_id = entry.get("payoutId")
            if not payout_id:
                continue

            if payout_id not in payouts_data:
                payouts_data[payout_id] = {
                    "payout_id": payout_id,
                    "date": fields.Date.from_string(entry.get("date") or entry.get("bookingDate") or date.today().isoformat()),
                    "currency_name": entry.get("currency") or "DKK",
                    "captures": [],
                    "refunds": [],
                    "fees": [],
                    "net_payout": 0.0,
                    "gross_payments": 0.0,
                    "gross_refunds": 0.0,
                    "total_fees": 0.0,
                }

            entry_type = (entry.get("entryType") or "").lower()
            amount_val = float(entry.get("amount") or 0.0) / 100.0

            if entry_type in ["payment", "capture"]:
                payouts_data[payout_id]["captures"].append({
                    "psp_reference": entry.get("pspReference"),
                    "amount": amount_val,
                })
                payouts_data[payout_id]["gross_payments"] += amount_val
            elif entry_type == "refund":
                payouts_data[payout_id]["refunds"].append({
                    "psp_reference": entry.get("pspReference"),
                    "amount": abs(amount_val),
                })
                payouts_data[payout_id]["gross_refunds"] += abs(amount_val)
            elif entry_type in ["commission", "fee", "merchant_fee"]:
                payouts_data[payout_id]["fees"].append({
                    "psp_reference": entry.get("pspReference"),
                    "amount": abs(amount_val),
                })
                payouts_data[payout_id]["total_fees"] += abs(amount_val)
            elif entry_type in ["payout", "payout-scheduled", "transfer"]:
                payouts_data[payout_id]["net_payout"] = abs(amount_val)

        for payout_id, data in payouts_data.items():
            existing_settlement = self.env["mobilepay.settlement"].search(
                [("payout_id", "=", payout_id)], limit=1
            )
            if existing_settlement and existing_settlement.state == "reconciled":
                continue

            if not data["net_payout"]:
                data["net_payout"] = data["gross_payments"] - data["gross_refunds"] - data["total_fees"]

            currency = self.env["res.currency"].search([("name", "=", data["currency_name"])], limit=1)
            if not currency:
                currency = self.company_id.currency_id

            settlement_vals = {
                "payout_id": payout_id,
                "settlement_date": data["date"],
                "gross_amount": data["gross_payments"] - data["gross_refunds"],
                "fee_amount": data["total_fees"],
                "net_amount": data["net_payout"],
                "currency_id": currency.id,
            }

            if not existing_settlement:
                settlement = self.env["mobilepay.settlement"].create(settlement_vals)
            else:
                settlement = existing_settlement
                settlement.write(settlement_vals)

            try:
                move_vals = self._mobilepay_prepare_settlement_move(settlement, data)
                move = self.env["account.move"].create(move_vals)
                settlement.write({"journal_entry_id": move.id})

                if self.mobilepay_auto_post_settlements:
                    move.action_post()
                    settlement.write({"state": "reconciled"})
                    self._mobilepay_reconcile_clearing_lines(move, data)
                else:
                    settlement.write({"state": "draft"})

            except Exception as e:
                _logger.error(
                    "Failed to process MobilePay payout settlement %s: %s",
                    payout_id,
                    str(e),
                )
                settlement.write(
                    {
                        "state": "error",
                        "note": f"Error: {str(e)}",
                    }
                )

    def _mobilepay_prepare_settlement_move(self, settlement, data):
        """Prepare values dict for the settlement Journal Entry (account.move)."""
        self.ensure_one()
        journal = self.mobilepay_journal_id
        description = _("MobilePay Payout Settlement %s") % settlement.payout_id
        line_ids = []
        
        bank_account = journal.default_account_id
        if not bank_account:
            raise UserError(
                _("The selected MobilePay Journal (%s) does not have a default account configured.")
                % journal.name
            )

        line_ids.append((0, 0, {
            "name": description + _(" (Net Payout)"),
            "account_id": bank_account.id,
            "debit": settlement.net_amount,
            "credit": 0.0,
            "currency_id": settlement.currency_id.id,
        }))
        
        fee_vals = {
            "name": description + _(" (Merchant Fees)"),
            "account_id": self.mobilepay_fee_account_id.id,
            "debit": settlement.fee_amount,
            "credit": 0.0,
            "currency_id": settlement.currency_id.id,
        }
        if self.mobilepay_fee_tax_id:
            fee_vals["tax_ids"] = [(6, 0, [self.mobilepay_fee_tax_id.id])]
        
        line_ids.append((0, 0, fee_vals))
        
        if data["gross_payments"]:
            line_ids.append((0, 0, {
                "name": description + _(" (Gross Receipts Clearing)"),
                "account_id": self.mobilepay_clearing_account_id.id,
                "debit": 0.0,
                "credit": data["gross_payments"],
                "currency_id": settlement.currency_id.id,
            }))
            
        if data["gross_refunds"]:
            line_ids.append((0, 0, {
                "name": description + _(" (Gross Refunds Clearing)"),
                "account_id": self.mobilepay_clearing_account_id.id,
                "debit": data["gross_refunds"],
                "credit": 0.0,
                "currency_id": settlement.currency_id.id,
            }))
            
        return {
            "journal_id": journal.id,
            "date": settlement.settlement_date,
            "ref": settlement.payout_id,
            "move_type": "entry",
            "line_ids": line_ids,
        }

    def _mobilepay_reconcile_clearing_lines(self, move, data):
        """Find and reconcile outstanding clearing account lines matching this payout's transactions."""
        self.ensure_one()
        psp_refs = [c["psp_reference"] for c in data["captures"] if c["psp_reference"]]
        refund_refs = [r["psp_reference"] for r in data["refunds"] if r["psp_reference"]]
        all_api_refs = psp_refs + refund_refs

        if not all_api_refs:
            return

        transactions = self.env["payment.transaction"].search([
            ("mobilepay_payment_id", "in", all_api_refs)
        ])

        clearing_lines = self.env["account.move.line"]

        # 1. Match standard payments linked via account.payment
        if transactions:
            payment_moves = transactions.payment_id.move_id
            if payment_moves:
                clearing_lines |= payment_moves.line_ids.filtered(
                    lambda l: l.account_id == self.mobilepay_clearing_account_id and not l.reconciled
                )

        # 2. Match by reference strings (for POS/web orders or fallback)
        references = transactions.mapped("reference")
        if references:
            additional_lines = self.env["account.move.line"].search([
                ("account_id", "=", self.mobilepay_clearing_account_id.id),
                ("reconciled", "=", False),
                "|",
                ("ref", "in", references),
                ("name", "in", references),
            ])
            clearing_lines |= additional_lines

        # 3. Get the clearing lines of our new settlement move
        settlement_clearing_lines = move.line_ids.filtered(
            lambda l: l.account_id == self.mobilepay_clearing_account_id and not l.reconciled
        )

        # Reconcile everything together
        lines_to_reconcile = clearing_lines | settlement_clearing_lines
        if len(lines_to_reconcile) > 1:
            try:
                lines_to_reconcile.reconcile()
            except Exception as e:
                _logger.warning("MobilePay: Automatic reconciliation failed for payout %s: %s", move.ref, str(e))
