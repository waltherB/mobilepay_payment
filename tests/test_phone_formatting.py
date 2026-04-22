# -*- coding: utf-8 -*-

import unittest
from odoo.tests.common import TransactionCase
from hypothesis import given, strategies as st, example

class TestPhoneFormatting(TransactionCase):
    """
    Property-based tests for phone number formatting.
    
    **Feature: odoo-mobilepay-integration, Property 6: Phone Number Formatting**
    **Validates: Requirements 3.3, 8.1, 8.2**
    """

    def setUp(self):
        super().setUp()
        self.Transaction = self.env['payment.transaction']

    def _format(self, number):
        # Access the private method via a dummy transaction or model method
        # Since it's a model method, we need an instance, or we can patch it to be static if it doesn't use self
        # Actually it uses self but only for logic that doesn't touch DB.
        # We can use a dummy transaction instance
        tx = self.Transaction.new({})
        return tx._format_phone_number_e164(number)

    @given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
    def test_basic_danish_number(self, digits):
        """Test formatting of 8-digit Danish numbers."""
        formatted = self._format(digits)
        self.assertEqual(formatted, f"+45{digits}")

    @given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
    def test_danish_number_with_45_prefix(self, digits):
        """Test formatting of 45+8 digits."""
        formatted = self._format(f"45{digits}")
        self.assertEqual(formatted, f"+45{digits}")

    @given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
    def test_danish_number_with_plus_45(self, digits):
        """Test formatting of +45+8 digits."""
        formatted = self._format(f"+45{digits}")
        self.assertEqual(formatted, f"+45{digits}")

    @given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
    def test_danish_number_with_0045(self, digits):
        """Test formatting of 0045+8 digits."""
        formatted = self._format(f"0045{digits}")
        self.assertEqual(formatted, f"+45{digits}")

    @given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
    def test_danish_number_with_spaces(self, digits):
        """Test formatting with spaces."""
        # Insert random spaces
        spaced = f"{digits[:2]} {digits[2:4]} {digits[4:6]} {digits[6:]}"
        formatted = self._format(spaced)
        self.assertEqual(formatted, f"+45{digits}")
        
        spaced_prefix = f"+45 {digits[:2]} {digits[2:4]} {digits[4:6]} {digits[6:]}"
        formatted = self._format(spaced_prefix)
        self.assertEqual(formatted, f"+45{digits}")

    @given(st.text())
    def test_invalid_numbers_return_none(self, text):
        """Test that invalid numbers return None."""
        # Filter out valid numbers (rough approximation for test simplicity)
        digits = ''.join(filter(str.isdigit, text))
        
        # If it happens to be a valid Danish number, skip this test case
        is_valid_dk = \
            (len(digits) == 8) or \
            (len(digits) == 10 and digits.startswith('45')) or \
            (len(digits) == 12 and digits.startswith('0045'))
            
        if is_valid_dk:
            return

        formatted = self._format(text)
        self.assertIsNone(formatted, f"Should return None for {text}")
