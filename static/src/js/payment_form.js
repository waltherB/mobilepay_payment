/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import paymentForm from "@payment/js/payment_form";

paymentForm.include({
    async _initiatePaymentFlow(providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode === "mobilepay") {
            const input = this._getMobilePayPhoneInput();
            const value = input?.value.trim() || "";
            const formatted = this._formatPhoneNumber(value);
            if (value && !formatted) {
                this._displayErrorDialog(
                    _t("Invalid phone number"),
                    _t("Please enter a valid Danish phone number (8 digits, optionally with +45).")
                );
                this._enableButton();
                return;
            }
            if (input) {
                input.value = formatted;
            }
        }
        return this._super(...arguments);
    },

    _prepareTransactionRouteParams() {
        const params = this._super(...arguments);
        if (this.paymentContext.providerCode === "mobilepay") {
            const input = this._getMobilePayPhoneInput();
            if (input) {
                params.mobilepay_phone = input.value.trim();
            }
        }
        return params;
    },

    _getMobilePayPhoneInput() {
        const radio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        return radio && this._getInlineForm(radio)?.querySelector('[name="mobilepay_phone"]');
    },

    _formatPhoneNumber(phoneNumber) {
        if (!phoneNumber) {
            return "";
        }
        if (!/^[+\d\s().-]+$/.test(phoneNumber)) {
            return "";
        }
        let digits = phoneNumber.replace(/\D/g, "");
        if (digits.startsWith("00")) {
            digits = digits.substring(2);
        }
        if (digits.length === 8) {
            return "+45" + digits;
        }
        if (digits.startsWith("45") && digits.length === 10) {
            return "+" + digits;
        }
        if (phoneNumber.trim().startsWith("+") && digits.length >= 9 && digits.length <= 15) {
            return "+" + digits;
        }
        return "";
    },
});
