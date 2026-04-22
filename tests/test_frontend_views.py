# -*- coding: utf-8 -*-

import unittest
from odoo.tests.common import TransactionCase, tagged

@tagged('post_install', '-at_install')
class TestFrontendViews(TransactionCase):
    """
    Test frontend views and templates for MobilePay.
    """

    def test_inline_form_template_exists(self):
        """Test that the inline form template is correctly registered."""
        view = self.env.ref('mobilepay_payment.inline_form', raise_if_not_found=False)
        self.assertTrue(view, "Inline form template 'mobilepay_payment.inline_form' not found")
        
    def test_inline_form_content(self):
        """Test that the inline form contains the phone input and branding."""
        view = self.env.ref('mobilepay_payment.inline_form')
        # Check for inputs
        self.assertIn('mobilepay_phone', view.arch_base, "Phone input not found in template")
        self.assertIn('form-control', view.arch_base, "Input missing form-control class")
        
        # Check for branding elements
        self.assertIn('mobilepay_icon.png', view.arch_base, "MobilePay logo not found in template")
        self.assertIn('Pay with MobilePay', view.arch_base, "Branding text not found")
