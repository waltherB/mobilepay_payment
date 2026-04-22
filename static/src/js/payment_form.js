/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import paymentForm from "@payment/js/payment_form";

console.log("MobilePay: payment_form.js extension active");

paymentForm.include({

    /**
     * Handle MobilePay-specific payment form processing
     * @override
     */
    async _processPayment(code, paymentOptionId, flow) {
        console.log("MobilePay: _processPayment", { code, paymentOptionId, flow });

        if (code !== 'mobilepay') {
            return this._super(...arguments);
        }

        try {
            // Validate phone number
            const phoneInput = document.getElementById(`mobilepay_phone_${paymentOptionId}`);
            if (phoneInput) {
                const phoneNumber = phoneInput.value;
                const formattedPhone = this._formatPhoneNumber(phoneNumber);
                console.log("MobilePay: Phone validation result", { original: phoneNumber, formatted: formattedPhone });

                if (phoneNumber && !formattedPhone) {
                    this._displayError(
                        _t("Invalid phone number"),
                        _t("Please enter a valid Danish phone number (8 digits, optionally with +45).")
                    );
                    return; // Stop processing and wait for user to fix
                }

                // Update input with formatted value for visual feedback
                if (formattedPhone) {
                    phoneInput.value = formattedPhone;
                }
            } else {
                console.warn(`MobilePay: Phone input 'mobilepay_phone_${paymentOptionId}' not found in DOM`);
            }
        } catch (err) {
            console.error("MobilePay: Error in _processPayment logic", err);
            // We don't return here so that the super call still happens
        }

        return this._super(...arguments);
    },

    /**
     * Add MobilePay phone number to transaction context
     * @override
     */
    _prepareTransactionContext(paymentOptionId, flow) {
        console.log("MobilePay: _prepareTransactionContext", { paymentOptionId, flow });
        const context = this._super(...arguments);

        try {
            const phoneInput = document.getElementById(`mobilepay_phone_${paymentOptionId}`);
            if (phoneInput && phoneInput.value) {
                context['mobilepay_phone'] = phoneInput.value;
                console.log("MobilePay: Phone added to context", phoneInput.value);
            }
        } catch (err) {
            console.error("MobilePay: Error in _prepareTransactionContext logic", err);
        }

        return context;
    },

    /**
     * Format phone number for MobilePay pre-fill
     * @private
     * @param {string} phoneNumber - Raw phone number
     * @returns {string} - Formatted phone number in E.164 format
     */
    _formatPhoneNumber(phoneNumber) {
        if (!phoneNumber) {
            return '';
        }

        // Remove all non-digit characters
        let cleaned = phoneNumber.replace(/\D/g, '');

        // Handle Danish phone numbers
        if (cleaned.startsWith('45') && cleaned.length === 10) {
            return '+' + cleaned;
        } else if (cleaned.length === 8) {
            return '+45' + cleaned;
        } else if (cleaned.startsWith('0045') && cleaned.length === 12) {
            return '+' + cleaned.substring(2);
        }

        // Fallback for international
        if (phoneNumber.trim().startsWith('+') && cleaned.length >= 10) {
            return '+' + cleaned;
        }

        return '';
    }
});