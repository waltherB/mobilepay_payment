# -*- coding: utf-8 -*-

import logging
from odoo import models, _

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_cancel(self):
        """
        Override sale order cancellation to automatically void any MobilePay
        authorized payment reservations, releasing the customer's funds immediately.
        """
        res = super().action_cancel()
        self._mobilepay_cancel_authorized_transactions()
        return res

    def _mobilepay_cancel_authorized_transactions(self):
        """
        Cancel any MobilePay authorized transactions linked to this sale order
        so the customer's reserved funds are released promptly.
        """
        for order in self:
            # Use sudo() to access payment provider fields regardless of user ACL
            transactions = order.sudo().transaction_ids.filtered(
                lambda tx: (
                    tx.provider_id.code == "mobilepay"
                    and tx.state == "authorized"
                )
            )

            for tx in transactions:
                _logger.info(
                    "MobilePay: Cancelling authorized transaction %s because "
                    "sale order %s was cancelled.",
                    tx.reference, order.name,
                )
                try:
                    tx.sudo()._send_cancel_request()
                    tx.message_post(
                        body=_(
                            "MobilePay payment authorization automatically cancelled "
                            "because sale order %(order)s was cancelled.",
                            order=order.name,
                        ),
                        message_type="notification",
                        subtype_xmlid="mail.mt_note",
                    )
                except Exception as e:
                    _logger.error(
                        "MobilePay: Failed to cancel transaction %s after order %s "
                        "was cancelled: %s",
                        tx.reference, order.name, str(e),
                    )
                    # Post a warning so someone can act manually
                    tx.message_post(
                        body=_(
                            "⚠️ Failed to automatically cancel MobilePay payment %(ref)s "
                            "after sale order %(order)s was cancelled: %(error)s\n"
                            "Please cancel this payment manually in the MobilePay portal "
                            "to release the customer's reserved funds.",
                            ref=tx.reference,
                            order=order.name,
                            error=str(e),
                        ),
                        message_type="notification",
                        subtype_xmlid="mail.mt_note",
                    )
