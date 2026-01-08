# -*- coding: utf-8 -*-

import unittest
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestMobilePayModuleStructure(TransactionCase):
    """Test module structure and basic configuration."""

    def setUp(self):
        super().setUp()
        self.PaymentProvider = self.env['payment.provider']
        self.PaymentTransaction = self.env['payment.transaction']

    def test_module_manifest_dependencies(self):
        """Test that module has correct dependencies."""
        # Get the module info
        module_info = self.env['ir.module.module'].search([
            ('name', '=', 'mobilepay_payment')
        ])
        
        # Check if module exists (it should be loaded for tests to run)
        self.assertTrue(module_info, "MobilePay payment module should be installed")
        
        # Verify required models are available
        self.assertTrue(hasattr(self.env, 'payment.provider'), 
                       "payment.provider model should be available")
        self.assertTrue(hasattr(self.env, 'payment.transaction'), 
                       "payment.transaction model should be available")

    def test_payment_provider_inheritance(self):
        """Test that payment.provider model is properly extended."""
        # Check that mobilepay code is available in selection
        provider_codes = dict(self.PaymentProvider._fields['code'].selection)
        self.assertIn('mobilepay', provider_codes, 
                     "MobilePay should be available as payment provider code")
        
        # Check MobilePay-specific fields exist
        provider_fields = self.PaymentProvider._fields
        expected_fields = [
            'mobilepay_client_id',
            'mobilepay_client_secret', 
            'mobilepay_subscription_key',
            'mobilepay_merchant_serial',
            'mobilepay_webhook_id',
            'mobilepay_webhook_secret',
            'capture_manually',
            'auto_capture_delay'
        ]
        
        for field_name in expected_fields:
            self.assertIn(field_name, provider_fields,
                         f"Field {field_name} should exist on payment.provider")

    def test_payment_transaction_inheritance(self):
        """Test that payment.transaction model is properly extended."""
        transaction_fields = self.PaymentTransaction._fields
        expected_fields = [
            'mobilepay_payment_id',
            'mobilepay_idempotency_key',
            'mobilepay_status',
            'authorized_amount',
            'captured_amount', 
            'refunded_amount',
            'last_status_poll',
            'capture_eligible'
        ]
        
        for field_name in expected_fields:
            self.assertIn(field_name, transaction_fields,
                         f"Field {field_name} should exist on payment.transaction")

    def test_mobilepay_provider_creation(self):
        """Test creating a MobilePay payment provider."""
        provider = self.PaymentProvider.create({
            'name': 'Test MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': 'test_client_secret',
            'mobilepay_subscription_key': 'test_subscription_key',
            'mobilepay_merchant_serial': 'test_merchant_serial'
        })
        
        self.assertEqual(provider.code, 'mobilepay')
        self.assertEqual(provider.mobilepay_client_id, 'test_client_id')
        self.assertTrue(provider.capture_manually)  # Default value

    def test_mobilepay_credentials_validation(self):
        """Test that MobilePay credentials are properly validated."""
        # Test missing credentials should raise ValidationError
        with self.assertRaises(ValidationError):
            self.PaymentProvider.create({
                'name': 'Invalid MobilePay Provider',
                'code': 'mobilepay',
                'state': 'test',
                'mobilepay_client_id': 'test_client_id',
                # Missing other required fields
            })

    def test_currency_compatibility(self):
        """Test that MobilePay only works with DKK currency."""
        # Create DKK currency if it doesn't exist
        dkk_currency = self.env['res.currency'].search([('name', '=', 'DKK')])
        if not dkk_currency:
            dkk_currency = self.env['res.currency'].create({
                'name': 'DKK',
                'symbol': 'kr',
                'rate': 1.0
            })
        
        # Create USD currency for comparison
        usd_currency = self.env['res.currency'].search([('name', '=', 'USD')])
        if not usd_currency:
            usd_currency = self.env['res.currency'].create({
                'name': 'USD', 
                'symbol': '$',
                'rate': 1.0
            })
        
        # Create MobilePay provider
        provider = self.PaymentProvider.create({
            'name': 'Test MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': 'test_client_secret',
            'mobilepay_subscription_key': 'test_subscription_key',
            'mobilepay_merchant_serial': 'test_merchant_serial'
        })
        
        # Test DKK compatibility
        compatible_providers_dkk = self.PaymentProvider._get_compatible_providers(
            currency_id=dkk_currency.id
        )
        mobilepay_providers_dkk = compatible_providers_dkk.filtered(
            lambda p: p.code == 'mobilepay'
        )
        self.assertTrue(mobilepay_providers_dkk, 
                       "MobilePay should be compatible with DKK currency")
        
        # Test USD incompatibility  
        compatible_providers_usd = self.PaymentProvider._get_compatible_providers(
            currency_id=usd_currency.id
        )
        mobilepay_providers_usd = compatible_providers_usd.filtered(
            lambda p: p.code == 'mobilepay'
        )
        self.assertFalse(mobilepay_providers_usd,
                        "MobilePay should not be compatible with USD currency")

    def test_transaction_capture_eligible_computation(self):
        """Test capture_eligible field computation."""
        # Create a provider first
        provider = self.PaymentProvider.create({
            'name': 'Test MobilePay Provider',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': 'test_client_secret',
            'mobilepay_subscription_key': 'test_subscription_key',
            'mobilepay_merchant_serial': 'test_merchant_serial'
        })
        
        # Create transaction
        transaction = self.PaymentTransaction.create({
            'provider_id': provider.id,
            'reference': 'TEST-001',
            'amount': 100.0,
            'currency_id': self.env.ref('base.DKK').id,
            'reference': 'TEST-001',
            'state': 'authorized',
            'mobilepay_status': 'RESERVED',
            'authorized_amount': 100.0
        })
        
        # Should be eligible for capture
        self.assertTrue(transaction.capture_eligible,
                       "Transaction should be eligible for capture")
        
        # Change state to done - should not be eligible
        transaction.state = 'done'
        self.assertFalse(transaction.capture_eligible,
                        "Done transaction should not be eligible for capture")