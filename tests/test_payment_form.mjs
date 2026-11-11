import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const source = readFileSync(
    new URL("../static/src/js/payment_form.js", import.meta.url), "utf8"
).replace(/^import .*;$/gm, "");
let extension;
vm.runInNewContext(source, {
    _t: (text) => text,
    paymentForm: { include: (methods) => { extension = methods; } },
});

function form(phone, provider = "mobilepay") {
    const input = { value: phone };
    const calls = { inherited: 0, errors: 0, enabled: 0 };
    return {
        ...extension,
        input,
        calls,
        paymentContext: { providerCode: provider },
        _getMobilePayPhoneInput: () => input,
        _super: () => { calls.inherited++; return { access_token: "synthetic-token" }; },
        _displayErrorDialog: () => { calls.errors++; },
        _enableButton: () => { calls.enabled++; },
    };
}

test("Nordic local and international numbers reach the server without a Danish rewrite", async () => {
    for (const phone of [
        "12345678", "91234567", "0401234567", "0701234567", "123456",
        "+45 12345678", "+47 91234567", "+358 401234567", "+46 701234567",
        "+299 123456", "004791234567", "",
    ]) {
        const paymentForm = form(phone);
        await paymentForm._initiatePaymentFlow("mobilepay", 1, "mobilepay", "redirect");
        assert.equal(paymentForm.calls.errors, 0, phone);
        assert.equal(paymentForm.calls.inherited, 1, phone);
        assert.equal(paymentForm.input.value, phone);
        const params = paymentForm._prepareTransactionRouteParams();
        assert.equal(params.mobilepay_phone, phone);
        assert.equal(params.access_token, "synthetic-token");
    }
});

test("invalid characters and lengths recover the payment button without initiating", async () => {
    for (const phone of ["call12345678", "12+3456789", "++4512345678", "１２３４５６７８",
                         "123", "+123456789012345678"]) {
        const paymentForm = form(phone);
        await paymentForm._initiatePaymentFlow("mobilepay", 1, "mobilepay", "redirect");
        assert.equal(paymentForm.calls.inherited, 0, phone);
        assert.equal(paymentForm.calls.errors, 1, phone);
        assert.equal(paymentForm.calls.enabled, 1, phone);
    }
});

test("trimming or clearing the optional phone is explicit", () => {
    for (const [phone, expected] of [["  +46 701234567  ", "+46 701234567"], ["  ", ""]]) {
        const paymentForm = form(phone);
        assert.equal(paymentForm._prepareTransactionRouteParams().mobilepay_phone, expected);
    }
});

test("other payment providers are unaffected", async () => {
    const paymentForm = form("not-a-phone", "other");
    await paymentForm._initiatePaymentFlow("other", 1, "other", "redirect");
    assert.equal(paymentForm.calls.inherited, 1);
    assert.equal(paymentForm.calls.errors, 0);
    assert.equal(paymentForm._prepareTransactionRouteParams().mobilepay_phone, undefined);
});

test("phone lookup stays scoped to the selected payment option", () => {
    const input = { value: "+4791234567" };
    const radio = {};
    const paymentForm = {
        ...extension,
        el: {
            querySelector: (selector) => {
                assert.equal(selector, 'input[name="o_payment_radio"]:checked');
                return radio;
            },
        },
        _getInlineForm: (selected) => {
            assert.equal(selected, radio);
            return {
                querySelector: (selector) => {
                    assert.equal(selector, '[name="mobilepay_phone"]');
                    return input;
                },
            };
        },
    };
    assert.equal(paymentForm._getMobilePayPhoneInput(), input);
});
