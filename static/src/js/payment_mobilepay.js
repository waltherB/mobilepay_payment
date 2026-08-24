/** @odoo-module */

/**
 * MobilePay POS Payment Terminal Interface
 *
 * Integrates MobilePay/Vipps ePayment into the Odoo 17 Point of Sale as a
 * custom payment terminal supporting:
 *   - Phone Number Push  (userFlow: PUSH_MESSAGE)
 *   - QR Code display    (userFlow: QR)
 *
 * The operator can switch from push to QR mid-flight without cancelling the
 * transaction.
 */

import { PaymentInterface } from "@point_of_sale/app/payment/payment_interface";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 3000;   // poll every 3 seconds
const TERMINAL_CODE   = "mobilepay";

// ---------------------------------------------------------------------------
// Helper: JSON-RPC call to our POS controller
// ---------------------------------------------------------------------------

async function posRpc(orm, route, params) {
    return orm.call("pos.session", route.replace("/", ""), [], params, { shadow: true })
        .catch(() => {
            // Fall back to raw fetch for non-ORM routes
            return fetch(route, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jsonrpc: "2.0", method: "call", params }),
            }).then((r) => r.json()).then((r) => r.result || r.error);
        });
}

async function callPosRoute(route, params) {
    const response = await fetch(route, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method: "call", params }),
    });
    const json = await response.json();
    if (json.error) {
        throw new Error(json.error.data?.message || json.error.message || "Unknown error");
    }
    return json.result;
}

// ---------------------------------------------------------------------------
// OWL Dialogs
// ---------------------------------------------------------------------------

/**
 * Dialog asking the operator to choose Phone Push or QR Code.
 */
export class MobilePayModeDialog extends Component {
    static template = "mobilepay_payment.MobilePayModeDialog";
    static props = {
        close: Function,
        onSelectMode: Function,
    };

    selectPhonePush() {
        this.props.onSelectMode("phone_push");
        this.props.close();
    }
    selectQr() {
        this.props.onSelectMode("qr_code");
        this.props.close();
    }
}

/**
 * Dialog for capturing the customer's phone number before push payment.
 */
export class MobilePayPhoneDialog extends Component {
    static template = "mobilepay_payment.MobilePayPhoneDialog";
    static props = {
        close: Function,
        onConfirm: Function,
        prefillPhone: { type: String, optional: true },
    };

    setup() {
        this.state = useState({ phone: this.props.prefillPhone || "" });
    }

    onInput(ev) {
        this.state.phone = ev.target.value;
    }
    appendDigit(digit) {
        this.state.phone = (this.state.phone || "") + digit;
    }
    deleteLast() {
        this.state.phone = (this.state.phone || "").slice(0, -1);
    }
    confirm() {
        const phone = (this.state.phone || "").trim();
        if (!phone) { return; }
        this.props.onConfirm(phone);
        this.props.close();
    }
}

/**
 * Full-screen overlay showing QR code, countdown, and status.
 */
export class MobilePayQrDisplay extends Component {
    static template = "mobilepay_payment.MobilePayQrDisplay";
    static props = {
        close: Function,
        qrPayload: String,
        timeout: Number,
        onSwitchToPhone: Function,
        onCancel: Function,
    };

    setup() {
        this.state = useState({
            elapsed: 0,
            statusText: _t("Waiting for customer to scan…"),
        });
        this._timer = setInterval(() => {
            this.state.elapsed++;
            if (this.state.elapsed >= this.props.timeout) {
                clearInterval(this._timer);
                this.state.statusText = _t("Payment timed out.");
            }
        }, 1000);
        onWillUnmount(() => clearInterval(this._timer));
    }

    get remaining() {
        return Math.max(0, this.props.timeout - this.state.elapsed);
    }
    get qrSrc() {
        return `data:image/png;base64,${this.props.qrPayload}`;
    }

    switchToPhone() {
        this.props.onSwitchToPhone();
        this.props.close();
    }
    cancel() {
        this.props.onCancel();
        this.props.close();
    }
}

// ---------------------------------------------------------------------------
// PaymentMobilePay — main PaymentInterface subclass
// ---------------------------------------------------------------------------

export class PaymentMobilePay extends PaymentInterface {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        // Per-line state keyed by clientId
        this._state = {};
    }

    // ------------------------------------------------------------------
    // PaymentInterface overrides
    // ------------------------------------------------------------------

    /**
     * Called when the operator confirms the MobilePay payment line amount.
     * Determines which mode to use, then initiates the payment.
     */
    async sendPaymentRequest(cid) {
        const line = this._getLine(cid);
        if (!line) { return false; }

        const defaultMode = this._getDefaultMode();

        if (defaultMode === "phone_push") {
            return this._promptPhoneAndInitiate(line);
        }
        if (defaultMode === "qr_code") {
            return this._initiateQr(line);
        }
        // "prompt" — show mode selection dialog
        return this._showModeDialog(line);
    }

    /**
     * Called when the operator explicitly cancels the payment.
     */
    async sendPaymentCancel(order, cid) {
        const st = this._state[cid];
        this._stopPolling(cid);
        if (st?.paymentId) {
            try {
                await callPosRoute("/mobilepay/pos/cancel_payment", {
                    pos_session_id: this.pos.pos_session.id,
                    payment_id: st.paymentId,
                });
            } catch (e) {
                console.warn("MobilePay POS: cancel_payment failed:", e);
            }
        }
        this._clearState(cid);
        return true;
    }

    // ------------------------------------------------------------------
    // Mode selection dialog
    // ------------------------------------------------------------------

    _showModeDialog(line) {
        return new Promise((resolve) => {
            this.dialogService.add(MobilePayModeDialog, {
                onSelectMode: async (mode) => {
                    let ok;
                    if (mode === "phone_push") {
                        ok = await this._promptPhoneAndInitiate(line);
                    } else {
                        ok = await this._initiateQr(line);
                    }
                    resolve(ok);
                },
            });
        });
    }

    // ------------------------------------------------------------------
    // Phone push flow
    // ------------------------------------------------------------------

    _promptPhoneAndInitiate(line) {
        const partner = this.pos.get_order()?.get_partner();
        const prefillPhone = partner?.phone || partner?.mobile || "";

        return new Promise((resolve) => {
            this.dialogService.add(MobilePayPhoneDialog, {
                prefillPhone,
                onConfirm: async (phone) => {
                    const ok = await this._initiatePhonePush(line, phone);
                    resolve(ok);
                },
            });
        });
    }

    async _initiatePhonePush(line, phone) {
        const cid = line.cid;
        try {
            const result = await this._callInitiate(line, "phone_push", phone);
            if (result.error) {
                this._handleFailure(line, result.error);
                return false;
            }
            this._setState(cid, { paymentId: result.payment_id, mode: "phone_push" });
            this._setLineStatus(line, _t("Push notification sent. Waiting for authorization…"));
            this._startPolling(cid, line, result.timeout || 60);
            return true;
        } catch (e) {
            this._handleFailure(line, e.message);
            return false;
        }
    }

    // ------------------------------------------------------------------
    // QR code flow
    // ------------------------------------------------------------------

    async _initiateQr(line) {
        const cid = line.cid;
        try {
            const result = await this._callInitiate(line, "qr_code");
            if (result.error) {
                this._handleFailure(line, result.error);
                return false;
            }
            const timeout = result.timeout || 60;
            this._setState(cid, { paymentId: result.payment_id, mode: "qr_code" });
            this._showQrDialog(line, result.qr_payload, timeout);
            this._startPolling(cid, line, timeout);
            return true;
        } catch (e) {
            this._handleFailure(line, e.message);
            return false;
        }
    }

    _showQrDialog(line, qrPayload, timeout) {
        this.dialogService.add(MobilePayQrDisplay, {
            qrPayload,
            timeout,
            onSwitchToPhone: () => this._switchToPhone(line),
            onCancel: () => this.sendPaymentCancel(null, line.cid),
        });
    }

    // ------------------------------------------------------------------
    // Mid-flight mode switch: QR → Phone
    // ------------------------------------------------------------------

    async _switchToPhone(line) {
        // Keep the same paymentId; just stop QR polling and restart after
        // the operator enters the phone number.  The existing payment session
        // on the Vipps side accepts a push after creation.
        this._stopPolling(line.cid);
        await this._promptPhoneAndInitiate(line);
    }

    // ------------------------------------------------------------------
    // Mid-flight mode switch: Phone → QR  (called from QR display button)
    // ------------------------------------------------------------------

    async _switchToQr(line) {
        const st = this._state[line.cid];
        if (!st?.paymentId) { return; }
        this._stopPolling(line.cid);

        try {
            const result = await callPosRoute("/mobilepay/pos/get_qr", {
                pos_session_id: this.pos.pos_session.id,
                payment_id: st.paymentId,
            });
            if (result.error || !result.qr_payload) {
                this._handleFailure(line, result.error || _t("Could not retrieve QR code."));
                return;
            }
            const timeout = this._getConfiguredTimeout();
            this._setState(line.cid, { mode: "qr_code" });
            this._showQrDialog(line, result.qr_payload, timeout);
            this._startPolling(line.cid, line, timeout);
        } catch (e) {
            this._handleFailure(line, e.message);
        }
    }

    // ------------------------------------------------------------------
    // Polling
    // ------------------------------------------------------------------

    _startPolling(cid, line, timeoutSeconds) {
        this._stopPolling(cid);
        let elapsed = 0;

        const timer = setInterval(async () => {
            elapsed += POLL_INTERVAL_MS / 1000;

            if (elapsed >= timeoutSeconds) {
                this._stopPolling(cid);
                await this.sendPaymentCancel(null, cid);
                this._handleFailure(line, _t("Payment timed out. Please try again."));
                return;
            }

            try {
                const st = this._state[cid];
                if (!st?.paymentId) {
                    this._stopPolling(cid);
                    return;
                }
                const result = await callPosRoute("/mobilepay/pos/check_status", {
                    pos_session_id: this.pos.pos_session.id,
                    payment_id: st.paymentId,
                });

                if (result.error) {
                    // Non-fatal transient error — keep polling
                    console.warn("MobilePay POS poll error:", result.error);
                    return;
                }

                if (result.status === "AUTHORIZED" || result.status === "CAPTURED") {
                    this._stopPolling(cid);
                    this._resolvePayment(line, result.amount);
                } else if (
                    result.status === "CANCELLED" ||
                    result.status === "EXPIRED"
                ) {
                    this._stopPolling(cid);
                    this._handleFailure(line, _t("Payment was cancelled or expired."));
                }
                // CREATED — still pending, keep polling
            } catch (e) {
                console.warn("MobilePay POS: polling error:", e);
            }
        }, POLL_INTERVAL_MS);

        this._setState(cid, { pollingTimer: timer });
    }

    _stopPolling(cid) {
        const st = this._state[cid];
        if (st?.pollingTimer) {
            clearInterval(st.pollingTimer);
            this._setState(cid, { pollingTimer: null });
        }
    }

    // ------------------------------------------------------------------
    // Resolution & failure
    // ------------------------------------------------------------------

    _resolvePayment(line, confirmedAmount) {
        // Mark the payment line as approved
        line.payment_status = "done";
        if (confirmedAmount != null) {
            // Convert minor units back to major (e.g. øre → DKK)
            line.amount = confirmedAmount / 100;
        }
        this._clearState(line.cid);
        this.pos.showScreen("ReceiptScreen");
    }

    _handleFailure(line, reason) {
        line.payment_status = "retry";
        this._clearState(line.cid);
        this.pos.env.services.notification.add(
            reason || _t("MobilePay payment failed."),
            { type: "danger", sticky: false }
        );
    }

    _setLineStatus(line, text) {
        line.payment_status = "waitingCard";
        if (line.set_payment_status) {
            line.set_payment_status("waitingCard");
        }
    }

    // ------------------------------------------------------------------
    // API call helpers
    // ------------------------------------------------------------------

    async _callInitiate(line, paymentMode, phoneNumber = null) {
        const order = this.pos.get_order();
        const currency = this.pos.currency?.name || "DKK";
        // Amount in minor units
        const amountMinor = Math.round(line.amount * 100);

        const params = {
            pos_session_id: this.pos.pos_session.id,
            amount: amountMinor,
            currency,
            pos_reference: order.name || `POS-${Date.now()}`,
            payment_mode: paymentMode,
        };
        if (phoneNumber) {
            params.phone_number = phoneNumber;
        }

        return callPosRoute("/mobilepay/pos/initiate_payment", params);
    }

    // ------------------------------------------------------------------
    // State helpers
    // ------------------------------------------------------------------

    _getLine(cid) {
        return this.pos.get_order()?.paymentlines.find((l) => l.cid === cid) || null;
    }

    _getDefaultMode() {
        const method = this.payment_method;
        return method?.mobilepay_pos_default_mode || "prompt";
    }

    _getConfiguredTimeout() {
        return this.payment_method?.mobilepay_pos_timeout || 60;
    }

    _setState(cid, patch) {
        this._state[cid] = Object.assign(this._state[cid] || {}, patch);
    }

    _clearState(cid) {
        delete this._state[cid];
    }
}

// Register the terminal with the POS payment terminal registry
registry
    .category("pos_payment_method_adapters")
    .add(TERMINAL_CODE, PaymentMobilePay);
