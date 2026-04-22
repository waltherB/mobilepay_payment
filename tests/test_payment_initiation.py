# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase
from hypothesis import given, strategies as st
from unittest.mock import patch
import uuid


class TestPaymentInitiation(TransactionCase):
    """
    Property-based tests for payment initiation functionality.
    Feature: odoo-mobilepay-integration, Property 4: Payment Initiation
    Validates: Requirements 3.1, 3.4
    """

    def setUp(self):
        super().setUp()
        # Create a MobilePay payment provider
        self.provider = self.env['payment.provider'].create({
            'name': 'MobilePay Test',
            'code': 'mobilepay',
            'state': 'test',
            'mobilepay_client_id': 'test_client_id',
            'mobilepay_client_secret': 'test_client_secret',
            'mobilepay_subscription_key': 'test_subscription_key',
            'mobilepay_merchant_serial': 'test_merchant_serial',
        })

        # Create a test partner
        self.partner = self.env['res.partner'].create({
            'name': 'Test Customer',
            'email': 'test@example.com',
            'phone': '+4512345678',
        })

    def _create_test_transaction(self, amount=100.0, reference=None):
        """Helper method to create a test transaction."""
        return self.env['payment.transaction'].create({
            'reference': reference or 'TEST-001',
            'amount': amount,
            'currency_id': self.env.ref('base.DKK').id,
            'provider_id': self.provider.id,
            'partner_id': self.partner.id,
        })

    @given(
        amount=st.floats(
            min_value=0.01,
            max_value=999999.99,
            allow_nan=False,
            allow_infinity=False
        ),
        reference=st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(
                whitelist_categories=('Lu', 'Ll', 'Nd'),
                whitelist_characters='-_'
            )
        )
    )
    def test_payment_initiation_structure_property(self, amount, reference):
        """
        Property: For any payment initiation, the Payment Provider should send
        a properly structured POST request to MobilePay with unique idempotency
        key, customer details, and transaction data.

        Feature: odoo-mobilepay-integration, Property 4: Payment Initiation
        Validates: Requirements 3.1, 3.4
        """
        transaction = self._create_test_transaction(
            amount=amount,
            reference=f'TEST-{reference}'
        )

        # Mock the API client and capture the payment data sent
        captured_payment_data = {}

        def mock_create_payment(provider, payment_data):
            captured_payment_data.update(payment_data)
            return {'paymentId': 'test_payment_id_123'}

        with patch.object(
            self.env['mobilepay.api.client'],
            'create_payment',
            side_effect=mock_create_payment
        ):
            # Mock the provider's get_base_url method
            with patch.object(
                self.provider,
                'get_base_url',
                return_value='https://example.com'
            ):
                # Send payment request
                response = transaction._send_payment_request()

                # Verify response contains payment ID
                self.assertEqual(response['paymentId'], 'test_payment_id_123')

                # Property 1: Idempotency key must be generated and stored
                # (Requirement 3.4)
                self.assertTrue(transaction.mobilepay_idempotency_key)
                self.assertIsInstance(
                    transaction.mobilepay_idempotency_key, str
                )

                # Verify idempotency key is valid UUID
                try:
                    uuid.UUID(transaction.mobilepay_idempotency_key)
                    uuid_valid = True
                except ValueError:
                    uuid_valid = False
                self.assertTrue(uuid_valid)

                # Property 2: Payment data must contain all required fields
                # (Requirement 3.1)
                required_fields = [
                    'amount', 'idempotencyKey', 'paymentPointId',
                    'redirectUri', 'reference', 'userFlow', 'paymentMethod'
                ]
                for field in required_fields:
                    self.assertIn(field, captured_payment_data)

                # Verify specific field values
                self.assertEqual(
                    captured_payment_data['amount'],
                    int(round(amount * 100))  # DKK to øre conversion
                )
                self.assertEqual(
                    captured_payment_data['idempotencyKey'],
                    transaction.mobilepay_idempotency_key
                )
                self.assertEqual(
                    captured_payment_data['paymentPointId'],
                    self.provider.mobilepay_merchant_serial
                )
                self.assertEqual(
                    captured_payment_data['reference'],
                    transaction.reference
                )
                self.assertEqual(
                    captured_payment_data['userFlow'], 'WEB_REDIRECT'
                )
                self.assertEqual(
                    captured_payment_data['paymentMethod'], 'MobilePay'
                )

                # Property 3: Customer details must be included when available
                # (Requirement 3.1)
                self.assertIn('customer', captured_payment_data)
                customer_data = captured_payment_data['customer']
                self.assertEqual(customer_data['name'], self.partner.name)
                self.assertEqual(customer_data['email'], self.partner.email)
                self.assertEqual(
                    customer_data['phoneNumber'], '+4512345678'
                )

                # Property 4: Merchant info must be included
                # (Requirement 3.1)
                self.assertIn('merchantInfo', captured_payment_data)
                merchant_info = captured_payment_data['merchantInfo']
                self.assertIn('merchantName', merchant_info)
                self.assertIn('merchantContactUrl', merchant_info)

    @given(st.integers(min_value=1, max_value=100))
    def test_unique_idempotency_keys_property(self, num_transactions):
        """
        Property: For any number of transactions, each should have a unique
        idempotency key to prevent duplicate payments.

        Feature: odoo-mobilepay-integration, Property 4: Payment Initiation
        Validates: Requirements 3.4
        """
        idempotency_keys = set()

        # Limit to 10 for performance
        for i in range(min(num_transactions, 10)):
            transaction = self._create_test_transaction(
                reference=f'TEST-UNIQUE-{i}'
            )

            # Generate idempotency key
            key = transaction._generate_idempotency_key()

            # Property: Each key must be unique
            self.assertNotIn(key, idempotency_keys)
            idempotency_keys.add(key)

            # Property: Each key must be a valid UUID
            try:
                uuid.UUID(key)
                uuid_valid = True
            except ValueError:
                uuid_valid = False
            self.assertTrue(uuid_valid)

    @given(
        customer_name=st.text(min_size=1, max_size=100),
        customer_email=st.emails(),
        phone_digits=st.text(
            min_size=8,
            max_size=8,
            alphabet=st.characters(whitelist_categories=('Nd',))
        )
    )
    def test_payment_with_customer_data_property(
        self,
        customer_name,
        customer_email,
        phone_digits
    ):
        """
        Property: For any customer data, payment initiation should include
        properly formatted customer details in the request.

        Feature: odoo-mobilepay-integration, Property 4: Payment Initiation
        Validates: Requirements 3.1
        """
        # Create partner with generated data
        partner = self.env['res.partner'].create({
            'name': customer_name,
            'email': customer_email,
            'phone': f'+45{phone_digits}',
        })

        transaction = self.env['payment.transaction'].create({
            'reference': 'TEST-CUSTOMER-DATA',
            'amount': 100.0,
            'currency_id': self.env.ref('base.DKK').id,
            'provider_id': self.provider.id,
            'partner_id': partner.id,
        })

        captured_payment_data = {}

        def mock_create_payment(provider, payment_data):
            captured_payment_data.update(payment_data)
            return {'paymentId': 'test_payment_id'}

        with patch.object(
            self.env['mobilepay.api.client'],
            'create_payment',
            side_effect=mock_create_payment
        ):
            with patch.object(
                self.provider,
                'get_base_url',
                return_value='https://example.com'
            ):
                transaction._send_payment_request()

                # Property: Customer data must be included and properly
                # formatted
                self.assertIn('customer', captured_payment_data)
                customer_data = captured_payment_data['customer']

                self.assertEqual(customer_data['name'], customer_name)
                self.assertEqual(customer_data['email'], customer_email)
                self.assertEqual(
                    customer_data['phoneNumber'], f'+45{phone_digits}'
                )

    def test_payment_without_customer_data(self):
        """Test that payment request works without customer data."""
        # Create transaction without partner
        transaction = self.env['payment.transaction'].create({
            'reference': 'TEST-NO-PARTNER',
            'amount': 100.0,
            'currency_id': self.env.ref('base.DKK').id,
            'provider_id': self.provider.id,
        })

        captured_payment_data = {}

        def mock_create_payment(provider, payment_data):
            captured_payment_data.update(payment_data)
            return {'paymentId': 'test_payment_id'}

        with patch.object(
            self.env['mobilepay.api.client'],
            'create_payment',
            side_effect=mock_create_payment
        ):
            with patch.object(
                self.provider,
                'get_base_url',
                return_value='https://example.com'
            ):
                transaction._send_payment_request()

                # Should still have required fields but no customer data
                required_fields = [
                    'amount', 'idempotencyKey', 'paymentPointId',
                    'redirectUri', 'reference', 'userFlow', 'paymentMethod'
                ]
                for field in required_fields:
                    self.assertIn(field, captured_payment_data)

                # Should not have customer data
                self.assertNotIn('customer', captured_payment_data)

    def test_landing_route_generation(self):
        """Test that landing route is properly generated."""
        transaction = self._create_test_transaction()

        with patch.object(
            self.provider,
            'get_base_url',
            return_value='https://example.com'
        ):
            landing_route = transaction._get_landing_route()
            self.assertEqual(
                landing_route,
                'https://example.com/payment/mobilepay/return'
            )