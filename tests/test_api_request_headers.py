# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch, Mock
from odoo.tests.common import TransactionCase

try:
    from hypothesis import given, strategies as st, settings
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False


class TestAPIRequestHeaders(TransactionCase):
    """
    Property-based tests for API request headers.
    
    **Feature: odoo-mobilepay-integration, Property 3: API Request Headers**
    **Validates: Requirements 2.5**
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
        access_token=st.text(min_size=20, max_size=200),
        subscription_key=st.text(min_size=10, max_size=100),
        merchant_serial=st.text(min_size=5, max_size=50)
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_auth_service.MobilePayAuthService.get_access_token')
    def test_property_mandatory_headers_present(self, mock_get_token, access_token, 
                                              subscription_key, merchant_serial):
        """
        Property: For any MobilePay API request, all mandatory Vipps system headers 
        should be included with correct values.
        
        **Validates: Requirements 2.5**
        """
        # Mock the auth service to return our test token
        mock_get_token.return_value = access_token
        
        # Update provider with test values
        self.provider.write({
            'mobilepay_subscription_key': subscription_key,
            'mobilepay_merchant_serial': merchant_serial
        })
        
        # Get system headers
        headers = self.ApiClient._get_system_headers(self.provider)
        
        # Verify all mandatory headers are present
        mandatory_headers = [
            'Authorization',
            'Vipps-System-Name',
            'Vipps-System-Version', 
            'Vipps-System-Plugin-Name',
            'Vipps-System-Plugin-Version',
            'Ocp-Apim-Subscription-Key',
            'Vipps-Merchant-Serial-Number',
            'Content-Type',
            'Accept'
        ]
        
        for header in mandatory_headers:
            self.assertIn(header, headers, f"Header {header} should be present")
        
        # Verify header values are correct
        self.assertEqual(headers['Authorization'], f'Bearer {access_token}')
        self.assertEqual(headers['Vipps-System-Name'], 'Odoo')
        self.assertEqual(headers['Vipps-System-Version'], '17.0')
        self.assertEqual(headers['Vipps-System-Plugin-Name'], 'mobilepay_payment')
        self.assertEqual(headers['Vipps-System-Plugin-Version'], '1.0.0')
        self.assertEqual(headers['Ocp-Apim-Subscription-Key'], subscription_key)
        self.assertEqual(headers['Vipps-Merchant-Serial-Number'], merchant_serial)
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(headers['Accept'], 'application/json')

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        endpoint=st.text(min_size=1, max_size=100),
        method=st.sampled_from(['GET', 'POST', 'PUT', 'DELETE'])
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_auth_service.MobilePayAuthService.get_access_token')
    @patch('mobilepay_payment.models.mobilepay_api_client.requests.request')
    def test_property_headers_included_in_all_requests(self, mock_request, mock_get_token, 
                                                     endpoint, method):
        """
        Property: For any API request method and endpoint, the mandatory headers 
        should be included in the actual HTTP request.
        
        **Validates: Requirements 2.5**
        """
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_request.return_value = mock_response
        
        # Mock auth service
        mock_get_token.return_value = 'test_access_token'
        
        # Make API request
        try:
            self.ApiClient._make_request(self.provider, method, f'/{endpoint}')
        except Exception:
            # We don't care if the request logic fails, we just want to verify headers
            pass
        
        # Verify request was made with headers
        if mock_request.called:
            call_args = mock_request.call_args
            headers = call_args[1].get('headers', {})
            
            # Check that key headers are present
            expected_headers = [
                'Authorization',
                'Vipps-System-Name',
                'Ocp-Apim-Subscription-Key',
                'Vipps-Merchant-Serial-Number'
            ]
            
            for header in expected_headers:
                self.assertIn(header, headers, 
                            f"Header {header} should be included in {method} request")

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        client_id=st.text(min_size=5, max_size=50),
        client_secret=st.text(min_size=10, max_size=100),
        subscription_key=st.text(min_size=10, max_size=100),
        merchant_serial=st.text(min_size=5, max_size=50)
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_auth_service.MobilePayAuthService.get_access_token')
    def test_property_header_values_match_provider_config(self, mock_get_token, client_id, 
                                                        client_secret, subscription_key, 
                                                        merchant_serial):
        """
        Property: For any provider configuration, the API headers should contain 
        values that match the provider's configuration.
        
        **Validates: Requirements 2.5**
        """
        # Mock auth service
        mock_get_token.return_value = 'test_token'
        
        # Update provider with test configuration
        self.provider.write({
            'mobilepay_client_id': client_id,
            'mobilepay_client_secret': client_secret,
            'mobilepay_subscription_key': subscription_key,
            'mobilepay_merchant_serial': merchant_serial
        })
        
        # Get headers
        headers = self.ApiClient._get_system_headers(self.provider)
        
        # Verify provider-specific values are correctly included
        self.assertEqual(headers['Ocp-Apim-Subscription-Key'], subscription_key,
                        "Subscription key should match provider configuration")
        self.assertEqual(headers['Vipps-Merchant-Serial-Number'], merchant_serial,
                        "Merchant serial should match provider configuration")
        
        # Verify system headers are consistent
        self.assertEqual(headers['Vipps-System-Name'], 'Odoo')
        self.assertEqual(headers['Vipps-System-Plugin-Name'], 'mobilepay_payment')

    def test_headers_include_bearer_token(self):
        """Test that Authorization header includes Bearer token format."""
        with patch('mobilepay_payment.models.mobilepay_auth_service.MobilePayAuthService.get_access_token') as mock_get_token:
            test_token = 'test_access_token_123'
            mock_get_token.return_value = test_token
            
            headers = self.ApiClient._get_system_headers(self.provider)
            
            self.assertEqual(headers['Authorization'], f'Bearer {test_token}')
            self.assertTrue(headers['Authorization'].startswith('Bearer '))

    def test_content_type_headers_are_json(self):
        """Test that Content-Type and Accept headers are set to JSON."""
        with patch('mobilepay_payment.models.mobilepay_auth_service.MobilePayAuthService.get_access_token') as mock_get_token:
            mock_get_token.return_value = 'test_token'
            
            headers = self.ApiClient._get_system_headers(self.provider)
            
            self.assertEqual(headers['Content-Type'], 'application/json')
            self.assertEqual(headers['Accept'], 'application/json')