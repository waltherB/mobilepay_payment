# MobilePay / Vipps TODOs

Updated: 2026-11-11. Work remains local on `18.0`.
See [migration and acceptance evidence](MIGRATION-18.0.md).
Unchecked items are not accepted functionality or production approval.

## 1. Resume sandbox acceptance when HTTPS is available

- [ ] Choose an operator-controlled HTTPS domain/reverse proxy, or explicitly
  approve a temporary tunnel. Leave the local HTTP-only setup unchanged for now.
- [ ] Replace default administrator credentials and restrict access before
  exposing the instance. Never copy API credentials into reports or chat.
- [ ] Configure trusted TLS, proxy forwarding and the Odoo website domain/base
  URL; verify return routing from the payment browser and webhook routing from
  Vipps. Do not simulate TLS by changing a URL scheme.
- [ ] Confirm DKK prices and a Danish billing country in the actual checkout;
  verify the configured outstanding/clearing accounts and company-currency
  conversions (the disposable company remains USD).
- [ ] Use a registered Merchant Test app user. Verify the edited phone prefills
  the remote payment page; test clearing it, approval, decline and abandonment.
- [ ] Confirm approval leaves the transaction authorized until delivery.
- [ ] Validate an actual delivery; verify remote capture, Done state, posted
  accounting payment and invoice reconciliation.
- [ ] Accept or revise the existing full-first-delivery capture policy:
  partial delivery captures the entire remaining reservation, not shipment value.
- [ ] Exercise full/repeated partial captures, remaining-authorization cancel,
  full/repeated refunds, backend wizards and duplicate operations remotely.
- [ ] Confirm Danish/Finnish sales-unit partial capture is enabled by Vipps.
- [ ] Exercise delayed capture boundaries, retries, failure notifications and
  operational cron scheduling with the merchant test unit.
- [ ] Register signed webhooks through the real proxy; test duplicate/retry
  behavior, return/event ordering, polling recovery and unregistration.

## 2. Report API and accounting

- [ ] Replace the unverified legacy
  `/settlement/v1/ledgers/{ledgerId}/entries` adapter with a validated mapping
  to the published Report API v2 funds/fees date or feed endpoints.
- [ ] Establish real response schemas, reference matching, pagination/cursors,
  deduplication, late reports and rollback/retry recovery before implementation.
- [ ] Arrange separately authorized report access: Report API is production-only
  and unavailable in Merchant Test. Do not enable live customer payments merely
  to work around that restriction.
- [ ] Validate actual gross/refund/fee/VAT/net reports against payments and bank
  amounts; repeat draft/error imports without duplicate journal entries.
- [ ] Verify merchant/provider/company isolation and partial-settlement matching.
- [ ] Decide and test foreign-currency accounting; automatic settlement currently
  stops explicitly when payout and company currencies differ.
- [ ] Have an accountant approve production accounts and fee VAT treatment.

## Branding cutover: 2027-01-12

The requested rollout date is **12 January 2027**, not 1 December.
The [official checkout guidance](https://brand.vippsmobilepay.com/document/61#/branding/online/branding-in-the-checkout)
was inspected on 2026-11-11. It announces MobilePay becoming Vipps in Denmark
and Finland on "12 January"; the page text inspected does not state the year.
The 2027 rollout year is the operator's requirement. Reconfirm final rollout
instructions before release.

### Official assets located

| Resource | Located assets / purpose |
| --- | --- |
| [New logo library: Vipps Blue](https://brand.vippsmobilepay.com/document/110) | `Vipps_logo_DK-FI_blue_RGB` (PNG and vector source variants); Danish tagline and DK/FI symbol variants also listed |
| [New paymark library: Vipps Blue](https://brand.vippsmobilepay.com/document/124) | `Vipps_Pay_Mark_Small_blue`, `Vipps_Pay_Mark_Medium_blue`, `Vipps_Pay_Mark_Large_blue`, `Vipps_Pay_Mark_Name_blue`; SVG and PNG listed |
| [Checkout blue-logo download collection](https://brand.vippsmobilepay.com/share/HWHQtP2RGYMF7jyfjxFQ) | Official checkout download link; recheck selected contents before adoption |
| [Checkout blue-paymark download collection](https://brand.vippsmobilepay.com/share/ySupQsv119vEjWvszFqY) | Official checkout download link; recheck selected contents before adoption |
| [Official button assets / Figma](https://www.figma.com/community/file/1240264703803071832/vipps-buttons-logo-and-mark) | Buttons linked directly by the checkout guidance |

Asset availability and names were verified in the official libraries; no
replacement asset was downloaded, altered or installed. Some example captions
on the checkout page conflict about market/color usage: use the dedicated
DK/FI Vipps Blue libraries and reconfirm final market rules before rollout.

- [ ] Download the approved DK/FI assets from these official collections; retain
  source URL, download date, applicable usage terms and selected variant.
  Prefer official SVG paymarks where supported; never redraw/recolor the logo.
- [ ] Reconfirm market/color variants, clear space, minimum size, contrast and
  button rules. Use the same logo/paymark treatment and prominence as comparable
  payment options; do not hide Vipps behind extra selection steps.
- [ ] Prepare a reviewed cutover release for 2027-01-12; do not switch live
  customer-facing branding early or implement an unreviewed date-based toggle.
- [ ] Update checkout/provider/payment-method display names, inline text,
  accessibility/alt text, Danish translations and customer status messages.
- [ ] Replace [inline logo](static/img/mobilepay_logo.svg) and
  [Apps/provider icon](static/description/icon.svg), then check
  [templates](views/mobilepay_templates.xml), [seed data](data/payment_provider_data.xml),
  [README](README.md), manifest and [Apps description](static/description/index.html).
- [ ] Plan an explicit upgrade for existing provider/method names and database
  images: seed records are `noupdate`; asset-file edits alone will not refresh
  those records. Preserve operator customizations and retain rollback options.
- [ ] Keep technical module/provider codes, existing XML IDs, merchant references,
  credentials, transaction history and API routes stable unless upstream
  product-specific guidance requires changes. Branding is not a data rename.
- [ ] Verify no current template/image path is broken, including the Apps
  description's relative logo reference; test actual rendered images.
- [ ] Run guest/authenticated desktop/mobile checkout, image-loading and
  accessibility checks in English/Danish before and after the cutover update.
- [ ] Review the separately announced developer-documentation domain move on
  2027-01-12; refresh documentation links after verifying redirects. Do not
  infer that API server hostnames change with the brand or documentation domain.

The official announcement says existing QR material, numbers and links continue
to work unless product-specific guidance says otherwise.

## 4. Remaining production gates

- [ ] Test remote-success/local-rollback recovery without duplicate money moves.
- [ ] Review webhook work/latency against the real delivery timeout.
- [ ] Confirm reservation-deadline policy with current upstream rules.
- [ ] Review logging/privacy, normal accounting/warehouse ACLs, multi-company
  behavior, Danish localization, other payment providers and Enterprise if used.
- [ ] Run an explicitly authorized Odoo 17 database upgrade, preserving the
  encryption key/ciphertext, record IDs, relationships and accounting balances.
- [ ] Triage historical unregistered tests; do not count simulations as acceptance.
- [ ] Review the local diff before any commit; do not push/merge without approval.
- [ ] Obtain human business/accounting acceptance before enabling live payments.

## Completed local evidence

- Lifecycle, checkout-phone, journal permissions and HTTP return-URL validation
  fixes: **93 registered tests pass** on the latest update.
- Earlier fresh installation: 91 tests passed before the two follow-up tests.
- Local synthetic Chromium, signed HTTP, delivery/backorder and accounting
  acceptance passed; these do not substitute for merchant test-unit acceptance.
- Operator reports test API authentication working, provider published in
  Test Mode, and Capture on Delivery selected.
- Sandbox DKK pricelist and existing draft cart corrected; company currency
  unchanged. HTTPS remains intentionally unconfigured.
