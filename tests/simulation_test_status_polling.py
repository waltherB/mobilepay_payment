#!/usr/bin/env python3
"""
Simulation test for payment status polling and mapping logic.
"""

import sys
from unittest.mock import Mock, MagicMock

# Logic copied for simulation purposes
def process_status(transaction, status_data):
    """
    Simulated _mobilepay_process_status logic.
    """
    status = status_data.get('status')
    if not status:
        return

    # Map MobilePay status to Odoo state
    if status == 'RESERVED':
        transaction._set_authorized()
    elif status == 'CAPTURED':
        transaction._set_done()
    elif status in ['CANCELLED', 'EXPIRED', 'ABORTED']:
        transaction._set_canceled()
        
    # Update captured/refunded amounts if present
    details = status_data.get('paymentDetails', {})
    if details:
        vals = {}
        if 'capturedAmount' in details:
            vals['captured_amount'] = float(details['capturedAmount']) / 100.0
        if 'refundedAmount' in details:
            vals['refunded_amount'] = float(details['refundedAmount']) / 100.0
        
        if vals:
            transaction.write(vals)

class MockTransaction:
    def __init__(self):
        self.state = 'draft'
        self.vals = {}
        
    def _set_authorized(self):
        self.state = 'authorized'
        print("    -> Transitioned to AUTHORIZED")
        
    def _set_done(self):
        self.state = 'done'
        print("    -> Transitioned to DONE")
        
    def _set_canceled(self):
        self.state = 'cancel'
        print("    -> Transitioned to CANCEL")
        
    def write(self, vals):
        self.vals.update(vals)
        print(f"    -> Updated values: {vals}")

def test_status_mapping():
    print("Testing Status Mapping Logic")
    print("=" * 40)
    
    # Test cases
    scenarios = [
        ('RESERVED', 'authorized'),
        ('CAPTURED', 'done'),
        ('CANCELLED', 'cancel'),
        ('EXPIRED', 'cancel'),
        ('ABORTED', 'cancel'),
        ('UNKNOWN', 'draft') # Should not change state
    ]
    
    success = True
    
    for status, expected_state in scenarios:
        print(f"\nTesting status: {status}")
        tx = MockTransaction()
        process_status(tx, {'status': status})
        
        if tx.state == expected_state:
            print(f"  ✓ Correctly mapped to {expected_state}")
        else:
            print(f"  ✗ Failed: expected {expected_state}, got {tx.state}")
            success = False
            
    # Test details update
    print("\nTesting Amount Updates")
    tx = MockTransaction()
    data = {
        'status': 'CAPTURED', 
        'paymentDetails': {
            'capturedAmount': 10000, # 100.00
            'refundedAmount': 5000   # 50.00
        }
    }
    process_status(tx, data)
    
    if tx.vals.get('captured_amount') == 100.0 and tx.vals.get('refunded_amount') == 50.0:
        print("  ✓ Captured/Refunded amounts updated correctly")
    else:
        print(f"  ✗ Failed to update amounts: {tx.vals}")
        success = False
        
    return success

if __name__ == "__main__":
    if test_status_mapping():
        print("\nAll status polling tests passed!")
        sys.exit(0)
    else:
        sys.exit(1)
