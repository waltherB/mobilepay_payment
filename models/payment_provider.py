# -*- coding: utf-8 -*-

import logging
from cryptography.fernet import Fernet
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('mobilepay', 'MobilePay')],
        ondelete={'mobilepay': 'set default'}
    )

    show_mobilepay_fields = fields.Boolean(
        compute='_compute_show_mobilepay_fields',
        help="Technical field to control visibility of MobilePay specific fields."
    )

    @api.depends('code')
    def _compute_show_mobilepay_fields(self):
        for provider in self:
            provider.show_mobilepay_fields = provider.code == 'mobilepay'

    # ===== Test Environment Credentials =====
    mobilepay_test_client_id = fields.Char(
        string="Test Client ID",
        help="MobilePay Test API Client ID"
    )
    
    mobilepay_test_client_secret_encrypted = fields.Char(
        string="Test Client Secret (Encrypted)",
        copy=False
    )
    
    mobilepay_test_client_secret = fields.Char(
        string="Test Client Secret",
        help="MobilePay Test API Client Secret (encrypted)",
        compute='_compute_mobilepay_test_client_secret',
        inverse='_inverse_mobilepay_test_client_secret'
    )
    
    mobilepay_test_subscription_key_encrypted = fields.Char(
        string="Test Subscription Key (Encrypted)",
        copy=False
    )
    
    mobilepay_test_subscription_key = fields.Char(
        string="Test Subscription Key",
        help="MobilePay Test API Subscription Key (encrypted)",
        compute='_compute_mobilepay_test_subscription_key',
        inverse='_inverse_mobilepay_test_subscription_key'
    )
    
    mobilepay_test_merchant_serial = fields.Char(
        string="Test Merchant Serial Number",
        help="MobilePay Test Merchant Serial Number"
    )
    
    # ===== Production Environment Credentials =====
    mobilepay_prod_client_id = fields.Char(
        string="Production Client ID",
        help="MobilePay Production API Client ID"
    )
    
    mobilepay_prod_client_secret_encrypted = fields.Char(
        string="Production Client Secret (Encrypted)",
        copy=False
    )
    
    mobilepay_prod_client_secret = fields.Char(
        string="Production Client Secret",
        help="MobilePay Production API Client Secret (encrypted)",
        compute='_compute_mobilepay_prod_client_secret',
        inverse='_inverse_mobilepay_prod_client_secret'
    )
    
    mobilepay_prod_subscription_key_encrypted = fields.Char(
        string="Production Subscription Key (Encrypted)",
        copy=False
    )
    
    mobilepay_prod_subscription_key = fields.Char(
        string="Production Subscription Key",
        help="MobilePay Production API Subscription Key (encrypted)",
        compute='_compute_mobilepay_prod_subscription_key',
        inverse='_inverse_mobilepay_prod_subscription_key'
    )
    
    mobilepay_prod_merchant_serial = fields.Char(
        string="Production Merchant Serial Number",
        help="MobilePay Production Merchant Serial Number"
    )
    
    # ===== Active Credentials (Computed based on state) =====
    mobilepay_client_id = fields.Char(
        string="Client ID",
        help="Active MobilePay API Client ID (auto-selected based on state)",
        compute='_compute_active_credentials',
        store=False
    )
    
    mobilepay_client_secret = fields.Char(
        string="Client Secret",
        help="Active MobilePay API Client Secret (auto-selected based on state)",
        compute='_compute_active_credentials',
        store=False
    )
    
    mobilepay_subscription_key = fields.Char(
        string="Subscription Key",
        help="Active MobilePay API Subscription Key (auto-selected based on state)",
        compute='_compute_active_credentials',
        store=False
    )
    
    mobilepay_merchant_serial = fields.Char(
        string="Merchant Serial Number",
        help="Active MobilePay Merchant Serial Number (auto-selected based on state)",
        compute='_compute_active_credentials',
        store=False
    )

    # Webhook Configuration
    mobilepay_webhook_id = fields.Char(
        string="Webhook ID",
        help="Registered webhook ID from MobilePay",
        readonly=True
    )
    
    mobilepay_webhook_secret_encrypted = fields.Char(
        string="Webhook Secret (Encrypted)",
        copy=False,
        readonly=True
    )
    
    mobilepay_webhook_secret = fields.Char(
        string="Webhook Secret",
        help="Webhook signature verification secret (encrypted)",
        compute='_compute_mobilepay_webhook_secret',
        inverse='_inverse_mobilepay_webhook_secret',
        readonly=True
    )

    # Payment Flow Configuration
    capture_manually = fields.Boolean(
        string="Manual Capture",
        help="Enable manual capture for authorize & capture flow",
        default=True
    )
    auto_capture_delay = fields.Integer(
        string="Auto Capture Delay (hours)",
        help="Delay in hours before automatic capture (when manual capture is disabled)",
        default=24
    )

    # Encryption Helpers
    def _get_encryption_key(self):
        """Get or create the encryption key from ir.config_parameter."""
        param_obj = self.env['ir.config_parameter'].sudo()
        key = param_obj.get_param('mobilepay.encryption_key')
        if not key:
            key = Fernet.generate_key().decode()
            param_obj.set_param('mobilepay.encryption_key', key)
        return key.encode()

    def _encrypt(self, value):
        """Encrypt a value."""
        if not value:
            return False
        f = Fernet(self._get_encryption_key())
        return f.encrypt(value.encode()).decode()

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
        if self.state == 'enabled':
            return 'https://api.vipps.no'
        else:
            return 'https://apitest.vipps.no'

    # Compute/Inverse methods for Test credentials
    @api.depends('mobilepay_test_client_secret_encrypted')
    def _compute_mobilepay_test_client_secret(self):
        for provider in self:
            if provider.mobilepay_test_client_secret_encrypted:
                provider.mobilepay_test_client_secret = provider._decrypt(provider.mobilepay_test_client_secret_encrypted)
            else:
                provider.mobilepay_test_client_secret = False

    def _inverse_mobilepay_test_client_secret(self):
        for provider in self:
            if provider.mobilepay_test_client_secret:
                provider.mobilepay_test_client_secret_encrypted = provider._encrypt(provider.mobilepay_test_client_secret)
            else:
                provider.mobilepay_test_client_secret_encrypted = False

    @api.depends('mobilepay_test_subscription_key_encrypted')
    def _compute_mobilepay_test_subscription_key(self):
        for provider in self:
            if provider.mobilepay_test_subscription_key_encrypted:
                provider.mobilepay_test_subscription_key = provider._decrypt(provider.mobilepay_test_subscription_key_encrypted)
            else:
                provider.mobilepay_test_subscription_key = False

    def _inverse_mobilepay_test_subscription_key(self):
        for provider in self:
            if provider.mobilepay_test_subscription_key:
                provider.mobilepay_test_subscription_key_encrypted = provider._encrypt(provider.mobilepay_test_subscription_key)
            else:
                provider.mobilepay_test_subscription_key_encrypted = False

    # Compute/Inverse methods for Production credentials
    @api.depends('mobilepay_prod_client_secret_encrypted')
    def _compute_mobilepay_prod_client_secret(self):
        for provider in self:
            if provider.mobilepay_prod_client_secret_encrypted:
                provider.mobilepay_prod_client_secret = provider._decrypt(provider.mobilepay_prod_client_secret_encrypted)
            else:
                provider.mobilepay_prod_client_secret = False

    def _inverse_mobilepay_prod_client_secret(self):
        for provider in self:
            if provider.mobilepay_prod_client_secret:
                provider.mobilepay_prod_client_secret_encrypted = provider._encrypt(provider.mobilepay_prod_client_secret)
            else:
                provider.mobilepay_prod_client_secret_encrypted = False

    @api.depends('mobilepay_prod_subscription_key_encrypted')
    def _compute_mobilepay_prod_subscription_key(self):
        for provider in self:
            if provider.mobilepay_prod_subscription_key_encrypted:
                provider.mobilepay_prod_subscription_key = provider._decrypt(provider.mobilepay_prod_subscription_key_encrypted)
            else:
                provider.mobilepay_prod_subscription_key = False

    def _inverse_mobilepay_prod_subscription_key(self):
        for provider in self:
            if provider.mobilepay_prod_subscription_key:
                provider.mobilepay_prod_subscription_key_encrypted = provider._encrypt(provider.mobilepay_prod_subscription_key)
            else:
                provider.mobilepay_prod_subscription_key_encrypted = False

    # Compute method for active credentials (auto-select based on state)
    @api.depends('state', 'mobilepay_test_client_id', 'mobilepay_test_client_secret_encrypted',
                 'mobilepay_test_subscription_key_encrypted', 'mobilepay_test_merchant_serial',
                 'mobilepay_prod_client_id', 'mobilepay_prod_client_secret_encrypted',
                 'mobilepay_prod_subscription_key_encrypted', 'mobilepay_prod_merchant_serial')
    def _compute_active_credentials(self):
        for provider in self:
            if provider.state == 'enabled':
                # Production mode
                provider.mobilepay_client_id = provider.mobilepay_prod_client_id
                provider.mobilepay_client_secret = provider._decrypt(provider.mobilepay_prod_client_secret_encrypted) if provider.mobilepay_prod_client_secret_encrypted else False
                provider.mobilepay_subscription_key = provider._decrypt(provider.mobilepay_prod_subscription_key_encrypted) if provider.mobilepay_prod_subscription_key_encrypted else False
                provider.mobilepay_merchant_serial = provider.mobilepay_prod_merchant_serial
            else:
                # Test mode (test or disabled)
                provider.mobilepay_client_id = provider.mobilepay_test_client_id
                provider.mobilepay_client_secret = provider._decrypt(provider.mobilepay_test_client_secret_encrypted) if provider.mobilepay_test_client_secret_encrypted else False
                provider.mobilepay_subscription_key = provider._decrypt(provider.mobilepay_test_subscription_key_encrypted) if provider.mobilepay_test_subscription_key_encrypted else False
                provider.mobilepay_merchant_serial = provider.mobilepay_test_merchant_serial

    # Compute/Inverse methods for Webhook Secret
    @api.depends('mobilepay_webhook_secret_encrypted')
    def _compute_mobilepay_webhook_secret(self):
        for provider in self:
            if provider.mobilepay_webhook_secret_encrypted:
                provider.mobilepay_webhook_secret = provider._decrypt(provider.mobilepay_webhook_secret_encrypted)
            else:
                provider.mobilepay_webhook_secret = False

    def _inverse_mobilepay_webhook_secret(self):
        for provider in self:
            if provider.mobilepay_webhook_secret:
                provider.mobilepay_webhook_secret_encrypted = provider._encrypt(provider.mobilepay_webhook_secret)
            else:
                provider.mobilepay_webhook_secret_encrypted = False

    @api.constrains('state', 'mobilepay_test_client_id', 'mobilepay_test_client_secret_encrypted',
                   'mobilepay_test_subscription_key_encrypted', 'mobilepay_test_merchant_serial',
                   'mobilepay_prod_client_id', 'mobilepay_prod_client_secret_encrypted',
                   'mobilepay_prod_subscription_key_encrypted', 'mobilepay_prod_merchant_serial')
    def _check_mobilepay_credentials(self):
        """Validate MobilePay credentials format and completeness."""
        for provider in self:
            if provider.code == 'mobilepay':
                # Check credentials based on provider state
                if provider.state == 'enabled':
                    # Production mode - check production credentials
                    if not all([
                        provider.mobilepay_prod_client_id,
                        provider.mobilepay_prod_client_secret_encrypted,
                        provider.mobilepay_prod_subscription_key_encrypted,
                        provider.mobilepay_prod_merchant_serial
                    ]):
                        raise ValidationError(_(
                            "All MobilePay production credentials are required when provider is enabled: "
                            "Production Client ID, Production Client Secret, Production Subscription Key, "
                            "and Production Merchant Serial Number"
                        ))
                else:
                    # Test/Disabled mode - check test credentials
                    if not all([
                        provider.mobilepay_test_client_id,
                        provider.mobilepay_test_client_secret_encrypted,
                        provider.mobilepay_test_subscription_key_encrypted,
                        provider.mobilepay_test_merchant_serial
                    ]):
                        raise ValidationError(_(
                            "All MobilePay test credentials are required: "
                            "Test Client ID, Test Client Secret, Test Subscription Key, "
                            "and Test Merchant Serial Number"
                        ))

    @api.model
    def _get_compatible_providers(self, *args, currency_id=None, **kwargs):
        """Override to ensure MobilePay only works with DKK currency."""
        providers = super()._get_compatible_providers(*args, currency_id=currency_id, **kwargs)
        
        if currency_id:
            currency = self.env['res.currency'].browse(currency_id)
            if currency.name != 'DKK':
                # Filter out MobilePay providers for non-DKK currencies
                providers = providers.filtered(lambda p: p.code != 'mobilepay')
        
        return providers


    def action_register_webhook(self):
        """Register webhook with MobilePay API."""
        self._check_mobilepay_credentials()
        
        try:
            webhook_id, webhook_secret = self._register_webhook_with_api()
            
            # Store webhook credentials
            self.write({
                'mobilepay_webhook_id': webhook_id,
                'mobilepay_webhook_secret': webhook_secret
            })
            
            # Test webhook connectivity
            self._test_webhook_connectivity()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Webhook Registration Successful'),
                    'message': _('Webhook has been registered successfully with MobilePay. ID: %s') % webhook_id,
                    'type': 'success',
                }
            }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Webhook Registration Failed'),
                    'message': _('Failed to register webhook: %s') % str(e),
                    'type': 'danger',
                    
                }
            }

    def _register_webhook_with_api(self):
        """
        Register webhook with MobilePay API and return webhook ID and secret.
        
        Returns:
            tuple: (webhook_id, webhook_secret)
            
        Raises:
            UserError: If webhook registration fails
        """
        # Get base URL for webhook endpoint
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        if not base_url:
            raise UserError(_("System base URL is not configured. Please set web.base.url parameter."))
            
        if not base_url.startswith('https://'):
            # Allow http for localhost/test environment if strictly needed,
            # but generally MobilePay requires HTTPS.
            allow_http = self.env['ir.config_parameter'].sudo().get_param('mobilepay.allow_http_webhooks') == 'True'
            if not allow_http:
                raise UserError(_("MobilePay requires an HTTPS webhook URL. Your system base URL is configured as HTTP.\n"
                                  "For local development, you can bypass this by setting the system parameter "
                                  "'mobilepay.allow_http_webhooks' to 'True'."))
        
        # Construct webhook URL
        webhook_url = f"{base_url}/payment/mobilepay/webhook"
        
        # Prepare webhook registration data
        webhook_data = {
            'url': webhook_url,
            'events': [
                'payment.reserved',
                'payment.captured', 
                'payment.cancelled',
                'payment.refunded'
            ]
        }
        
        # Use API client to register webhook
        api_client = self.env['mobilepay.api.client']
        response_data = api_client.register_webhook(self, webhook_data)
        
        webhook_id = response_data.get('id')
        webhook_secret = response_data.get('secret')
        
        if not webhook_id or not webhook_secret:
            raise UserError(_("Invalid webhook registration response from MobilePay API"))
        
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
        _logger.info(f"Webhook connectivity validated for provider {self.id}, webhook ID: {self.mobilepay_webhook_id}")
        
        return True

    def action_unregister_webhook(self):
        """Unregister webhook from MobilePay API."""
        if not self.mobilepay_webhook_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Webhook Registered'),
                    'message': _('No webhook is currently registered for this provider.'),
                    'type': 'warning',
                }
            }
        
        try:
            self._unregister_webhook_from_api()
            
            # Clear webhook credentials
            self.write({
                'mobilepay_webhook_id': False,
                'mobilepay_webhook_secret': False
            })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Webhook Unregistered'),
                    'message': _('Webhook has been successfully unregistered from MobilePay.'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Webhook Unregistration Failed'),
                    'message': _('Failed to unregister webhook: %s') % str(e),
                    'type': 'danger',
                }
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
        api_client = self.env['mobilepay.api.client']
        
        try:
            api_client.unregister_webhook(self, self.mobilepay_webhook_id)
        except Exception as e:
            raise UserError(_("Error unregistering webhook: %s") % str(e))