#!/usr/bin/env python3
"""
Simulation test for Azure-style Webhook Signature Verification.
"""

import sys
import unittest
import json
import hashlib
import hmac
import base64
from unittest.mock import MagicMock

# --- Mocks for logic testing ---
class MockController:
    def _verify_signature(self, payload, auth_header, content_hash_header, date_header, host_header, path, secret):
        # Transcribed logic from controllers/main.py for isolated testing
        if not secret:
            return False
            
        try:
            # 1. Verify content hash
            calculated_hash = base64.b64encode(hashlib.sha256(payload).digest()).decode('utf-8')
            if not hmac.compare_digest(calculated_hash, content_hash_header):
                print(f"Hash mismatch: {calculated_hash} != {content_hash_header}")
                return False
                
            if 'Signature=' not in auth_header:
                return False
            
            provided_signature = auth_header.split('Signature=')[1]
            
            # 3. Construct string to sign
            string_to_sign = f"POST\n{path}\n{date_header};{host_header};{content_hash_header}"
            
            # 4. Calculate HMAC
            # Secret is base64 encoded
            key = base64.b64decode(secret)
            
            calculated_hmac = hmac.new(key, string_to_sign.encode('utf-8'), hashlib.sha256).digest()
            calculated_signature = base64.b64encode(calculated_hmac).decode('utf-8')
            
            return hmac.compare_digest(calculated_signature, provided_signature)
            
        except Exception as e:
            print(f"Error: {e}")
            return False

class TestWebhookAuth(unittest.TestCase):
    
    def test_azure_signature_verification(self):
        """Test the Azure-style signature verification logic."""
        controller = MockController()
        
        # Test Data
        secret = "A0+AeKBRG2KRGvnNwJpQlb6IJFk48CKXCIcrLoHncVJKDILsQSxS6NWCccwWm6r6FhGKhiHTBsG2wo/xU6FY/A=="
        payload = json.dumps({"data": {"paymentId": "123"}}).encode('utf-8')
        date = "Thu, 30 Mar 2023 08:38:32 GMT"
        host = "webhook.site"
        path = "/payment/mobilepay/webhook"
        
        # 1. Calculate Content Hash
        content_hash = base64.b64encode(hashlib.sha256(payload).digest()).decode('utf-8')
        
        # 2. Construct String to Sign
        string_to_sign = f"POST\n{path}\n{date};{host};{content_hash}"
        
        # 3. Calculate Signature using the secret
        key = base64.b64decode(secret)
        signature_hmac = hmac.new(key, string_to_sign.encode('utf-8'), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature_hmac).decode('utf-8')
        
        # 4. Construct Authorization Header
        auth_header = f"HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature={signature_b64}"
        
        print(f"Testing with valid signature: {signature_b64}")
        
        # ACT
        result = controller._verify_signature(
            payload,
            auth_header,
            content_hash,
            date,
            host,
            path,
            secret
        )
        
        # ASSERT
        self.assertTrue(result, "Valid signature should pass verification")
        
        # Test Tampering
        tampered_payload = json.dumps({"data": {"paymentId": "666"}}).encode('utf-8') # Evil payload
        
        result_tampered = controller._verify_signature(
            tampered_payload, # Changed payload
            auth_header,      # Original header (now mismatch)
            content_hash,     # Original hash (mismatch with payload)
            date,
            host,
            path,
            secret
        )
        self.assertFalse(result_tampered, "Tampered payload content hash check should fail")
        
        print("✓ Simulation passed")

if __name__ == "__main__":
    unittest.main()
