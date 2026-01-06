#!/usr/bin/env python3
"""
Simulation test for JS phone formatting logic.
Transcribed JS logic into Python to verify correctness.
"""

import sys
import re

def js_format_phone_number(phone_number):
    if not phone_number:
        return ''
    
    # Remove all non-digit characters
    cleaned = re.sub(r'\D', '', phone_number)
    
    # Handle Danish phone numbers
    if cleaned.startswith('45') and len(cleaned) == 10:
        # Already has country code (45 + 8 digits)
        return '+' + cleaned
    elif len(cleaned) == 8:
        # Add Danish country code
         return '+45' + cleaned
    elif cleaned.startswith('0045') and len(cleaned) == 12:
         # Remove leading 00 and add +
         return '+' + cleaned[2:]
    
    # Fallback
    if phone_number.strip().startswith('+') and len(cleaned) >= 10:
         return '+' + cleaned
    
    return ''

def test_js_logic():
    print("Testing JS Logic Simulation")
    print("=" * 40)
    
    cases = [
        ('12345678', '+4512345678'),
        ('4512345678', '+4512345678'),
        ('004512345678', '+4512345678'),
        ('+45 12 34 56 78', '+4512345678'),
    ]
    
    success = True
    for input_val, expected in cases:
        result = js_format_phone_number(input_val)
        if result == expected:
            print(f"✓ {input_val} -> {result}")
        else:
            print(f"✗ {input_val} -> {result} (Expected {expected})")
            success = False
            
    return success

if __name__ == "__main__":
    if test_js_logic():
        print("\nAll JS logic tests passed!")
        sys.exit(0)
    else:
        sys.exit(1)
