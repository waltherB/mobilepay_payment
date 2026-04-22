# -*- coding: utf-8 -*-

import os
import unittest
from odoo.tests.common import TransactionCase, tagged
from odoo.modules.module import get_module_resource

@tagged('post_install', '-at_install')
class TestLocalization(TransactionCase):
    """
    Test localization files for MobilePay.
    """

    def test_danish_translation_file_exists(self):
        """Test that the da.po file exists in i18n directory."""
        # Check if file exists in the module directory
        # We can simulate this check by verifying the file path which we know we just created
        # In a real Odoo environment, get_module_resource would be used, but here we can check the path directly
        # or use os.path.exists if we know the absolute structure.
        
        # Taking a safer approach for this environment: check specific path
        module_path = os.path.dirname(os.path.dirname(__file__))
        po_file_path = os.path.join(module_path, 'i18n', 'da.po')
        
        self.assertTrue(os.path.exists(po_file_path), "da.po file not found in i18n directory")
        
    def test_danish_translation_content(self):
        """Test that key terms are present in the translation file."""
        module_path = os.path.dirname(os.path.dirname(__file__))
        po_file_path = os.path.join(module_path, 'i18n', 'da.po')
        
        if os.path.exists(po_file_path):
            with open(po_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            self.assertIn('msgid "Phone Number"', content)
            self.assertIn('msgstr "Telefonnummer"', content)
            self.assertIn('msgid "Please enter a valid Danish phone number."', content)
            self.assertIn('msgstr "Indtast venligst et gyldigt dansk telefonnummer."', content)
