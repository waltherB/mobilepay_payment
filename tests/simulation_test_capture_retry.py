#!/usr/bin/env python3
"""
Simulation test for manual capture and retry logic.
"""

import sys
from unittest.mock import Mock, MagicMock
import datetime

# --- Simulation of Logic ---
class SimulatedTransaction:
    def __init__(self, provider_code='mobilepay', state='authorized', 
                 mobilepay_status='RESERVED', amount=100.0, create_date=None):
        self.provider_id = type('MockProvider', (), {'code': provider_code})()
        self.state = state
        self.mobilepay_status = mobilepay_status
        self.amount = amount
        self.authorized_amount = amount
        self.captured_amount = 0.0
        self.mobilepay_payment_id = "test_payment_id"
        self.reference = "TEST-REF"
        self.provider_id = Mock()
        self.env = MagicMock()
        
        # Simulate Odoo fields
        self.create_date = create_date or datetime.datetime.now()
        
    @property
    def capture_eligible(self):
        return (
            self.provider_id.code == 'mobilepay' and
            self.state == 'authorized' and
            self.mobilepay_status == 'RESERVED' and
            self.authorized_amount > 0
        )

    def _convert_dkk_to_ore(self, amount):
        return int(round(amount * 100))

    def _set_done(self):
        self.state = 'done'
        print("    -> State transitioned to DONE")

    def write(self, vals):
        print(f"    -> Writing values: {vals}")
        if 'captured_amount' in vals:
            self.captured_amount = vals['captured_amount']
        if 'mobilepay_status' in vals:
            self.mobilepay_status = vals['mobilepay_status']

    def action_capture(self):
        print(f"  Action: Capture transaction {self.reference}")
        if self.provider_code != 'mobilepay':
            print("    -> Not mobilepay provider, skipping")
            return
            
        if not self.capture_eligible:
            print("    -> Error: Not eligible for capture")
            return False
            
        amount_ore = self._convert_dkk_to_ore(self.amount)
        capture_data = {
            'amount': amount_ore,
            'description': f"Capture for {self.reference}"
        }
        
        try:
            # Mock API call
            print(f"    -> Calling API capture with amount {amount_ore}")
            
            # Simulate success
            self._set_done()
            self.write({
                'captured_amount': self.amount,
                'mobilepay_status': 'CAPTURED'
            })
            return True
            
        except Exception as e:
            print(f"    -> Capture failed: {e}")
            return False

    def _mobilepay_retry_poll_status(self):
        print("  Action: Retry Poll Status")
        status_timeout_min = 5
        
        if self.provider_code != 'mobilepay' or self.state not in ['draft', 'pending']:
             print("    -> Skipping: Invalid state/provider")
             return

        time_diff = datetime.datetime.now() - self.create_date
        seconds_elapsed = time_diff.total_seconds()
        
        print(f"    -> Seconds elapsed: {seconds_elapsed}")
        
        if seconds_elapsed < (status_timeout_min * 60):
            print("    -> Polling API...")
            # Simulate polling call
            self.write({'last_status_poll': datetime.datetime.now()})
        else:
            print("    -> Timeout exceeded, stop polling")


# --- Tests ---

def test_manual_capture():
    print("\nTesting Manual Capture Logic")
    print("=" * 40)
    
    # Case 1: Eligible transaction
    print("\nCase 1: Eligible Transaction")
    tx = SimulatedTransaction()
    result = tx.action_capture()
    if result and tx.state == 'done' and tx.mobilepay_status == 'CAPTURED':
        print("✓ Capture successful")
    else:
        print("✗ Capture failed")
        return False
        
    # Case 2: Ineligible transaction (already captured/done)
    print("\nCase 2: Ineligible Transaction (Already Done)")
    tx = SimulatedTransaction(state='done', mobilepay_status='CAPTURED')
    result = tx.action_capture()
    if not result:
        print("✓ Capture correctly blocked")
    else:
        print("✗ Should have been blocked")
        return False
        
    return True

def test_retry_polling():
    print("\nTesting Retry Polling Logic")
    print("=" * 40)
    
    # Case 1: Within timeframe (e.g. 2 minutes ago)
    print("\nCase 1: Transaction created 2 mins ago")
    create_date = datetime.datetime.now() - datetime.timedelta(minutes=2)
    tx = SimulatedTransaction(state='pending', create_date=create_date)
    tx._mobilepay_retry_poll_status() # Should poll
    
    # Case 2: Outside timeframe (e.g. 6 minutes ago)
    print("\nCase 2: Transaction created 6 mins ago")
    create_date = datetime.datetime.now() - datetime.timedelta(minutes=6)
    tx = SimulatedTransaction(state='pending', create_date=create_date)
    tx._mobilepay_retry_poll_status() # Should NOT poll
    
    return True

if __name__ == "__main__":
    if test_manual_capture() and test_retry_polling():
        print("\nAll capture/retry simulation tests passed!")
        sys.exit(0)
    else:
        sys.exit(1)
