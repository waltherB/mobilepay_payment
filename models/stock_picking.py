# -*- coding: utf-8 -*-

import logging
from odoo import models, _

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        """
        Extend validation to automatically capture MobilePay payments if configured
        when the picking transitions to done.
        """
        res = super(StockPicking, self)._action_done()
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
                # Use sudo() to ensure payment provider fields are accessible
                # regardless of the user context during delivery validation
                transactions = sale_order.sudo().transaction_ids.filtered(
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
                        tx.sudo()._send_capture_request()
                    except Exception as e:
                        error_msg = str(e)
                        _logger.error(
                            f"Failed to auto-capture transaction {tx.reference}: {error_msg}"
                        )
                        # Post a message on the picking so the warehouse operator
                        # sees the failure directly on the delivery order.
                        picking.message_post(
                            body=_(
                                "⚠️ MobilePay auto-capture failed for transaction %(ref)s: %(error)s\n"
                                "Please capture the payment manually or contact support.",
                                ref=tx.reference,
                                error=error_msg,
                            ),
                            message_type="notification",
                            subtype_xmlid="mail.mt_note",
                        )
