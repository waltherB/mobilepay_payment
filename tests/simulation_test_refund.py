#!/usr/bin/env python3
"""
Simulation test for refund logic.
"""

import sys
from unittest.mock import Mock, MagicMock
import uuid

# --- Simulation of Logic ---
class SimulatedTransaction:
    def __init__(self, provider_code='mobilepay', state='done', 
                 amount=100.0, captured_amount=100.0, refunded_amount=0.0):
        self.provider_id = type('MockProvider', (), {'code': provider_code})()
        self.state = state
        self.amount = amount
        self.captured_amount = captured_amount
        self.refunded_amount = refunded_amount
        self.mobilepay_payment_id = "test_payment_id"
        self.reference = "TEST-REF"
        self.mobilepay_status = 'CAPTURED'
        self.provider_id = Mock()
        self.env = MagicMock()
        
    def _convert_dkk_to_ore(self, amount):
        return int(round(amount * 100))
        
    def write(self, vals):
        print(f"    -> Writing values: {vals}")
        if 'refunded_amount' in vals:
            self.refunded_amount = vals['refunded_amount']
        if 'mobilepay_status' in vals:
            self.mobilepay_status = vals['mobilepay_status']

    def _send_refund_request(self, amount_to_refund=None):
        print(f"  Action: Refund transaction {self.reference} for {amount_to_refund or 'FULL'}")
        
        if self.provider_id.code != 'mobilepay':
            print("    -> Not mobilepay provider, skipping")
            return
            
        if self.state != 'done':
            print("    -> Error: Transaction not in done state")
            return False
            
        if not self.mobilepay_payment_id:
            print("    -> Error: Missing payment ID")
            return False

        # Calculate refund amount
        refund_amount = amount_to_refund or self.captured_amount
        
        # Validate refund amount
        remaining_amount = self.captured_amount - self.refunded_amount
        
        if refund_amount > remaining_amount + 0.01:
             print(f"    -> Error: Refund {refund_amount} > Remaining {remaining_amount}")
             return False

        amount_ore = self._convert_dkk_to_ore(refund_amount)
        print(f"    -> Calling API refund with amount {amount_ore} ({refund_amount} DKK)")
        
        try:
            # Mock API call
            # Simulate success
            new_refunded_amount = self.refunded_amount + refund_amount
            self.write({
                'refunded_amount': new_refunded_amount,
                'mobilepay_status': 'REFUNDED' if new_refunded_amount >= self.captured_amount else self.mobilepay_status
            })
            
            return True
            
        except Exception as e:
            print(f"    -> Refund failed: {e}")
            return False

# --- Tests ---

def test_refund_logic():
    print("\nTesting Refund Logic")
    print("=" * 40)
    
    # Case 1: Full Refund Success
    print("\nCase 1: Full Refund Success")
    tx = SimulatedTransaction(amount=100.0, captured_amount=100.0)
    result = tx._send_refund_request()
    if result and tx.refunded_amount == 100.0 and tx.mobilepay_status == 'REFUNDED':
        print("✓ Full refund successful")
    else:
        print("✗ Full refund failed")
        return False
        
    # Case 2: Partial Refund Success
    print("\nCase 2: Partial Refund (50 DKK) Success")
    tx = SimulatedTransaction(amount=100.0, captured_amount=100.0)
    result = tx._send_refund_request(amount_to_refund=50.0)
    if result and tx.refunded_amount == 50.0 and tx.mobilepay_status == 'CAPTURED':
        print("✓ Partial refund successful")
    else:
        print("✗ Partial refund failed")
        return False
        
    # Case 3: Invalid state
    print("\nCase 3: Invalid State (Authorized)")
    tx = SimulatedTransaction(state='authorized', captured_amount=0.0)
    result = tx._send_refund_request()
    if not result:
        print("✓ Refund correctly blocked for non-done state")
    else:
        print("✗ Should have been blocked")
        return False
        
    # Case 4: Refund Amount Exceeds Captured
    print("\nCase 4: Refund Amount > Captured")
    tx = SimulatedTransaction(amount=100.0, captured_amount=100.0, refunded_amount=50.0)
    result = tx._send_refund_request(amount_to_refund=60.0) # 50 refunded + 60 request = 110 > 100
    if not result:
        print("✓ Excessive refund blocked")
    else:
        print("✗ Should have been blocked")
        return False
        
    return True

if __name__ == "__main__":
    if test_refund_logic():
        print("\nAll refund simulation tests passed!")
        sys.exit(0)
    else:
        sys.exit(1)
