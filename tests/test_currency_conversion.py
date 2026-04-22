# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase
from hypothesis import given, strategies as st
import hypothesis


class TestCurrencyConversion(TransactionCase):
    """
    Property-based tests for currency conversion functionality.
    Feature: odoo-mobilepay-integration, Property 5: Currency Conversion
    Validates: Requirements 3.2, 10.4
    """

    def setUp(self):
        super().setUp()
        # Create a MobilePay payment provider
        self.provider = self.env['payment.provider'].create({
            'name': 'MobilePay Test',
            'code': 'mobilepay',
            'state': 'test',
        })
        
        # Create a test transaction
        self.transaction = self.env['payment.transaction'].create({
            'reference': 'TEST-001',
            'amount': 100.0,
            'currency_id': self.env.ref('base.DKK').id,
            'provider_id': self.provider.id,
        })

    @given(st.floats(min_value=0.01, max_value=999999.99, allow_nan=False, allow_infinity=False))
    def test_dkk_to_ore_conversion_property(self, dkk_amount):
        """
        Property: For any positive DKK amount, converting to øre should multiply by 100 and round to integer.
        Feature: odoo-mobilepay-integration, Property 5: Currency Conversion
        Validates: Requirements 3.2, 10.4
        """
        # Convert DKK to øre
        ore_amount = self.transaction._convert_dkk_to_ore(dkk_amount)
        
        # Property: øre amount should be DKK amount * 100, rounded to integer
        expected_ore = int(round(dkk_amount * 100))
        self.assertEqual(ore_amount, expected_ore)
        
        # Property: øre amount should always be an integer
        self.assertIsInstance(ore_amount, int)
        
        # Property: øre amount should be non-negative for positive DKK amounts
        self.assertGreaterEqual(ore_amount, 0)

    @given(st.integers(min_value=1, max_value=99999999))
    def test_ore_to_dkk_conversion_property(self, ore_amount):
        """
        Property: For any positive øre amount, converting to DKK should divide by 100.
        Feature: odoo-mobilepay-integration, Property 5: Currency Conversion
        Validates: Requirements 3.2, 10.4
        """
        # Convert øre to DKK
        dkk_amount = self.transaction._convert_ore_to_dkk(ore_amount)
        
        # Property: DKK amount should be øre amount / 100
        expected_dkk = float(ore_amount) / 100.0
        self.assertEqual(dkk_amount, expected_dkk)
        
        # Property: DKK amount should always be a float
        self.assertIsInstance(dkk_amount, float)
        
        # Property: DKK amount should be non-negative for positive øre amounts
        self.assertGreaterEqual(dkk_amount, 0.0)

    @given(st.floats(min_value=0.01, max_value=999999.99, allow_nan=False, allow_infinity=False))
    def test_round_trip_conversion_property(self, original_dkk):
        """
        Property: Converting DKK to øre and back to DKK should preserve value within rounding precision.
        Feature: odoo-mobilepay-integration, Property 5: Currency Conversion
        Validates: Requirements 3.2, 10.4
        """
        # Round trip: DKK -> øre -> DKK
        ore_amount = self.transaction._convert_dkk_to_ore(original_dkk)
        final_dkk = self.transaction._convert_ore_to_dkk(ore_amount)
        
        # Property: Round trip should preserve value within 0.01 DKK precision (1 øre)
        self.assertAlmostEqual(original_dkk, final_dkk, places=2)

    def test_zero_amount_handling(self):
        """Test edge case: zero amounts should be handled correctly."""
        # Test zero DKK to øre
        self.assertEqual(self.transaction._convert_dkk_to_ore(0), 0)
        self.assertEqual(self.transaction._convert_dkk_to_ore(None), 0)
        
        # Test zero øre to DKK
        self.assertEqual(self.transaction._convert_ore_to_dkk(0), 0.0)
        self.assertEqual(self.transaction._convert_ore_to_dkk(None), 0.0)

    def test_typical_amounts(self):
        """Test specific examples of typical payment amounts."""
        # Test common payment amounts
        test_cases = [
            (1.00, 100),      # 1 DKK = 100 øre
            (10.50, 1050),    # 10.50 DKK = 1050 øre
            (99.99, 9999),    # 99.99 DKK = 9999 øre
            (100.00, 10000),  # 100 DKK = 10000 øre
            (0.01, 1),        # 0.01 DKK = 1 øre
        ]
        
        for dkk, expected_ore in test_cases:
            with self.subTest(dkk=dkk):
                self.assertEqual(self.transaction._convert_dkk_to_ore(dkk), expected_ore)
                self.assertEqual(self.transaction._convert_ore_to_dkk(expected_ore), dkk)