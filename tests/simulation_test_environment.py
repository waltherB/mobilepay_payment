#!/usr/bin/env python3
"""
Simulation test for API URL generation based on environment state.
"""

import sys
import unittest
from unittest.mock import MagicMock

# --- Mocks ---
class MockPaymentProvider:
    def __init__(self, state='enabled'):
        self.state = state
        
    def ensure_one(self):
        pass
        
    def _mobilepay_get_api_url(self):
        # Transcribed logic for testing
        self.ensure_one()
        if self.state == 'enabled':
            return 'https://api.vipps.no'
        else:
            return 'https://apitest.vipps.no'

class TestEnvironmentSwitching(unittest.TestCase):
    
    def test_production_url(self):
        """Test that 'enabled' state returns Production URL."""
        provider = MockPaymentProvider(state='enabled')
        url = provider._mobilepay_get_api_url()
        self.assertEqual(url, 'https://api.vipps.no')
        print("✓ Production URL verified")
        
    def test_test_url(self):
        """Test that 'test' state returns Test URL."""
        provider = MockPaymentProvider(state='test')
        url = provider._mobilepay_get_api_url()
        self.assertEqual(url, 'https://apitest.vipps.no')
        print("✓ Test URL verified")

    def test_disabled_defaults_to_test(self):
        """Test that 'disabled' (or other states) default to Test URL for safety."""
        provider = MockPaymentProvider(state='disabled')
        url = provider._mobilepay_get_api_url()
        self.assertEqual(url, 'https://apitest.vipps.no')
        print("✓ Disabled/Other defaults to Test URL verified")

if __name__ == "__main__":
    unittest.main()
