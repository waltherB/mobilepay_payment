#!/usr/bin/env python3
"""
Simulation of the property-based test for data encryption.
Validates the encryption logic and computed fields without a full Odoo environment.
"""

import sys
import unittest
from unittest.mock import Mock, MagicMock
from cryptography.fernet import Fernet
import functools

# Mock Odoo fields
class Field:
    def __init__(self, string=None, help=None, compute=None, inverse=None, required_if_provider=None, readonly=False, copy=True):
        self.string = string
        self.compute = compute
        self.inverse = inverse

def api_depends(*args):
    def decorator(func):
        return func
    return decorator

# Mock Model
class MockModel:
    def __init__(self):
        self._vals = {}
        # env will be replaced by subclass or just initialized as Mock
        self.env = Mock()
        
    def __getattr__(self, name):
        if name in self._vals:
            return self._vals[name]
        return None
        
    def __setattr__(self, name, value):
        if name in ['_vals', 'env']:
            super().__setattr__(name, value)
        else:
            self._vals[name] = value

class PaymentProviderSimulation(MockModel):
    def __init__(self):
        super().__init__()
        # Initialize dictionary to hold values
        self._vals = {
            'mobilepay_client_secret_encrypted': False,
            'mobilepay_subscription_key_encrypted': False,
            'mobilepay_webhook_secret_encrypted': False,
            'mobilepay_client_secret': False,
            'mobilepay_subscription_key': False,
            'mobilepay_webhook_secret': False
        }
        
        # Setup mock env
        self.env = MagicMock()
        
        # Setup mock config parameter
        self.config_param_mock = Mock()
        self._params = {}
        self.config_param_mock.sudo().get_param.side_effect = self._params.get
        self.config_param_mock.sudo().set_param.side_effect = self._params.__setitem__
        
        # Configure env.__getitem__ to return our config param mock
        def get_model(name):
            if name == 'ir.config_parameter':
                return self.config_param_mock
            return Mock()
            
        self.env.__getitem__.side_effect = get_model

    def _get_encryption_key(self):
        # Replicated logic from payment_provider.py
        param_obj = self.env['ir.config_parameter'].sudo()
        key = param_obj.get_param('mobilepay.encryption_key')
        if not key:
            key = Fernet.generate_key().decode()
            param_obj.set_param('mobilepay.encryption_key', key)
        return key.encode()

    def _encrypt(self, value):
        if not value:
            return False
        f = Fernet(self._get_encryption_key())
        return f.encrypt(value.encode()).decode()

    def _decrypt(self, value):
        if not value:
            return False
        try:
            f = Fernet(self._get_encryption_key())
            return f.decrypt(value.encode()).decode()
        except Exception:
            return False

    # Simulate computed fields logic
    def _compute_mobilepay_client_secret(self):
        # Logic from payment_provider.py
        if self.mobilepay_client_secret_encrypted:
            self.mobilepay_client_secret = self._decrypt(self.mobilepay_client_secret_encrypted)
        else:
            self.mobilepay_client_secret = False

    def _inverse_mobilepay_client_secret(self):
        # Logic from payment_provider.py
        if self.mobilepay_client_secret:
            self.mobilepay_client_secret_encrypted = self._encrypt(self.mobilepay_client_secret)
        else:
            self.mobilepay_client_secret_encrypted = False

def test_encryption_flow():
    print("Testing Encryption Flow Simulation")
    print("=" * 40)
    
    provider = PaymentProviderSimulation()
    
    # 1. Test setting plain text triggers encryption (Inverse)
    print("\n1. Test Inverse Computation (Encrypt)")
    original_secret = "my_super_secret_value"
    provider.mobilepay_client_secret = original_secret
    
    # Trigger inverse manually as we are simulating
    provider._inverse_mobilepay_client_secret()
    
    encrypted_val = provider.mobilepay_client_secret_encrypted
    print(f"  ✓ Original: {original_secret}")
    print(f"  ✓ Encrypted: {encrypted_val}")
    
    if encrypted_val == original_secret:
        print("  ✗ Error: Value was not encrypted!")
        return False
        
    if not encrypted_val:
        print("  ✗ Error: Encrypted value is empty!")
        return False
        
    # 2. Test getting plain text triggers decryption (Compute)
    print("\n2. Test Compute (Decrypt)")
    # Clear local cache to force compute
    provider.mobilepay_client_secret = False
    
    # Trigger compute manually
    provider._compute_mobilepay_client_secret()
    
    decrypted_val = provider.mobilepay_client_secret
    print(f"  ✓ Decrypted: {decrypted_val}")
    
    if decrypted_val != original_secret:
        print(f"  ✗ Error: Decrypted value '{decrypted_val}' does not match original '{original_secret}'")
        return False
        
    print("\n✓ Encryption/Decryption round trip successful!")
    return True

if __name__ == "__main__":
    if test_encryption_flow():
        sys.exit(0)
    else:
        sys.exit(1)
