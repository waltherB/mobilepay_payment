from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase


class TestMobilePayLifecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env.ref("mobilepay_payment.payment_provider_mobilepay")
        cls.provider.write({"state": "test", "capture_mode": "manual"})
        cls.currency = cls.env.ref("base.DKK")
        cls.currency.active = True
        cls.partner = cls.env["res.partner"].create({
            "name": "Lifecycle Test", "country_id": cls.env.ref("base.dk").id,
        })
        cls.client = cls.env["mobilepay.api.client"]

    def _transaction(self, **values):
        return self.env["payment.transaction"].create({
            "provider_id": self.provider.id,
            "payment_method_id": self.env.ref("mobilepay_payment.payment_method_mobilepay").id,
            "partner_id": self.partner.id,
            "currency_id": self.currency.id,
            "reference": self.env["payment.transaction"]._compute_reference("mobilepay", prefix="FLOW"),
            "amount": 100.0,
            "authorized_amount": 100.0,
            "mobilepay_api_reference": "FLOW-REMOTE",
            "mobilepay_payment_id": "FLOW-REMOTE",
            "provider_reference": "FLOW-REMOTE",
            "state": "authorized",
            "mobilepay_status": "AUTHORIZED",
            "operation": "online_redirect",
            **values,
        })

    def _aggregate(self, captured=0, refunded=0, cancelled=0, authorized=100):
        return {"aggregate": {
            name: {"currency": "DKK", "value": int(round(amount * 100))}
            for name, amount in (
                ("authorizedAmount", authorized), ("capturedAmount", captured),
                ("refundedAmount", refunded), ("cancelledAmount", cancelled),
            )
        }}

    def test_backend_void_calls_cancel(self):
        tx = self._transaction()
        with patch.object(type(self.client), "cancel_payment", return_value=self._aggregate(
            cancelled=100
        )) as cancel:
            tx.action_void()
        cancel.assert_called_once()
        self.assertEqual(tx.state, "cancel")
        self.assertEqual(tx.cancelled_amount, 100)

    def test_legacy_cancel_calls_real_hook(self):
        tx = self._transaction()
        with patch.object(type(self.client), "cancel_payment", return_value=self._aggregate(
            cancelled=100
        )):
            tx._send_cancel_request()
        self.assertEqual(tx.state, "cancel")

    def test_pending_payment_can_be_terminated(self):
        tx = self._transaction(state="pending")
        with patch.object(type(self.client), "cancel_payment", return_value={"state": "TERMINATED"}):
            tx._send_cancel_request()
        self.assertEqual(tx.state, "cancel")

    def test_full_capture_uses_parent(self):
        tx = self._transaction()
        with patch.object(type(self.client), "capture_payment", return_value=self._aggregate(100)):
            child = tx._send_capture_request()
        self.assertFalse(child)
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.captured_amount, 100)

    def test_repeated_partial_capture_creates_children(self):
        tx = self._transaction()
        with patch.object(type(self.client), "capture_payment", side_effect=[
            self._aggregate(40), self._aggregate(100),
        ]) as capture:
            first = tx._send_capture_request(40)
            self.assertEqual(tx.state, "authorized")
            self.assertTrue(tx.capture_eligible)
            second = tx._send_capture_request()
        self.assertEqual(first.amount, 40)
        self.assertEqual(second.amount, 60)
        self.assertEqual(first.state, "done")
        self.assertEqual(second.state, "done")
        self.assertEqual((first | second).source_transaction_id, tx)
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.captured_amount, 100)
        self.assertNotEqual(
            capture.call_args_list[0].kwargs["idempotency_key"],
            capture.call_args_list[1].kwargs["idempotency_key"],
        )

    def test_capture_then_void_remaining_preserves_captured_child(self):
        tx = self._transaction()
        with patch.object(type(self.client), "capture_payment", return_value=self._aggregate(40)):
            captured = tx._send_capture_request(40)
        with patch.object(type(self.client), "cancel_payment", return_value=self._aggregate(
            captured=40, cancelled=60
        )):
            voided = tx._send_void_request(60)
        self.assertEqual(tx.state, "done")
        self.assertEqual(captured.state, "done")
        self.assertEqual(voided.state, "cancel")
        self.assertEqual(voided.amount, 60)
        self.assertEqual(tx.captured_amount, 40)
        self.assertEqual(tx.cancelled_amount, 60)

    def test_capture_wizard_can_capture_and_void_remaining(self):
        tx = self._transaction()
        wizard = self.env["payment.capture.wizard"].create({
            "transaction_ids": [(6, 0, tx.ids)],
            "amount_to_capture": 40,
            "void_remaining_amount": True,
        })
        with patch.object(type(self.client), "capture_payment", return_value=self._aggregate(40)), \
             patch.object(type(self.client), "cancel_payment", return_value=self._aggregate(
                 captured=40, cancelled=60
             )):
            wizard.action_capture()
        self.assertEqual(tx.state, "done")
        self.assertEqual(sorted(tx.child_transaction_ids.mapped("state")), ["cancel", "done"])

    def test_partial_void_cannot_release_less_than_remaining(self):
        tx = self._transaction()
        with self.assertRaises(UserError), self.cr.savepoint(), \
             patch.object(type(self.client), "cancel_payment") as cancel:
            tx._send_void_request(30)
        cancel.assert_not_called()

    def test_refund_creates_negative_child(self):
        tx = self._transaction(state="done", captured_amount=100)
        with patch.object(type(self.client), "refund_payment", return_value=self._aggregate(
            captured=100, refunded=25
        )):
            refund = tx._send_refund_request(25)
        self.assertEqual(refund.source_transaction_id, tx)
        self.assertEqual(refund.operation, "refund")
        self.assertEqual(refund.amount, -25)
        self.assertEqual(refund.state, "done")
        self.assertEqual(tx.refunded_amount, 25)
        self.assertEqual(tx.state, "done")

    def test_repeated_refunds_default_to_remaining(self):
        tx = self._transaction(state="done", captured_amount=100)
        with patch.object(type(self.client), "refund_payment", side_effect=[
            self._aggregate(100, 25), self._aggregate(100, 100),
        ]):
            first = tx._send_refund_request(25)
            second = tx._send_refund_request()
        self.assertEqual(first.amount, -25)
        self.assertEqual(second.amount, -75)
        self.assertEqual(tx.refunded_amount, 100)
        self.assertEqual(tx.mobilepay_status, "REFUNDED")
        self.assertEqual(tx.state, "done")

    def test_partial_capture_refund_updates_root_and_child(self):
        tx = self._transaction()
        with patch.object(type(self.client), "capture_payment", return_value=self._aggregate(40)):
            child = tx._send_capture_request(40)
        with patch.object(type(self.client), "refund_payment", return_value=self._aggregate(
            captured=40, refunded=10
        )) as refund_request:
            refund = child._send_refund_request(10)
        self.assertEqual(refund_request.call_args.args[1], tx.mobilepay_api_reference)
        self.assertEqual(refund.source_transaction_id, child)
        self.assertEqual(child.refunded_amount, 10)
        self.assertEqual(tx.refunded_amount, 10)

    def test_captured_parent_with_children_cannot_be_refunded_twice(self):
        tx = self._transaction()
        with patch.object(type(self.client), "capture_payment", side_effect=[
            self._aggregate(40), self._aggregate(100),
        ]):
            tx._send_capture_request(40)
            tx._send_capture_request(60)
        with self.assertRaises(UserError), self.cr.savepoint():
            tx._send_refund_request(10)

    def test_invalid_capture_amounts_do_not_call_api(self):
        for amount in (0, -1, 100.01, 1.001, True, float("nan"), float("inf")):
            with self.subTest(amount=amount), self.assertRaises(UserError), self.cr.savepoint(), \
                 patch.object(type(self.client), "capture_payment") as request:
                self._transaction()._send_capture_request(amount)
            request.assert_not_called()

    def test_invalid_refund_amounts_do_not_call_api(self):
        for amount in (0, -1, 100.01, 1.001, True, float("nan"), float("inf")):
            with self.subTest(amount=amount), self.assertRaises(UserError), self.cr.savepoint(), \
                 patch.object(type(self.client), "refund_payment") as request:
                self._transaction(state="done", captured_amount=100)._send_refund_request(amount)
            request.assert_not_called()

    def test_api_error_does_not_confirm_child_or_change_amounts(self):
        tx = self._transaction()
        with self.assertRaises(UserError), self.cr.savepoint(), \
             patch.object(type(self.client), "capture_payment", side_effect=UserError("API failure")):
            tx._send_capture_request(40)
        self.assertEqual(tx.state, "authorized")
        self.assertEqual(tx.captured_amount, 0)
        self.assertFalse(tx.child_transaction_ids)

    def test_unconfirmed_capture_does_not_mark_done(self):
        tx = self._transaction()
        for response in ({}, self._aggregate(99)):
            with self.subTest(response=response), self.assertRaises(UserError), self.cr.savepoint(), \
                 patch.object(type(self.client), "capture_payment", return_value=response):
                tx._send_capture_request()
        self.assertEqual(tx.state, "authorized")
        self.assertEqual(tx.captured_amount, 0)

    def test_lost_response_retry_reuses_operation_key(self):
        tx = self._transaction()
        with patch.object(type(self.client), "capture_payment", side_effect=[
            UserError("Lost response"), self._aggregate(40),
        ]) as request:
            with self.assertRaises(UserError), self.cr.savepoint():
                tx._send_capture_request(40)
            tx._send_capture_request(40)
        self.assertEqual(
            request.call_args_list[0].kwargs["idempotency_key"],
            request.call_args_list[1].kwargs["idempotency_key"],
        )

    def test_authorized_aggregate_confirms_capture_and_does_not_reopen(self):
        tx = self._transaction()
        tx._mobilepay_process_status({"state": "AUTHORIZED", **self._aggregate(100)})
        self.assertEqual(tx.state, "done")
        tx._mobilepay_process_status({"state": "AUTHORIZED", **self._aggregate(100)})
        self.assertEqual(tx.state, "done")

    def test_refund_retry_reuses_key_without_duplicate_child(self):
        tx = self._transaction(state="done", captured_amount=100)
        with patch.object(type(self.client), "refund_payment", side_effect=[
            UserError("Lost response"), self._aggregate(100, 25),
        ]) as request:
            with self.assertRaises(UserError), self.cr.savepoint():
                tx._send_refund_request(25)
            tx._send_refund_request(25)
        self.assertEqual(request.call_args_list[0].kwargs["idempotency_key"],
                         request.call_args_list[1].kwargs["idempotency_key"])
        self.assertEqual(len(tx.child_transaction_ids), 1)

    def test_cancel_retry_reuses_key_and_requires_aggregate_confirmation(self):
        tx = self._transaction()
        with patch.object(type(self.client), "cancel_payment", side_effect=[
            {}, self._aggregate(cancelled=100),
        ]) as request:
            with self.assertRaises(UserError), self.cr.savepoint():
                tx.action_void()
            self.assertEqual(tx.state, "authorized")
            tx.action_void()
        self.assertEqual(request.call_args_list[0].kwargs["idempotency_key"],
                         request.call_args_list[1].kwargs["idempotency_key"])
        self.assertEqual(tx.state, "cancel")

    def test_authorized_aggregate_confirms_cancellation(self):
        tx = self._transaction()
        tx._mobilepay_process_status({"state": "AUTHORIZED", **self._aggregate(cancelled=100)})
        self.assertEqual(tx.state, "cancel")

    def test_partial_capture_poll_keeps_remaining_eligible(self):
        tx = self._transaction()
        tx._mobilepay_process_status({"state": "AUTHORIZED", **self._aggregate(40)})
        self.assertEqual(tx.state, "authorized")
        self.assertTrue(tx.capture_eligible)
        self.assertEqual(tx.mobilepay_status, "PARTIALLY_CAPTURED")

    def test_delayed_capture_runs_at_boundary_once(self):
        self.provider.write({"capture_mode": "auto_delay", "auto_capture_delay": 24})
        now = fields.Datetime.now()
        tx = self._transaction(last_state_change=now - timedelta(hours=24))
        with patch.object(fields.Datetime, "now", return_value=now), \
             patch.object(type(self.client), "capture_payment", return_value=self._aggregate(100)) as request:
            tx._cron_mobilepay_auto_capture()
            tx._cron_mobilepay_auto_capture()
        request.assert_called_once()
        self.assertEqual(tx.state, "done")

    def test_delayed_capture_waits_from_authorization_not_creation(self):
        self.provider.write({"capture_mode": "auto_delay", "auto_capture_delay": 24})
        now = fields.Datetime.now()
        tx = self._transaction(last_state_change=now - timedelta(hours=23, minutes=59))
        with patch.object(fields.Datetime, "now", return_value=now), \
             patch.object(type(self.client), "capture_payment") as request:
            tx._cron_mobilepay_auto_capture()
        request.assert_not_called()

    def test_delayed_capture_excludes_manual_delivery_and_disabled(self):
        tx = self._transaction(last_state_change=fields.Datetime.now() - timedelta(days=2))
        for values in (
            {"capture_mode": "manual"}, {"capture_mode": "delivery"},
            {"capture_mode": "auto_delay", "state": "disabled"},
        ):
            self.provider.write(values)
            with patch.object(type(self.client), "capture_payment") as request:
                tx._cron_mobilepay_auto_capture()
            request.assert_not_called()

    def test_delayed_capture_failure_is_logged_and_other_payment_runs(self):
        self.provider.write({"capture_mode": "auto_delay", "auto_capture_delay": 0})
        first = self._transaction(last_state_change=fields.Datetime.now() - timedelta(hours=1))
        second = self._transaction(last_state_change=first.last_state_change)
        with patch.object(type(self.client), "capture_payment", side_effect=[
            UserError("Capture unavailable"), self._aggregate(100),
        ]) as request:
            first._cron_mobilepay_auto_capture()
        self.assertEqual(request.call_count, 2)
        self.assertEqual(first.state, "authorized")
        self.assertEqual(second.state, "done")

    def test_negative_delay_rejected(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.provider.auto_capture_delay = -1

    def test_phone_formatting_rejects_letters_and_overlong_numbers(self):
        tx = self._transaction()
        for phone in ("+45 12 34 56 78", "12345678", "004512345678"):
            self.assertEqual(tx._format_phone_number_v3(phone), "4512345678")
        for phone in ("call12345678", "+1234567890123456", "invalid"):
            self.assertIsNone(tx._format_phone_number_v3(phone))
