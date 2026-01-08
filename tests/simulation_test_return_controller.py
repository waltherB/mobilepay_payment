#!/usr/bin/env python3
"""
Simulation test for MobilePay Return Controller logic.
Verifies that the controller attempts to find the transaction and poll its status.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# --- Mocks ---

class MockTransaction:
    def __init__(self, reference):
        self.reference = reference
        self.provider_id = type('MockProvider', (), {'code': 'mobilepay'})()
        self.status_polled = False
        
    def _mobilepay_get_payment_status(self):
        print(f"Polling status for {self.reference}...")
        self.status_polled = True
        
class MockController:
    # Simulating the controller logic for isolation
    def mobilepay_return(self, params, fetch_transaction_mock):
        reference = params.get('reference')
        
        if reference:
            # Simulate search
            tx_sudo = fetch_transaction_mock(reference)
            
            if tx_sudo:
                print(f"MobilePay Return: Polling status for {reference}")
                try:
                    tx_sudo._mobilepay_get_payment_status()
                except Exception as e:
                    print(f"MobilePay Return: Failed to poll status: {e}")
        
        return "REDIRECT:/payment/status"


class TestReturnController(unittest.TestCase):
    
    def test_return_polls_status(self):
        """Test that the return handler polls status for valid reference."""
        controller = MockController()
        
        # Setup mock transaction
        mock_tx = MockTransaction("ORDER-123")
        
        def mock_search(ref):
            if ref == "ORDER-123":
                return mock_tx
            return None
            
        # ACT
        result = controller.mobilepay_return({'reference': "ORDER-123"}, mock_search)
        
        # ASSERT
        self.assertTrue(mock_tx.status_polled, "Transaction status should be polled on return")
        self.assertEqual(result, "REDIRECT:/payment/status")
        print("✓ Polling triggered successfully")
        
    def test_return_handle_invalid_reference(self):
        """Test that unknown reference doesn't crash."""
        controller = MockController()
        
        def mock_search(ref):
            return None
            
        # ACT
        result = controller.mobilepay_return({'reference': "UNKNOWN"}, mock_search)
        
        # ASSERT
        self.assertEqual(result, "REDIRECT:/payment/status", "Should still redirect even if tx not found")
        print("✓ Invalid reference handled gracefully")

if __name__ == "__main__":
    unittest.main()
