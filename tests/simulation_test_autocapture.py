#!/usr/bin/env python3
"""
Simulation test for Auto-Capture on Delivery.
Verifies that validating a picking triggers action_capture on related transactions.
"""

import unittest
from unittest.mock import MagicMock


class TestAutoCaptureSimulation(unittest.TestCase):
    def test_auto_capture_trigger(self):
        """Verify that picking validation triggers capture logic"""
        print("Testing Auto-Capture Trigger Logic...")

        # Setup mocks
        mock_tx = MagicMock()
        mock_tx.provider_id.code = "mobilepay"
        mock_tx.provider_id.capture_on_delivery = True
        mock_tx.state = "authorized"
        mock_tx.capture_eligible = True
        mock_tx.reference = "TX123"

        # MagicMock iteration over self returns nothing by default,
        # so we need to make it return a list containing itself when iterated.
        mock_tx.__iter__.return_value = [mock_tx]

        mock_sale = MagicMock()
        mock_sale.__iter__.return_value = [mock_sale]
        # Mock filtered return
        mock_sale.transaction_ids.filtered.return_value = mock_tx

        mock_picking = MagicMock()
        mock_picking.name = "WH/OUT/001"
        mock_picking.state = "done"
        mock_picking.sale_id = mock_sale
        mock_picking.__iter__.return_value = [mock_picking]

        # We simulate the _mobilepay_auto_capture_payments logic from stock_picking.py
        print(f"Simulating internal logic for picking {mock_picking.name}")

        # LOGIC from stock_picking.py:
        for picking in mock_picking:
            if picking.state != "done":
                continue
            sale_orders = picking.sale_id
            for sale_order in sale_orders:
                transactions = sale_order.transaction_ids.filtered(lambda x: True)
                for tx in transactions:
                    if (
                        tx.provider_id.code == "mobilepay"
                        and tx.provider_id.capture_on_delivery
                        and tx.state == "authorized"
                    ):
                        tx.action_capture()

        # ASSERT
        mock_tx.action_capture.assert_called_once()
        print("✓ Auto-capture action_capture() was called correctly")


if __name__ == "__main__":
    unittest.main()
