/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { PaymentForm } from "@payment/js/payment_form";

PaymentForm.include({

    /**
     * Handle MobilePay-specific payment form processing
     * @override
     */
    /**
     * Handle MobilePay-specific payment form processing
     * @override
     */
    async _processPayment(code, paymentOptionId, flow) {
        if (code !== 'mobilepay') {
            return this._super(...arguments);
        }

        // Validate phone number
        const phoneInput = document.getElementById(`mobilepay_phone_${paymentOptionId}`);
        if (phoneInput) {
            const phoneNumber = phoneInput.value;
            const formattedPhone = this._formatPhoneNumber(phoneNumber);

            if (phoneNumber && !formattedPhone) {
                this._displayError(
                    _t("Invalid phone number"),
                    _t("Please enter a valid Danish phone number.")
                );
                return;
            }

            // Update input with formatted value for visual feedback
            if (formattedPhone) {
                phoneInput.value = formattedPhone;
            }
        }

        return this._super(...arguments);
    },

    /**
     * Add MobilePay phone number to transaction context
     * @override
     */
    _prepareTransactionContext(paymentOptionId, flow) {
        const context = this._super(...arguments);
        const phoneInput = document.getElementById(`mobilepay_phone_${paymentOptionId}`);

        if (phoneInput && phoneInput.value) {
            context['mobilepay_phone'] = phoneInput.value;
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
            // Already has country code (45 + 8 digits)
            return '+' + cleaned;
        } else if (cleaned.length === 8) {
            // Add Danish country code
            return '+45' + cleaned;
        } else if (cleaned.startsWith('0045') && cleaned.length === 12) {
            // Remove leading 00 and add +
            return '+' + cleaned.substring(2);
        }

        // Fallback: If it looks like a valid international number or we can't determine,
        // we might return it as is or try to format.
        // For E.164, we need +.

        // If the original input started with + and length seems ok (e.g. 10-15 digits)
        if (phoneNumber.trim().startsWith('+') && cleaned.length >= 10) {
            return '+' + cleaned;
        }

        // If we strictly only support Danish for auto-fix:
        return ''; // Or return null to indicate invalid/unformatted
    }
});