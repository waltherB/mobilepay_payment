/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import paymentForm from "@payment/js/payment_form";

paymentForm.include({
    async _initiatePaymentFlow(providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode === "mobilepay") {
            const input = this._getMobilePayPhoneInput();
            const value = input?.value.trim() || "";
            if (value && !this._isValidMobilePayPhone(value)) {
                this._displayErrorDialog(
                    _t("Invalid phone number"),
                    _t("Enter a valid phone number, preferably with its country code, or leave it blank.")
                );
                this._enableButton();
                return;
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

    _isValidMobilePayPhone(phoneNumber) {
        const digits = phoneNumber.replace(/\D/g, "");
        // Country-dependent normalization belongs on the server, not in the browser.
        return /^\+?[0-9\s().-]+$/.test(phoneNumber) && digits.length >= 6 && digits.length <= 17;
    },
});
