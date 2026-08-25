/** @odoo-module */

/**
 * MobilePay POS Payment Terminal Interface — Odoo 17 CE compatible
 *
 * Registration:  register_payment_method("mobilepay", PaymentMobilePay)
 * Base class:    PaymentInterface  (plain JS class, NOT an OWL component)
 * Popup system:  this.env.services.popup  (POS popup service)
 * Method names:  snake_case  (send_payment_request / send_payment_cancel)
 */

import { PaymentInterface } from "@point_of_sale/app/payment/payment_interface";
import { register_payment_method } from "@point_of_sale/app/store/pos_store";
import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, onWillUnmount } from "@odoo/owl";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 3000; // poll every 3 seconds

// ---------------------------------------------------------------------------
// JSON-RPC helper — plain fetch, no OWL services needed
// ---------------------------------------------------------------------------

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
// POS Popups  (AbstractAwaitablePopup — resolved via this.env.services.popup)
// ---------------------------------------------------------------------------

/**
 * Popup: operator chooses Phone Push or QR Code.
 * Resolves with { confirmed: true, payload: "phone_push" | "qr_code" }
 */
export class MobilePayModePopup extends AbstractAwaitablePopup {
    static template = "mobilepay_payment.MobilePayModePopup";
    static defaultProps = { title: _t("MobilePay — Choose Payment Mode") };

    async selectPhonePush() {
        this.props.resolve({ confirmed: true, payload: "phone_push" });
        this.props.close();
    }
    async selectQr() {
        this.props.resolve({ confirmed: true, payload: "qr_code" });
        this.props.close();
    }
}

/**
 * Popup: captures the customer's phone number.
 * Resolves with { confirmed: true, payload: "<phone>" } or { confirmed: false }
 */
export class MobilePayPhonePopup extends AbstractAwaitablePopup {
    static template = "mobilepay_payment.MobilePayPhonePopup";
    static defaultProps = { title: _t("MobilePay — Enter Phone Number"), prefillPhone: "" };

    setup() {
        super.setup();
        this.state = useState({ phone: this.props.prefillPhone || "" });
    }

    appendDigit(digit) {
        this.state.phone = (this.state.phone || "") + digit;
    }
    deleteLast() {
        this.state.phone = (this.state.phone || "").slice(0, -1);
    }
    async confirm() {
        const phone = (this.state.phone || "").trim();
        if (!phone) { return; }
        this.props.resolve({ confirmed: true, payload: phone });
        this.props.close();
    }
    async cancel() {
        this.props.resolve({ confirmed: false, payload: null });
        this.props.close();
    }
}

/**
 * Popup: displays QR code with countdown, and switch/cancel actions.
 * Does NOT resolve automatically — the polling loop drives resolution externally.
 * Closed programmatically when the payment resolves/fails/times out.
 */
export class MobilePayQrPopup extends AbstractAwaitablePopup {
    static template = "mobilepay_payment.MobilePayQrPopup";
    static defaultProps = {
        title: _t("MobilePay — Scan to Pay"),
        qrPayload: "",
        timeout: 60,
        onSwitchToPhone: null,
        onCancel: null,
    };

    setup() {
        super.setup();
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

    async switchToPhone() {
        if (this.props.onSwitchToPhone) { this.props.onSwitchToPhone(); }
        this.props.close();
    }
    async cancelPayment() {
        if (this.props.onCancel) { this.props.onCancel(); }
        this.props.close();
    }
}

// ---------------------------------------------------------------------------
// PaymentMobilePay — PaymentInterface subclass (plain JS class, not OWL)
// ---------------------------------------------------------------------------

export class PaymentMobilePay extends PaymentInterface {
    /**
     * Called by PosStore as: new PaymentMobilePay(pos, payment_method)
     * super.setup sets: this.env, this.pos, this.payment_method
     */
    setup(...args) {
        super.setup(...args);
        // Per-line state keyed by clientId
        this._state = {};
        // Reference to the open QR popup close function (for programmatic close)
        this._qrPopupClose = null;
    }

    // ------------------------------------------------------------------
    // PaymentInterface overrides (snake_case — Odoo 17 convention)
    // ------------------------------------------------------------------

    /**
     * Called by the POS payment screen when the operator confirms the amount.
     * Must return a Promise that resolves to true (success) or false (failure).
     */
    async send_payment_request(cid) {
        const line = this._getLine(cid);
        if (!line) { return false; }

        const defaultMode = this._getDefaultMode();

        if (defaultMode === "phone_push") {
            return this._promptPhoneAndInitiate(line);
        }
        if (defaultMode === "qr_code") {
            return this._initiateQr(line);
        }
        // "prompt" — ask operator
        return this._showModePopupAndInitiate(line);
    }

    /**
     * Called when the operator presses Cancel on the payment screen.
     * Must return a Promise that resolves to true.
     */
    async send_payment_cancel(order, cid) {
        const st = this._state[cid];
        this._stopPolling(cid);
        this._closeQrPopup();

        if (st?.paymentId) {
            try {
                await callPosRoute("/mobilepay/pos/cancel_payment", {
                    pos_session_id: this.pos.pos_session.id,
                    payment_id: st.paymentId,
                });
            } catch (e) {
                console.warn("MobilePay POS: cancel_payment API call failed:", e);
            }
        }
        this._clearState(cid);
        return true;
    }

    // ------------------------------------------------------------------
    // Mode selection popup
    // ------------------------------------------------------------------

    async _showModePopupAndInitiate(line) {
        const { confirmed, payload: mode } = await this.env.services.popup.add(
            MobilePayModePopup, {}
        );
        if (!confirmed) { return false; }

        if (mode === "phone_push") {
            return this._promptPhoneAndInitiate(line);
        }
        return this._initiateQr(line);
    }

    // ------------------------------------------------------------------
    // Phone push flow
    // ------------------------------------------------------------------

    async _promptPhoneAndInitiate(line) {
        const partner = this.pos.get_order?.()?.get_partner?.();
        const prefillPhone = partner?.phone || partner?.mobile || "";

        const { confirmed, payload: phone } = await this.env.services.popup.add(
            MobilePayPhonePopup, { prefillPhone }
        );
        if (!confirmed || !phone) { return false; }

        return this._initiatePhonePush(line, phone);
    }

    async _initiatePhonePush(line, phone) {
        try {
            const result = await this._callInitiate(line, "phone_push", phone);
            if (result.error) {
                this._showError(result.error);
                return false;
            }
            this._setState(line.cid, { paymentId: result.payment_id, mode: "phone_push" });
            line.set_payment_status("waitingCard");
            return await this._waitForPolling(line, result.timeout || 60);
        } catch (e) {
            this._showError(e.message);
            return false;
        }
    }

    // ------------------------------------------------------------------
    // QR code flow
    // ------------------------------------------------------------------

    async _initiateQr(line) {
        try {
            const result = await this._callInitiate(line, "qr_code");
            if (result.error) {
                this._showError(result.error);
                return false;
            }
            const timeout = result.timeout || 60;
            this._setState(line.cid, { paymentId: result.payment_id, mode: "qr_code" });
            this._openQrPopup(line, result.qr_payload, timeout);
            return await this._waitForPolling(line, timeout);
        } catch (e) {
            this._showError(e.message);
            return false;
        }
    }

    _openQrPopup(line, qrPayload, timeout) {
        const closeRef = {};
        this.env.services.popup.add(MobilePayQrPopup, {
            qrPayload,
            timeout,
            onSwitchToPhone: () => this._switchToPhone(line),
            onCancel: () => this.send_payment_cancel(null, line.cid),
            // AbstractAwaitablePopup provides this.props.close via the service
        }).then(({ close }) => {
            closeRef.fn = close;
        }).catch(() => {});
        // Store a close handle on the instance for programmatic closing
        this._qrPopupClose = () => {
            if (closeRef.fn) { closeRef.fn(); }
        };
    }

    _closeQrPopup() {
        if (this._qrPopupClose) {
            try { this._qrPopupClose(); } catch (_) {}
            this._qrPopupClose = null;
        }
    }

    // ------------------------------------------------------------------
    // Mid-flight mode switch: QR → Phone
    // ------------------------------------------------------------------

    async _switchToPhone(line) {
        this._stopPolling(line.cid);
        // _waitForPolling is already awaiting; switching re-initiates it
        await this._promptPhoneAndInitiate(line);
    }

    // ------------------------------------------------------------------
    // Polling — returns Promise<bool> that resolves when payment is done
    // ------------------------------------------------------------------

    _waitForPolling(line, timeoutSeconds) {
        return new Promise((resolve) => {
            let elapsed = 0;
            const cid = line.cid;

            const timer = setInterval(async () => {
                elapsed += POLL_INTERVAL_MS / 1000;

                if (elapsed >= timeoutSeconds) {
                    this._stopPolling(cid);
                    this._closeQrPopup();
                    await this.send_payment_cancel(null, cid);
                    this._showError(_t("Payment timed out. Please try again."));
                    resolve(false);
                    return;
                }

                const st = this._state[cid];
                if (!st?.paymentId) {
                    this._stopPolling(cid);
                    resolve(false);
                    return;
                }

                try {
                    const result = await callPosRoute("/mobilepay/pos/check_status", {
                        pos_session_id: this.pos.pos_session.id,
                        payment_id: st.paymentId,
                    });

                    if (result.error) {
                        // Transient error — keep polling
                        console.warn("MobilePay POS poll error:", result.error);
                        return;
                    }

                    if (result.status === "AUTHORIZED" || result.status === "CAPTURED") {
                        this._stopPolling(cid);
                        this._closeQrPopup();
                        this._resolvePayment(line, result.amount);
                        resolve(true);
                    } else if (result.status === "CANCELLED" || result.status === "EXPIRED") {
                        this._stopPolling(cid);
                        this._closeQrPopup();
                        this._clearState(cid);
                        this._showError(_t("Payment was cancelled or expired."));
                        resolve(false);
                    }
                    // CREATED — still pending, keep polling
                } catch (e) {
                    console.warn("MobilePay POS: polling fetch error:", e);
                }
            }, POLL_INTERVAL_MS);

            this._setState(cid, { pollingTimer: timer, resolvePolling: resolve });
        });
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

    _resolvePayment(line, confirmedAmountMinor) {
        if (confirmedAmountMinor != null) {
            line.amount = confirmedAmountMinor / 100;
        }
        line.set_payment_status("done");
        this._clearState(line.cid);
    }

    _showError(message) {
        this.env.services.popup.add(
            // ErrorPopup is a built-in POS popup
            // eslint-disable-next-line no-undef
            (window.__mobilepayErrorPopup ||
                // Lazy import fallback: use a simple notification if ErrorPopup is unavailable
                class extends AbstractAwaitablePopup {
                    static template = "mobilepay_payment.MobilePayErrorPopup";
                    static defaultProps = { title: _t("MobilePay Error"), body: "" };
                }),
            { title: _t("MobilePay Error"), body: message || _t("An unknown error occurred.") }
        );
    }

    // ------------------------------------------------------------------
    // API helpers
    // ------------------------------------------------------------------

    async _callInitiate(line, paymentMode, phoneNumber = null) {
        const order = this.pos.get_order?.();
        const currency = this.pos.currency?.name || "DKK";
        const amountMinor = Math.round(line.amount * 100);
        const params = {
            pos_session_id: this.pos.pos_session.id,
            amount: amountMinor,
            currency,
            pos_reference: order?.name || `POS-${Date.now()}`,
            payment_mode: paymentMode,
        };
        if (phoneNumber) { params.phone_number = phoneNumber; }
        return callPosRoute("/mobilepay/pos/initiate_payment", params);
    }

    // ------------------------------------------------------------------
    // State helpers
    // ------------------------------------------------------------------

    _getLine(cid) {
        return this.pos.get_order?.()?.paymentlines?.find((l) => l.cid === cid) || null;
    }

    _getDefaultMode() {
        return this.payment_method?.mobilepay_pos_default_mode || "prompt";
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

// ---------------------------------------------------------------------------
// Register with the Odoo 17 POS store
// The key "mobilepay" must match the use_payment_terminal selection value.
// ---------------------------------------------------------------------------
register_payment_method("mobilepay", PaymentMobilePay);
