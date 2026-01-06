# -*- coding: utf-8 -*-

import json
import unittest
from unittest.mock import patch, Mock
from datetime import datetime, timedelta
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

try:
    from hypothesis import given, strategies as st, settings
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False


class TestOAuth2TokenManagement(TransactionCase):
    """
    Property-based tests for OAuth2 token management.
    
    **Feature: odoo-mobilepay-integration, Property 2: OAuth2 Token Management**
    **Validates: Requirements 2.1, 2.2, 2.3**
    """

    def setUp(self):
        super().setUp()
        self.PaymentProvider = self.env['payment.provider']
        self.AuthService = self.env['mobilepay.auth.service']
        
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

    def tearDown(self):
        # Clean up cached tokens after each test
        self.AuthService._clear_cached_token(self.provider.id)
        super().tearDown()

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        access_token=st.text(min_size=10, max_size=100),
        expires_in=st.integers(min_value=60, max_value=7200)
    )
    @settings(max_examples=20, deadline=None)
    def test_property_token_caching_and_retrieval(self, access_token, expires_in):
        """
        Property: For any valid access token and expiry time, the authentication service 
        should cache the token and retrieve it correctly until expiry.
        
        **Validates: Requirements 2.1, 2.2**
        """
        # Store token
        self.AuthService._store_token(self.provider.id, access_token, expires_in)
        
        # Should retrieve the same token
        cached_token = self.AuthService._get_cached_token(self.provider.id)
        self.assertEqual(cached_token, access_token, 
                        "Cached token should match stored token")
        
        # Token should be valid for the expected duration (minus safety margin)
        # We can't test actual expiry without time manipulation, but we can verify storage

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        client_id=st.text(min_size=5, max_size=50),
        client_secret=st.text(min_size=10, max_size=100),
        response_token=st.text(min_size=20, max_size=200),
        expires_in=st.integers(min_value=300, max_value=7200)
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_auth_service.requests.post')
    def test_property_token_acquisition_with_valid_credentials(self, mock_post, 
                                                             client_id, client_secret, 
                                                             response_token, expires_in):
        """
        Property: For any valid credentials and successful API response, the authentication 
        service should acquire and cache a new token.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Update provider with test credentials
        self.provider.write({
            'mobilepay_client_id': client_id,
            'mobilepay_client_secret': client_secret
        })
        
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': response_token,
            'expires_in': expires_in,
            'token_type': 'Bearer'
        }
        mock_post.return_value = mock_response
        
        # Acquire token
        token = self.AuthService._acquire_new_token(self.provider)
        
        # Verify token matches response
        self.assertEqual(token, response_token, 
                        "Acquired token should match API response")
        
        # Verify token is cached
        cached_token = self.AuthService._get_cached_token(self.provider.id)
        self.assertEqual(cached_token, response_token,
                        "Token should be cached after acquisition")
        
        # Verify API was called with correct parameters
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('grant_type', call_args[1]['data'])
        self.assertEqual(call_args[1]['data']['client_id'], client_id)
        self.assertEqual(call_args[1]['data']['client_secret'], client_secret)

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        status_code=st.integers(min_value=400, max_value=599),
        error_message=st.text(min_size=1, max_size=200)
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_auth_service.requests.post')
    def test_property_token_acquisition_error_handling(self, mock_post, status_code, error_message):
        """
        Property: For any API error response, the authentication service should 
        raise appropriate UserError with meaningful message.
        
        **Validates: Requirements 2.3**
        """
        # Mock error response
        mock_response = Mock()
        mock_response.status_code = status_code
        mock_response.text = error_message
        mock_post.return_value = mock_response
        
        # Should raise UserError for any error status code
        with self.assertRaises(UserError) as context:
            self.AuthService._acquire_new_token(self.provider)
        
        # Error message should contain some reference to the failure
        error_str = str(context.exception)
        self.assertTrue(len(error_str) > 0, "Error message should not be empty")

    @unittest.skipUnless(HYPOTHESIS_AVAILABLE, "Hypothesis not available")
    @given(
        initial_token=st.text(min_size=10, max_size=100),
        new_token=st.text(min_size=10, max_size=100),
        expires_in=st.integers(min_value=300, max_value=7200)
    )
    @settings(max_examples=20, deadline=None)
    @patch('mobilepay_payment.models.mobilepay_auth_service.requests.post')
    def test_property_token_refresh_on_401_response(self, mock_post, initial_token, 
                                                   new_token, expires_in):
        """
        Property: For any 401 response handling, the authentication service should 
        clear the old token and acquire a new one.
        
        **Validates: Requirements 2.2**
        """
        # Assume initial_token and new_token are different for meaningful test
        if initial_token == new_token:
            new_token = initial_token + "_refreshed"
        
        # Store initial token
        self.AuthService._store_token(self.provider.id, initial_token, 3600)
        
        # Verify initial token is cached
        cached_token = self.AuthService._get_cached_token(self.provider.id)
        self.assertEqual(cached_token, initial_token)
        
        # Mock successful refresh response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': new_token,
            'expires_in': expires_in,
            'token_type': 'Bearer'
        }
        mock_post.return_value = mock_response
        
        # Handle 401 response (refresh token)
        refreshed_token = self.AuthService.handle_401_response(self.provider)
        
        # Should return new token
        self.assertEqual(refreshed_token, new_token,
                        "Should return new token after refresh")
        
        # New token should be cached
        cached_token = self.AuthService._get_cached_token(self.provider.id)
        self.assertEqual(cached_token, new_token,
                        "New token should be cached after refresh")

    def test_get_access_token_uses_cached_when_available(self):
        """Test that get_access_token returns cached token when available."""
        test_token = "cached_test_token"
        
        # Store a token
        self.AuthService._store_token(self.provider.id, test_token, 3600)
        
        # get_access_token should return cached token without API call
        with patch('mobilepay_payment.models.mobilepay_auth_service.requests.post') as mock_post:
            token = self.AuthService.get_access_token(self.provider)
            self.assertEqual(token, test_token)
            mock_post.assert_not_called()

    @patch('mobilepay_payment.models.mobilepay_auth_service.requests.post')
    def test_get_access_token_acquires_new_when_no_cache(self, mock_post):
        """Test that get_access_token acquires new token when no cached token."""
        test_token = "new_test_token"
        
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': test_token,
            'expires_in': 3600,
            'token_type': 'Bearer'
        }
        mock_post.return_value = mock_response
        
        # Should acquire new token
        token = self.AuthService.get_access_token(self.provider)
        self.assertEqual(token, test_token)
        mock_post.assert_called_once()

    def test_missing_credentials_raises_error(self):
        """Test that missing credentials raise appropriate error."""
        # Create provider without credentials
        invalid_provider = self.PaymentProvider.create({
            'name': 'Invalid MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            # Missing credentials
        })
        
        with self.assertRaises(UserError):
            self.AuthService._acquire_new_token(invalid_provider)