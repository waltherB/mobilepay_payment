# -*- coding: utf-8 -*-

from . import models
from . import controllers

def uninstall_hook(env):
    """
    Remove references to module views from the payment provider so that the
    views can be cleanly uninstalled without raising foreign key constraints.
    """
    providers = env['payment.provider'].search([('code', '=', 'mobilepay')])
    providers.write({
        'inline_form_view_id': False,
        'redirect_form_view_id': False,
        'token_inline_form_view_id': False,
        'express_checkout_form_view_id': False,
    })