# -*- coding: utf-8 -*-

import logging
from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):
        """
        Extend validation to automatically capture MobilePay payments if configured.
        """
        res = super(StockPicking, self).button_validate()

        # Ensure the picking is validated successfully
        if res is True or (isinstance(res, dict) and not res.get("res_model")):
            self._mobilepay_auto_capture_payments()

        return res

    def _mobilepay_auto_capture_payments(self):
        """Find and capture MobilePay authorized transactions related to this picking."""
        for picking in self:
            if picking.state != "done":
                continue

            # Find related Sale Orders
            sale_orders = picking.sale_id
            if not sale_orders:
                continue

            for sale_order in sale_orders:
                # Find authorized MobilePay transactions
                transactions = sale_order.transaction_ids.filtered(
                    lambda tx: (
                        tx.provider_id.code == "mobilepay"
                        and tx.provider_id.capture_on_delivery
                        and tx.state == "authorized"
                        and tx.capture_eligible
                    )
                )

                for tx in transactions:
                    try:
                        _logger.info(
                            f"Auto-capturing MobilePay transaction {tx.reference} for picking {picking.name}"
                        )
                        tx.action_capture()
                    except Exception as e:
                        _logger.error(
                            f"Failed to auto-capture transaction {tx.reference}: {str(e)}"
                        )
