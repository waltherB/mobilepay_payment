#!/usr/bin/env python3
"""
Simulation test for credential switching based on provider state.
"""

import sys
import unittest
from unittest.mock import MagicMock

# --- Mocks ---
class MockPaymentProvider:
    def __init__(self, state='test'):
        self.state = state
        # Test credentials
        self.mobilepay_test_client_id = 'test_client_123'
        self.mobilepay_test_client_secret_encrypted = 'encrypted_test_secret'
        self.mobilepay_test_subscription_key_encrypted = 'encrypted_test_key'
        self.mobilepay_test_merchant_serial = 'TEST-MSN-123'
        # Production credentials
        self.mobilepay_prod_client_id = 'prod_client_456'
        self.mobilepay_prod_client_secret_encrypted = 'encrypted_prod_secret'
        self.mobilepay_prod_subscription_key_encrypted = 'encrypted_prod_key'
        self.mobilepay_prod_merchant_serial = 'PROD-MSN-456'
        
    def ensure_one(self):
        pass
        
    def _decrypt(self, encrypted_value):
        # Mock decryption - just remove 'encrypted_' prefix
        if encrypted_value and encrypted_value.startswith('encrypted_'):
            return encrypted_value.replace('encrypted_', '')
        return False
        
    def _compute_active_credentials(self):
        # Transcribed logic from payment_provider.py
        if self.state == 'enabled':
            # Production mode
            self.mobilepay_client_id = self.mobilepay_prod_client_id
            self.mobilepay_client_secret = self._decrypt(self.mobilepay_prod_client_secret_encrypted) if self.mobilepay_prod_client_secret_encrypted else False
            self.mobilepay_subscription_key = self._decrypt(self.mobilepay_prod_subscription_key_encrypted) if self.mobilepay_prod_subscription_key_encrypted else False
            self.mobilepay_merchant_serial = self.mobilepay_prod_merchant_serial
        else:
            # Test mode (test or disabled)
            self.mobilepay_client_id = self.mobilepay_test_client_id
            self.mobilepay_client_secret = self._decrypt(self.mobilepay_test_client_secret_encrypted) if self.mobilepay_test_client_secret_encrypted else False
            self.mobilepay_subscription_key = self._decrypt(self.mobilepay_test_subscription_key_encrypted) if self.mobilepay_test_subscription_key_encrypted else False
            self.mobilepay_merchant_serial = self.mobilepay_test_merchant_serial

class TestCredentialSwitching(unittest.TestCase):
    
    def test_test_mode_uses_test_credentials(self):
        """Test that 'test' state uses Test credentials."""
        provider = MockPaymentProvider(state='test')
        provider._compute_active_credentials()
        
        self.assertEqual(provider.mobilepay_client_id, 'test_client_123')
        self.assertEqual(provider.mobilepay_client_secret, 'test_secret')
        self.assertEqual(provider.mobilepay_subscription_key, 'test_key')
        self.assertEqual(provider.mobilepay_merchant_serial, 'TEST-MSN-123')
        print("✓ Test mode uses Test credentials")
        
    def test_enabled_mode_uses_production_credentials(self):
        """Test that 'enabled' state uses Production credentials."""
        provider = MockPaymentProvider(state='enabled')
        provider._compute_active_credentials()
        
        self.assertEqual(provider.mobilepay_client_id, 'prod_client_456')
        self.assertEqual(provider.mobilepay_client_secret, 'prod_secret')
        self.assertEqual(provider.mobilepay_subscription_key, 'prod_key')
        self.assertEqual(provider.mobilepay_merchant_serial, 'PROD-MSN-456')
        print("✓ Enabled mode uses Production credentials")

    def test_disabled_mode_uses_test_credentials(self):
        """Test that 'disabled' state defaults to Test credentials for safety."""
        provider = MockPaymentProvider(state='disabled')
        provider._compute_active_credentials()
        
        self.assertEqual(provider.mobilepay_client_id, 'test_client_123')
        self.assertEqual(provider.mobilepay_merchant_serial, 'TEST-MSN-123')
        print("✓ Disabled mode defaults to Test credentials")

if __name__ == "__main__":
    unittest.main()
