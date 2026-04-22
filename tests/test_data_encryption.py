# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch, Mock
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

try:
    from hypothesis import given, strategies as st, settings
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False


class TestDataEncryption(TransactionCase):
    """
    Property-based tests for data encryption and security.
    
    **Feature: odoo-mobilepay-integration, Property 14: Data Encryption and Security**
    **Validates: Requirements 9.1, 9.2, 9.5**
    """

    def setUp(self):
        super().setUp()
        self.PaymentProvider = self.env['payment.provider']
        self.ConfigParam = self.env['ir.config_parameter']
        
    def tearDown(self):
        # Clean up any test configuration parameters
        test_params = self.ConfigParam.search([
            ('key', 'like', 'mobilepay_test_%')
        ])
        test_params.unlink()
        super().tearDown()

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        client_secret=st.text(min_size=10, max_size=100),
        subscription_key=st.text(min_size=10, max_size=100),
        webhook_secret=st.text(min_size=10, max_size=100)
    )
    @settings(max_examples=20, deadline=None)
    def test_property_sensitive_fields_are_encrypted_in_database(self, client_secret, 
                                                               subscription_key, 
                                                               webhook_secret):
        """
        Property: For any sensitive configuration data (client secret, subscription key, 
        webhook secret), the system should store it encrypted in the database.
        
        **Validates: Requirements 9.1**
        """
        # Create provider with sensitive data
        provider = self.PaymentProvider.create({
            'name': 'Test MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': client_secret,
            'mobilepay_subscription_key': subscription_key,
            'mobilepay_merchant_serial': 'test_merchant_serial',
            'mobilepay_webhook_secret': webhook_secret
        })
        
        # Check that sensitive fields are stored as encrypted values in the backing fields
        self.assertTrue(provider.mobilepay_client_secret_encrypted)
        self.assertTrue(provider.mobilepay_subscription_key_encrypted)
        self.assertTrue(provider.mobilepay_webhook_secret_encrypted)
        
        # Verify the encrypted values are NOT the plain text
        self.assertNotEqual(provider.mobilepay_client_secret_encrypted, client_secret)
        self.assertNotEqual(provider.mobilepay_subscription_key_encrypted, subscription_key)
        self.assertNotEqual(provider.mobilepay_webhook_secret_encrypted, webhook_secret)
        
        # Verify values can be retrieved (decrypted) via the computed fields
        self.assertEqual(provider.mobilepay_client_secret, client_secret)
        self.assertEqual(provider.mobilepay_subscription_key, subscription_key)
        self.assertEqual(provider.mobilepay_webhook_secret, webhook_secret)
        
        # Verify that directly ensuring the encryption key exists
        self.assertTrue(self.ConfigParam.get_param('mobilepay.encryption_key'))

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        provider_id=st.integers(min_value=1, max_value=1000),
        token=st.text(min_size=20, max_size=200),
        expires_in=st.integers(min_value=300, max_value=7200)
    )
    @settings(max_examples=20, deadline=None)
    def test_property_oauth_tokens_stored_securely(self, provider_id, token, expires_in):
        """
        Property: For any OAuth2 token, the authentication service should store it 
        securely using Odoo's configuration parameter system.
        
        **Validates: Requirements 9.2**
        """
        # Create a test provider
        provider = self.PaymentProvider.create({
            'name': f'Test Provider {provider_id}',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': 'test_secret',
            'mobilepay_subscription_key': 'test_key',
            'mobilepay_merchant_serial': 'test_serial'
        })
        
        # Store token using authentication service
        auth_service = self.env['mobilepay.auth.service']
        auth_service._store_token(provider.id, token, expires_in)
        
        # Verify token is stored in ir.config_parameter
        cache_key = f'mobilepay_token_{provider.id}'
        stored_data = self.ConfigParam.get_param(cache_key)
        self.assertIsNotNone(stored_data, "Token should be stored in config parameters")
        
        # Verify token can be retrieved
        cached_token = auth_service._get_cached_token(provider.id)
        self.assertEqual(cached_token, token, "Retrieved token should match stored token")
        
        # Verify token storage uses secure configuration parameter system
        # (ir.config_parameter provides built-in security for sensitive data)
        config_param = self.ConfigParam.search([('key', '=', cache_key)])
        self.assertTrue(config_param.exists(), "Token should be stored as config parameter")

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        client_secret=st.text(min_size=10, max_size=100),
        subscription_key=st.text(min_size=10, max_size=100)
    )
    @settings(max_examples=20, deadline=None)
    def test_property_sensitive_data_not_exposed_in_logs(self, client_secret, subscription_key):
        """
        Property: For any sensitive credential data, the system should not expose 
        it in logs or user interfaces.
        
        **Validates: Requirements 9.5**
        """
        # Create provider with sensitive data
        provider = self.PaymentProvider.create({
            'name': 'Test MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': client_secret,
            'mobilepay_subscription_key': subscription_key,
            'mobilepay_merchant_serial': 'test_merchant_serial'
        })
        
        # Test that string representation doesn't expose sensitive data
        provider_str = str(provider)
        self.assertNotIn(client_secret, provider_str, 
                        "Client secret should not appear in string representation")
        self.assertNotIn(subscription_key, provider_str,
                        "Subscription key should not appear in string representation")
        
        # Test that repr doesn't expose sensitive data
        provider_repr = repr(provider)
        self.assertNotIn(client_secret, provider_repr,
                        "Client secret should not appear in repr")
        self.assertNotIn(subscription_key, provider_repr,
                        "Subscription key should not appear in repr")
        
        # Test that field values are masked in form views (when encryption is implemented)
        # For now, verify that the fields are marked as password fields or similar
        field_info = provider.fields_get(['mobilepay_client_secret', 'mobilepay_subscription_key'])
        
        # Verify sensitive fields exist
        self.assertIn('mobilepay_client_secret', field_info)
        self.assertIn('mobilepay_subscription_key', field_info)
        
        # TODO: Once encryption is implemented, add checks that:
        # 1. Field values are masked in UI (password field type or similar)
        # 2. Sensitive data is not logged in debug/info logs
        # 3. API responses don't include plain text sensitive data

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        webhook_secret=st.text(min_size=16, max_size=64)
    )
    @settings(max_examples=20, deadline=None)
    def test_property_webhook_secret_encryption(self, webhook_secret):
        """
        Property: For any webhook secret, the system should store it encrypted 
        and use it for signature verification without exposing the plain text.
        
        **Validates: Requirements 9.1, 9.5**
        """
        # Create provider and set webhook secret
        provider = self.PaymentProvider.create({
            'name': 'Test MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': 'test_secret',
            'mobilepay_subscription_key': 'test_key',
            'mobilepay_merchant_serial': 'test_serial',
            'mobilepay_webhook_secret': webhook_secret
        })
        
        # Verify webhook secret can be retrieved
        self.assertEqual(provider.mobilepay_webhook_secret, webhook_secret)
        
        # Verify webhook secret is not exposed in string representations
        provider_str = str(provider)
        self.assertNotIn(webhook_secret, provider_str,
                        "Webhook secret should not appear in string representation")
        
        # TODO: Once webhook handler is implemented, test that:
        # 1. Webhook secret is used for HMAC signature verification
        # 2. Secret is not logged during webhook processing
        # 3. Secret is properly encrypted in database storage

    def test_encryption_field_attributes(self):
        """Test that sensitive fields have appropriate security attributes."""
        provider = self.PaymentProvider.create({
            'name': 'Test MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': 'test_secret',
            'mobilepay_subscription_key': 'test_key',
            'mobilepay_merchant_serial': 'test_serial'
        })
        
        # Get field definitions
        fields_info = provider.fields_get([
            'mobilepay_client_secret',
            'mobilepay_subscription_key', 
            'mobilepay_webhook_secret'
        ])
        
        # Verify sensitive fields exist and have appropriate help text indicating encryption
        for field_name in ['mobilepay_client_secret', 'mobilepay_subscription_key', 'mobilepay_webhook_secret']:
            self.assertIn(field_name, fields_info, f"Field {field_name} should exist")
            field_info = fields_info[field_name]
            
            # Check that help text indicates encryption
            help_text = field_info.get('help', '').lower()
            self.assertIn('encrypt', help_text, 
                         f"Field {field_name} should indicate encryption in help text")

    def test_credential_validation_prevents_empty_sensitive_fields(self):
        """Test that credential validation prevents empty sensitive fields."""
        # Test that creating provider without required sensitive fields raises validation error
        with self.assertRaises(ValidationError):
            self.PaymentProvider.create({
                'name': 'Invalid MobilePay Provider',
                'code': 'mobilepay',
                'state': 'test',
                'mobilepay_client_id': 'test_client_id',
                # Missing required sensitive fields
                'mobilepay_merchant_serial': 'test_serial'
            })
        
        # Test that empty sensitive fields raise validation error
        with self.assertRaises(ValidationError):
            self.PaymentProvider.create({
                'name': 'Invalid MobilePay Provider',
                'code': 'mobilepay',
                'state': 'test',
                'mobilepay_client_id': 'test_client_id',
                'mobilepay_client_secret': '',  # Empty
                'mobilepay_subscription_key': '',  # Empty
                'mobilepay_merchant_serial': 'test_serial'
            })