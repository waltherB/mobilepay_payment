# Checkout paymarks

The existing `mobilepay_logo.svg` is retained for DK/FI before the approved
January 2027 cutover. The following official Vipps assets were downloaded
unchanged on 2026-11-11 for their intended payment-integration use:

| File | Official asset | Source |
| --- | --- | --- |
| `vipps_orange.svg` | `Vipps_Pay_Mark_Small_RGB_290125`, NO/SE | [Download collection](https://brand.vippsmobilepay.com/share/T51tLMxebgiN4wmTffe5/assets/2859), [original SVG](https://media.ffycdn.net/eu/vipps/6ssHVp4d5qDv3yjDrogP.svg) |
| `vipps_blue.svg` | `Vipps_Pay_Mark_Small_blue`, DK/FI after cutover | [Download collection](https://brand.vippsmobilepay.com/share/ySupQsv119vEjWvszFqY/assets/5524), [original SVG](https://media.ffycdn.net/eu/vipps/hukCSfLtnZjnPQn6kZ8L.svg) |

SHA-256:

```text
69e3f60b5eb3c6f2b7213bdf5849329ec4840121da2f28c54e8e6f06ac2ca983  vipps_orange.svg
5b8936765bbd2ce164cea2bccd0410d46d537fae6def0b649eea367f40c05a4b  vipps_blue.svg
```

These are trademarks/brand assets, not newly authored artwork. Their use is
subject to [Vipps MobilePay's official brand guidelines](https://brand.vippsmobilepay.com/document/61#/branding/online/branding-in-the-checkout)
and applicable merchant terms; the addon's LGPL does not relicense trademarks.
Do not redraw, recolor, crop or distort them. Scale proportionally and retain
their built-in space; validate prominence, size and contrast in the deployed
checkout. No remote asset request is needed at checkout.

The [6 October 2026 announcement](https://vippsmobilepay.com/en-NO/news/2026/10/vipps-mobilepay-becomes-vipps-across-the-nordics)
confirms the 12 January name change: DK/FI keep blue, NO/SE keep orange.
The module gates DK/FI switching on explicit operator approval and
2027-01-12 UTC, not the browser language or customer's billing country.
