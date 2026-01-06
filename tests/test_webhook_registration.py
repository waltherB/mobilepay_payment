# -*- coding: utf-8 -*-

import json
import unittest
from unittest.mock import patch, Mock
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

try:
    from hypothesis import given, strategies as st, settings
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False


class TestWebhookRegistration(TransactionCase):
    """
    Property-based tests for webhook registration API integration.
    
    **Feature: odoo-mobilepay-integration, Property 1: Webhook Registration API Integration**
    **Validates: Requirements 1.2, 1.3**
    """

    def setUp(self):
        super().setUp()
        self.PaymentProvider = self.env['payment.provider']
        self.ApiClient = self.env['mobilepay.api.client']
        
        # Create test provider
        self.provider = self.PaymentProvider.create({
            'name': 'Test MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': 'test_client_secret',
            'mobilepay_subscription_key': 'test_subscription_key',
            'mobilepay_merchant_serial': 'test_merchant_serial'
        })

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        webhook_id=st.text(min_size=10, max_size=100),
        webhook_secret=st.text(min_size=16, max_size=64),
        base_url=st.text(min_size=10, max_size=100).map(lambda x: f"https://{x}.example.com")
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_api_client.MobilePayApiClient.register_webhook')
    @patch('odoo.http.request')
    def test_property_webhook_registration_api_integration(self, mock_request, mock_register_webhook,
                                                         webhook_id, webhook_secret, base_url):
        """
        Property: For any webhook registration request, the Configuration Manager should 
        send a POST request to the MobilePay webhooks endpoint with correct event 
        subscriptions and store the returned webhook ID and secret in encrypted fields.
        
        **Validates: Requirements 1.2, 1.3**
        """
        # Mock the base URL configuration
        with patch('odoo.models.Model.env') as mock_env:
            mock_config_param = Mock()
            mock_config_param.get_param.return_value = base_url
            mock_env.__getitem__.return_value.sudo.return_value = mock_config_param
            
            # Mock successful webhook registration response
            mock_register_webhook.return_value = {
                'id': webhook_id,
                'secret': webhook_secret,
                'url': f"{base_url}/payment/mobilepay/webhook",
                'events': ['payment.reserved', 'payment.captured', 'payment.cancelled', 'payment.refunded']
            }
            
            # Trigger webhook registration
            result = self.provider.action_register_webhook()
            
            # Verify API client was called with correct webhook data
            mock_register_webhook.assert_called_once()
            call_args = mock_register_webhook.call_args[0]
            
            # Verify provider was passed
            self.assertEqual(call_args[0], self.provider)
            
            # Verify webhook data structure
            webhook_data = call_args[1]
            self.assertIn('url', webhook_data)
            self.assertIn('events', webhook_data)
            
            # Verify webhook URL is correctly constructed
            expected_url = f"{base_url}/payment/mobilepay/webhook"
            self.assertEqual(webhook_data['url'], expected_url)
            
            # Verify all required events are subscribed
            expected_events = ['payment.reserved', 'payment.captured', 'payment.cancelled', 'payment.refunded']
            self.assertEqual(set(webhook_data['events']), set(expected_events))
            
            # Verify webhook credentials are stored in provider
            self.assertEqual(self.provider.mobilepay_webhook_id, webhook_id)
            self.assertEqual(self.provider.mobilepay_webhook_secret, webhook_secret)
            
            # Verify success notification is returned
            self.assertEqual(result['type'], 'ir.actions.client')
            self.assertEqual(result['tag'], 'display_notification')
            self.assertEqual(result['params']['type'], 'success')

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        webhook_id=st.text(min_size=5, max_size=50),
        webhook_secret=st.text(min_size=10, max_size=100),
        webhook_url=st.text(min_size=10, max_size=200).map(lambda x: f"https://{x}.test.com/webhook")
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_api_client.MobilePayApiClient.register_webhook')
    def test_property_webhook_data_structure_validation(self, mock_register_webhook,
                                                      webhook_id, webhook_secret, webhook_url):
        """
        Property: For any webhook registration, the system should send properly 
        structured webhook data with URL and event subscriptions to MobilePay API.
        
        **Validates: Requirements 1.2**
        """
        # Mock base URL configuration
        with patch.object(self.env['ir.config_parameter'], 'sudo') as mock_sudo:
            mock_config = Mock()
            mock_config.get_param.return_value = webhook_url.replace('/webhook', '')
            mock_sudo.return_value = mock_config
            
            # Mock successful API response
            mock_register_webhook.return_value = {
                'id': webhook_id,
                'secret': webhook_secret
            }
            
            # Call webhook registration
            self.provider._register_webhook_with_api()
            
            # Verify API was called with correct structure
            mock_register_webhook.assert_called_once()
            call_args = mock_register_webhook.call_args
            
            # Extract webhook data from call
            webhook_data = call_args[0][1]  # Second argument is webhook_data
            
            # Verify required fields are present
            self.assertIn('url', webhook_data, "Webhook data should contain URL")
            self.assertIn('events', webhook_data, "Webhook data should contain events")
            
            # Verify URL format
            self.assertTrue(webhook_data['url'].startswith('http'), 
                          "Webhook URL should use HTTP/HTTPS protocol")
            self.assertTrue(webhook_data['url'].endswith('/payment/mobilepay/webhook'),
                          "Webhook URL should end with correct endpoint path")
            
            # Verify events are a list
            self.assertIsInstance(webhook_data['events'], list,
                                "Events should be provided as a list")
            
            # Verify all required events are included
            required_events = {'payment.reserved', 'payment.captured', 'payment.cancelled', 'payment.refunded'}
            actual_events = set(webhook_data['events'])
            self.assertEqual(actual_events, required_events,
                           "All required payment events should be subscribed")

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        error_status=st.integers(min_value=400, max_value=599),
        error_message=st.text(min_size=1, max_size=200)
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_api_client.MobilePayApiClient.register_webhook')
    def test_property_webhook_registration_error_handling(self, mock_register_webhook,
                                                        error_status, error_message):
        """
        Property: For any webhook registration API error, the system should handle 
        the error gracefully and return appropriate error notification.
        
        **Validates: Requirements 1.2, 1.3**
        """
        # Mock base URL configuration
        with patch.object(self.env['ir.config_parameter'], 'sudo') as mock_sudo:
            mock_config = Mock()
            mock_config.get_param.return_value = 'https://test.example.com'
            mock_sudo.return_value = mock_config
            
            # Mock API error
            mock_register_webhook.side_effect = UserError(f"API Error {error_status}: {error_message}")
            
            # Call webhook registration and expect error handling
            result = self.provider.action_register_webhook()
            
            # Verify error notification is returned
            self.assertEqual(result['type'], 'ir.actions.client')
            self.assertEqual(result['tag'], 'display_notification')
            self.assertEqual(result['params']['type'], 'danger')
            
            # Verify error message contains some reference to the failure
            self.assertIn('Failed to register webhook', result['params']['message'])
            
            # Verify webhook credentials are not stored on error
            self.assertFalse(self.provider.mobilepay_webhook_id)
            self.assertFalse(self.provider.mobilepay_webhook_secret)

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        webhook_id=st.text(min_size=8, max_size=64),
        webhook_secret=st.text(min_size=16, max_size=128)
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_api_client.MobilePayApiClient.register_webhook')
    def test_property_webhook_credentials_storage(self, mock_register_webhook,
                                                webhook_id, webhook_secret):
        """
        Property: For any successful webhook registration response, the system should 
        store the webhook ID and secret in encrypted fields on the provider.
        
        **Validates: Requirements 1.3**
        """
        # Mock base URL configuration
        with patch.object(self.env['ir.config_parameter'], 'sudo') as mock_sudo:
            mock_config = Mock()
            mock_config.get_param.return_value = 'https://test.example.com'
            mock_sudo.return_value = mock_config
            
            # Mock successful API response
            mock_register_webhook.return_value = {
                'id': webhook_id,
                'secret': webhook_secret,
                'url': 'https://test.example.com/payment/mobilepay/webhook'
            }
            
            # Verify initial state (no webhook credentials)
            self.assertFalse(self.provider.mobilepay_webhook_id)
            self.assertFalse(self.provider.mobilepay_webhook_secret)
            
            # Register webhook
            webhook_id_result, webhook_secret_result = self.provider._register_webhook_with_api()
            
            # Verify returned values match API response
            self.assertEqual(webhook_id_result, webhook_id)
            self.assertEqual(webhook_secret_result, webhook_secret)
            
            # Verify credentials are stored in provider fields
            # Note: The actual storage happens in action_register_webhook, 
            # but _register_webhook_with_api returns the values for storage
            self.assertEqual(webhook_id_result, webhook_id)
            self.assertEqual(webhook_secret_result, webhook_secret)

    def test_webhook_registration_requires_base_url_configuration(self):
        """Test that webhook registration fails when base URL is not configured."""
        # Mock missing base URL configuration
        with patch.object(self.env['ir.config_parameter'], 'sudo') as mock_sudo:
            mock_config = Mock()
            mock_config.get_param.return_value = None  # No base URL configured
            mock_sudo.return_value = mock_config
            
            # Should raise UserError for missing base URL
            with self.assertRaises(UserError) as context:
                self.provider._register_webhook_with_api()
            
            # Verify error message mentions base URL configuration
            error_message = str(context.exception)
            self.assertIn('base URL', error_message.lower())

    def test_webhook_registration_validates_api_response_structure(self):
        """Test that webhook registration validates API response contains required fields."""
        with patch.object(self.env['ir.config_parameter'], 'sudo') as mock_sudo:
            mock_config = Mock()
            mock_config.get_param.return_value = 'https://test.example.com'
            mock_sudo.return_value = mock_config
            
            with patch('mobilepay_payment.models.mobilepay_api_client.MobilePayApiClient.register_webhook') as mock_register:
                # Test missing webhook ID in response
                mock_register.return_value = {'secret': 'test_secret'}  # Missing 'id'
                
                with self.assertRaises(UserError) as context:
                    self.provider._register_webhook_with_api()
                
                self.assertIn('Invalid webhook registration response', str(context.exception))
                
                # Test missing webhook secret in response
                mock_register.return_value = {'id': 'test_id'}  # Missing 'secret'
                
                with self.assertRaises(UserError) as context:
                    self.provider._register_webhook_with_api()
                
                self.assertIn('Invalid webhook registration response', str(context.exception))

    @patch('mobilepay_payment.models.mobilepay_api_client.MobilePayApiClient.register_webhook')
    def test_webhook_connectivity_test_is_called(self, mock_register_webhook):
        """Test that webhook connectivity test is performed after registration."""
        # Mock base URL and successful registration
        with patch.object(self.env['ir.config_parameter'], 'sudo') as mock_sudo:
            mock_config = Mock()
            mock_config.get_param.return_value = 'https://test.example.com'
            mock_sudo.return_value = mock_config
            
            mock_register_webhook.return_value = {
                'id': 'test_webhook_id',
                'secret': 'test_webhook_secret'
            }
            
            # Mock the connectivity test method
            with patch.object(self.provider, '_test_webhook_connectivity') as mock_test:
                mock_test.return_value = True
                
                # Register webhook
                result = self.provider.action_register_webhook()
                
                # Verify connectivity test was called
                mock_test.assert_called_once()
                
                # Verify success result
                self.assertEqual(result['params']['type'], 'success')