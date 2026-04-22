#!/usr/bin/env python3
"""
Simulation test for phone formatting logic.
"""

import sys
import re
from hypothesis import given, strategies as st, settings

# Logic copied EXACTLY from payment_transaction.py
def _format_phone_number_e164(phone_number):
    """
    Format phone number to E.164 format for MobilePay API.
    """
    if not phone_number:
        return None
    
    # Remove all non-digit characters
    digits_only = re.sub(r'\D', '', phone_number)
    
    # Handle Danish phone numbers
    if digits_only.startswith('45') and len(digits_only) == 10:
        # Already has country code
        return f"+{digits_only}"
    elif len(digits_only) == 8:
        # Add Danish country code
        return f"+45{digits_only}"
    elif digits_only.startswith('0045') and len(digits_only) == 12:
        # Remove leading 00 and add +
        return f"+{digits_only[2:]}"
    
    # If it already starts with +45, validate and return
    if phone_number.startswith('+45') and len(digits_only) == 10:
        return phone_number
    
    return None

@given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
@settings(max_examples=20)
def test_sim_basic_danish_number(digits):
    formatted = _format_phone_number_e164(digits)
    assert formatted == f"+45{digits}", f"Failed for {digits}: got {formatted}"

@given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
@settings(max_examples=20)
def test_sim_danish_number_with_45_prefix(digits):
    formatted = _format_phone_number_e164(f"45{digits}")
    assert formatted == f"+45{digits}", f"Failed for 45{digits}: got {formatted}"

@given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
@settings(max_examples=20)
def test_sim_danish_number_with_plus_45(digits):
    formatted = _format_phone_number_e164(f"+45{digits}")
    assert formatted == f"+45{digits}", f"Failed for +45{digits}: got {formatted}"

@given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
@settings(max_examples=20)
def test_sim_danish_number_with_0045(digits):
    formatted = _format_phone_number_e164(f"0045{digits}")
    assert formatted == f"+45{digits}", f"Failed for 0045{digits}: got {formatted}"

@given(st.text(min_size=8, max_size=8, alphabet=st.characters(whitelist_categories=('Nd',))))
@settings(max_examples=20)
def test_sim_danish_number_with_spaces(digits):
    spaced = f"{digits[:2]} {digits[2:4]} {digits[4:6]} {digits[6:]}"
    formatted = _format_phone_number_e164(spaced)
    assert formatted == f"+45{digits}", f"Failed for {spaced}: got {formatted}"
    
    spaced_prefix = f"+45 {digits[:2]} {digits[2:4]} {digits[4:6]} {digits[6:]}"
    formatted = _format_phone_number_e164(spaced_prefix)
    assert formatted == f"+45{digits}", f"Failed for {spaced_prefix}: got {formatted}"

def run_simulation():
    print("Running Phone Formatting Simulation")
    print("=" * 40)
    
    try:
        test_sim_basic_danish_number()
        print("✓ Basic 8-digit numbers passed")
        
        test_sim_danish_number_with_45_prefix()
        print("✓ 45+8 digits passed")
        
        test_sim_danish_number_with_plus_45()
        print("✓ +45+8 digits passed")
        
        test_sim_danish_number_with_0045()
        print("✓ 0045+8 digits passed")
        
        test_sim_danish_number_with_spaces()
        print("✓ Spaced numbers passed")
        
        print("\nAll simulation tests passed!")
        return True
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        return False

if __name__ == "__main__":
    if run_simulation():
        sys.exit(0)
    else:
        sys.exit(1)
