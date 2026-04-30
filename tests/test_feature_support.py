# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase

class TestMobilePayFeatureSupport(TransactionCase):
    """Test feature support flags for MobilePay provider."""

    def setUp(self):
        super().setUp()
        self.provider = self.env['payment.provider'].search([
            ('code', '=', 'mobilepay')
        ], limit=1)

    def test_feature_support_flags(self):
        """Verify that feature support flags are correctly computed."""
        self.assertTrue(self.provider, "MobilePay provider should exist")
        
        # Trigger compute
        self.provider._compute_feature_support_fields()
        
        self.assertEqual(self.provider.support_manual_capture, 'full',
                         "MobilePay should support partial manual capture")
        self.assertEqual(self.provider.support_refund, 'partial',
                         "MobilePay should support partial refunds")
        self.assertFalse(self.provider.support_tokenization,
                         "MobilePay should not support tokenization (as per current config)")
