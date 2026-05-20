#!/usr/bin/env python3
"""
Simulation test for localization files.
Checks for existence of da.po and specific translation keys.
"""

import sys
import os

def test_localization():
    print("Testing Localization")
    print("=" * 40)
    
    # Path relative to script execution
    po_file_path = 'mobilepay_payment/i18n/da.po'
    if not os.path.exists(po_file_path):
        po_file_path = 'i18n/da.po'
        
    # 1. Check file existence
    if os.path.exists(po_file_path):
        print(f"✓ File exists: {po_file_path}")
    else:
        print(f"✗ File missing: {po_file_path} (also checked mobilepay_payment/i18n/da.po)")
        return False
        
    # 2. Check content
    try:
        with open(po_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        required_strings = [
            'msgid "Phone Number"',
            'msgstr "Telefonnummer"',
            'msgid "Please enter a valid Danish phone number."',
            'msgstr "Indtast venligst et gyldigt dansk telefonnummer."'
        ]
        
        all_found = True
        for s in required_strings:
            if s in content:
                print(f"✓ Found translation key: {s[:30]}...")
            else:
                print(f"✗ Missing translation key: {s}")
                all_found = False
                
        if all_found:
            return True
        else:
            return False
            
    except Exception as e:
        print(f"✗ Error reading file: {e}")
        return False

if __name__ == "__main__":
    if test_localization():
        print("\nAll localization tests passed!")
        sys.exit(0)
    else:
        sys.exit(1)
