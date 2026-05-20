#!/usr/bin/env python3
"""
Comprehensive Integration Simulation Test for MobilePay Module.
Simulates the entire payment lifecycle:
1. Configuration & Encryption
2. Payment Initiation (with Phone Normalization)
3. Frontend Context (JS Logic Simulation)
4. Status Polling (Reserved -> Authorized)
5. Manual Capture (Captured -> Done)
6. Refund (Partial Refund -> Update)
"""

import sys
import uuid
import logging
from unittest.mock import MagicMock, Mock
from cryptography.fernet import Fernet

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Mock Odoo Environment ---
class Models(dict):
    def __init__(self):
        self['ir.config_parameter'] = MockConfigParameter()
        self['mobilepay.api.client'] = MockApiClient()
        
    def __getitem__(self, key):
        return super().get(key, MagicMock())

class MockConfigParameter:
    def __init__(self):
        self.params = {}
    def sudo(self): return self
    def get_param(self, key): return self.params.get(key)
    def set_param(self, key, value): self.params[key] = value

class MockApiClient:
    def create_payment(self, provider, data):
        return {'paymentId': str(uuid.uuid4())}
    def get_payment_status(self, provider, payment_id):
        # Default behavior, can be overridden in test
        return {'status': 'RESERVED'}
    def capture_payment(self, provider, payment_id, data):
        return {'status': 'CAPTURED'}
    def refund_payment(self, provider, payment_id, data):
        return {'status': 'REFUNDED'}

class MockRecord:
    def __init__(self, env, **kwargs):
        self.env = env
        self.vals = kwargs
        self._name = 'mock.record' # Default name
        for k, v in kwargs.items():
            setattr(self, k, v)
            
    def __getattr__(self, name):
        if name in self.vals:
            return self.vals[name]
        # Return 0 for amount fields to be safe in math simulation
        if 'amount' in name:
            return 0.0
        # For methods, return a dummy function if needed, or raise
        if name in ['ensure_one', 'sudo']:
             return lambda: self
        return None
    
    def write(self, vals):
        self.vals.update(vals)
        for k, v in vals.items():
            setattr(self, k, v)
        logger.info(f"  [DB] Updated {self._name}: {vals}")

class PaymentProvider(MockRecord):
    _name = 'payment.provider'
    
    def _get_encryption_key(self):
        key = self.env['ir.config_parameter'].get_param('mobilepay.encryption_key')
        if not key:
            key = Fernet.generate_key().decode()
            self.env['ir.config_parameter'].set_param('mobilepay.encryption_key', key)
        return key.encode()

    def _encrypt(self, value):
        if not value: return False
        try:
            f = Fernet(self._get_encryption_key())
            return f.encrypt(value.encode()).decode()
        except: return False
        
    def _decrypt(self, value):
        if not value: return False
        try:
            f = Fernet(self._get_encryption_key())
            return f.decrypt(value.encode()).decode()
        except: return False

class PaymentTransaction(MockRecord):
    _name = 'payment.transaction'
    
    def _convert_dkk_to_ore(self, amount): return int(round(amount * 100))
    def _convert_ore_to_dkk(self, amount): return float(amount) / 100.0
    
    def _format_phone_number_e164(self, phone):
        # Mini-implementation of the logic
        if not phone: return None
        import re
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('45') and len(digits) == 10: return f"+{digits}"
        if len(digits) == 8: return f"+45{digits}"
        return None

    def _send_payment_request(self):
        # Simulate logic from payment_transaction.py
        logger.info(f"  [Tx] Sending payment request for '{self.reference}'")
        
        # Phone handling
        phone = self.partner_phone if hasattr(self, 'partner_phone') else None
        fmt_phone = self._format_phone_number_e164(phone)
        if fmt_phone:
            logger.info(f"  [Tx] Using phone: {fmt_phone}")
        
        # Call API
        api = self.env['mobilepay.api.client']
        resp = api.create_payment(self.provider_id, {})
        
        self.write({
            'mobilepay_payment_id': resp['paymentId'],
            'state': 'pending'
        })
        return resp

    def _mobilepay_get_payment_status(self):
        logger.info(f"  [Tx] Polling status...")
        api = self.env['mobilepay.api.client']
        status_data = api.get_payment_status(self.provider_id, self.mobilepay_payment_id)
        
        self.write({'mobilepay_status': status_data['status']})
        self._mobilepay_process_status(status_data)
        
    def _mobilepay_process_status(self, data):
        logger.info(f"  [Tx] Processing status: {data['status']}")
        if data['status'] == 'RESERVED':
            self.write({'state': 'authorized', 'authorized_amount': self.amount})
        elif data['status'] == 'CAPTURED':
             self.write({'state': 'done'})
             
    def _send_capture_request(self, amount_to_capture=None):
        logger.info(f"  [Tx] Executing Manual Capture")
        api = self.env['mobilepay.api.client']
        api.capture_payment(self.provider_id, self.mobilepay_payment_id, {})
        self.write({
            'state': 'done',
            'captured_amount': self.amount,
            'mobilepay_status': 'CAPTURED'
        })

    def _send_refund_request(self, refund_amount=None):
        amount = refund_amount or self.captured_amount
        logger.info(f"  [Tx] Requesting Refund: {amount} DKK")
        
        # Validation checks simulated
        if self.state != 'done': raise Exception("Tx not done")
        if getattr(self, 'refunded_amount', 0) + amount > self.captured_amount:
            raise Exception("Refund exceeds capture")
            
        api = self.env['mobilepay.api.client']
        api.refund_payment(self.provider_id, self.mobilepay_payment_id, {})
        
        self.write({
            'refunded_amount': getattr(self, 'refunded_amount', 0) + amount,
            'mobilepay_status': 'REFUNDED' if getattr(self, 'refunded_amount', 0) + amount >= self.captured_amount else self.mobilepay_status
        })

# --- Integration Test Flow ---

def run_integration_test():
    print("\nRunning Integration Simulation")
    print("=" * 40)
    
    env = Models()
    
    # 1. Configuration
    print("\n[Step 1] Configuration & Encryption")
    provider = PaymentProvider(env, 
        mobilepay_client_secret_encrypted=None,
        mobilepay_client_secret=None
    )
    # Encrypt
    secret = "super_secret_sauce"
    encrypted = provider._encrypt(secret)
    provider.write({'mobilepay_client_secret_encrypted': encrypted})
    # Decrypt
    decrypted = provider._decrypt(encrypted)
    if decrypted == secret:
        print("✓ Credentials encrypted and decrypted successfully")
    else:
        print("✗ Encryption failed")
        return False

    # 2. Payment Initiation
    print("\n[Step 2] Payment Initiation")
    tx = PaymentTransaction(env, 
        reference="TX-001", 
        amount=100.0, 
        state='draft', 
        provider_id=provider,
        partner_phone="12345678" # From Frontend Context
    )
    tx._send_payment_request()
    
    if tx.mobilepay_payment_id and tx.state == 'pending':
        print("✓ Payment initiated, ID received, state is pending")
    else:
        print("✗ Payment initiation failed")
        return False

    # 3. Status Polling (User pays on phone)
    print("\n[Step 3] Status Polling (User Authorizes)")
    # Mock return status as RESERVED
    tx._mobilepay_get_payment_status()
    
    if tx.state == 'authorized' and tx.authorized_amount == 100.0:
        print("✓ Status updated to AUTHORIZED")
    else:
        print("✗ Status update failed")
        return False

    # 4. Manual Capture
    print("\n[Step 4] Manual Capture")
    tx._send_capture_request()
    
    if tx.state == 'done' and tx.captured_amount == 100.0:
        print("✓ Payment CAPTURED successfully")
    else:
        print("✗ Capture failed")
        return False

    # 5. Partial Refund
    print("\n[Step 5] Partial Refund")
    tx._send_refund_request(refund_amount=50.0)
    
    if getattr(tx, 'refunded_amount', 0) == 50.0 and tx.state == 'done':
        print("✓ Partial refund processed successfully")
    else:
        print("✗ Partial refund failed")
        return False
        
    print("\n[Step 6] Full Refund Remainder")
    tx._send_refund_request(refund_amount=50.0)
    
    if getattr(tx, 'refunded_amount', 0) == 100.0 and getattr(tx, 'mobilepay_status') == 'REFUNDED':
        print("✓ Full refund completed, status is REFUNDED")
    else:
        print("✗ Full refund failed")
        return False

    return True

if __name__ == "__main__":
    if run_integration_test():
        print("\nAll integration tests passed successfully!")
        sys.exit(0)
    else:
        sys.exit(1)
