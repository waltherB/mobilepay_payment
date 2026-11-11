# MobilePay (Vipps) Payment Provider for Odoo 18

Development integration with the Vipps MobilePay ePayment API. The client calls
`/epayment/v1`, `/webhooks/v1`, and `/settlement/v1` endpoints.

**Status: not production-ready.** Version `18.0.1.2.0` has 111 passing Odoo 18
tests plus 5 frontend regressions, extending the earlier 93-test baseline with
Nordic market and localization coverage. Earlier local Chromium checkout
acceptance used synthetic API responses.
The demonstrated lifecycle/phone gaps are repaired. No live merchant API,
MobilePay app approval, or public reverse-proxy delivery has been accepted.
The legacy settlement API adapter remains blocked by a published-contract mismatch.

See the [migration report](MIGRATION-18.0.md) for evidence, unresolved issues,
and required acceptance tests, and the prioritized [TODO list](TODO.md).

### Current sandbox status (2026-11-11)

The operator reports successful test API authentication, a published provider
in Test Mode, and Capture on Delivery selected. The isolated test website now
has a DKK pricelist; its existing draft cart was recalculated in DKK without
changing the company's USD accounting currency.

Testing is intentionally paused at the HTTPS prerequisite. The local instance
is HTTP-only; payment creation now stops with an explicit HTTPS setup message.
No tunnel or public endpoint has been configured. Authentication success does
not prove payment approval, capture or webhook delivery. Phone forwarding in
Test Mode is regression-tested but not yet accepted on the remote payment page.

### Branding cutover: 12 January 2027

The official checkout guidance announces MobilePay becoming **Vipps** in Denmark
and Finland on 12 January. Track the requested **2027-01-12** rollout in the
[branding TODOs](TODO.md#branding-cutover-2027-01-12). The new **Vipps Blue**
logo and SVG paymark libraries are available; official links and asset names
are recorded there. No assets, display names or technical identifiers have
been changed for this future cutover.

## What is implemented

| Surface | Current evidence |
| --- | --- |
| Test/production credentials and Fernet encryption | Credential write/read and production validation tested |
| OAuth token acquisition, caching, and API headers | Mocked token acquisition and Odoo 18 headers tested |
| Payment creation and redirect form | Tested with a mocked ePayment response |
| Authorization and capture status processing | Tested with synthetic status aggregates |
| Full / repeated partial capture | Confirmed aggregates, capture children and real invoice/payment posting tested |
| Backend void / cancellation | Real Odoo void hook; cancels all remaining reservation, including after partial capture |
| Refunds | Negative children, repeated partial refunds, actual backend wizard and outbound payments tested |
| Capture on delivery | Real picking validation, backorder wizard, duplicate and failure paths tested |
| Capture after a delay | Five-minute cron; delay boundary, repeat runs and failure isolation tested |
| Webhooks, return route, status polling | Signed HTTP events, tampering, duplicate delivery, retry responses and return tested locally |
| Checkout phone input | Real guest/authenticated browser editing, clearing, invalid input and button recovery tested |
| Settlement and fee entries | Actual clearing reconciliation, refunds, net/fee/VAT balances, draft/error retry tested with synthetic reports; remote API adapter not accepted |
| Nordic availability | DK, FI, NO, SE, GL and FO customers; merchant-region currency enforcement |
| Localization | English source; Danish, Finnish, Norwegian Bokmal and Swedish catalogs |

No POS terminal integration is included in this branch.

## Installation

- Target: **Odoo 18**. Community was tested locally; Enterprise was not tested.
- Odoo dependencies: `payment`, `account`, `website_sale`, `stock`, `sale_stock`, `sale`.
- Python dependencies: `requests`, `cryptography`.

Install missing Python dependencies into the Odoo runtime using your deployment's
dependency-management process, not into an unrelated host Python environment.
Both dependencies were available in the local test image.

1. Put this addon on the Odoo addons path and restart Odoo.
2. Activate developer mode, update the Apps list, and install
   **MobilePay (Vipps) Payment Provider**.
3. Keep the provider disabled until the blockers in the migration report are
   resolved and test-environment acceptance is complete.

## Configuration for later sandbox acceptance

1. Obtain **test** Client ID, Client Secret, Subscription Key, and Merchant Serial
   Number from the [Vipps MobilePay portal](https://portal.vippsmobilepay.com/).
2. Open **Accounting > Configuration > Payment Providers > Vipps / MobilePay**
   (or your customized provider name).
   Enter the test credentials and select **Test Mode**, not Enabled.
   Set **Sales Unit Region** to the region registered for those credentials:
   Denmark (DKK), Finland (EUR), or Norway (NOK). This is not the customer's
   country. The default remains Denmark for existing Danish installations.
3. Configure the settlement journal, clearing account, fee expense account, and
   optional fee tax. Configure the standard payment journal as a bank journal.
   Missing MobilePay outstanding accounts default to the configured clearing
   account; existing nonempty account settings are preserved and must be checked.
   Report fees are treated as the total deduction including configured VAT.
   Automatic settlement currently requires company currency; FX payouts stop
   with an explicit error and require manual accounting review.
4. Use **Test API Connection** to request an access token. This is not a payment
   or webhook delivery test.
5. Set `web.base.url` to the externally reachable HTTPS URL. The inherited
   development parameter `mobilepay.allow_http_webhooks` defaults to `True`;
   set it to `False` for HTTPS-only webhook registration.
6. Register a webhook only against the intended merchant test unit.
   The registration's "connectivity" check currently checks local registration
   state, not actual delivery from Vipps.

Credentials use Fernet with the encryption key stored in the same Odoo database;
this is not an external secrets vault. Preserve that key when migrating existing
encrypted credentials.

### Nordic markets and languages

The payment method allows customers in **Denmark, Finland, Norway, Sweden,
Greenland and the Faroe Islands**. Customer country does not determine payment
currency: a Norwegian or Swedish customer can pay a Danish merchant in DKK.

| Registered merchant sales unit | Payment currency |
| --- | --- |
| Denmark, including Greenland | DKK |
| Finland | EUR |
| Norway | NOK |

These are the wallet sales-unit regions listed in the
[official Nordic guide](https://developer.vippsmobilepay.com/docs/knowledge-base/across-borders/).
Swedish customers use cross-border payments; this is **not** a claim of Swedish
merchant onboarding or SEK support. Mismatched currencies are hidden at
checkout and rejected before payment creation, even if an operator clears the
provider's currency filter. Configure each merchant unit's own credentials and
matching region; never infer its region from the customer's billing country.
Activate the matching Odoo currency and website pricelist. Selecting a region
does not convert existing carts or change the company's accounting currency.

The entered phone is sent in both environments. Use `+` or `00` and a country
code for cross-border phone numbers. Local numbers are normalized on the server
using the billing country (DK/NO eight digits, FI/SE leading national zero,
GL six digits). Faroese customers use a Danish number, as required by the
official eligibility guidance. Without a billing country, the company country
and then sales-unit region provide the fallback. The browser does not prepend
`+45` to Norwegian numbers. Clearing the input omits the phone. Number formatting
does not establish that the person has an eligible app account; in Test Mode,
use a registered Merchant Test user, not an ordinary personal number.

English source text and **Danish, Finnish, Norwegian Bokmal and Swedish**
translations cover all 249 extracted Odoo module terms per language, including checkout,
JavaScript errors, settings and accounting messages. Install the desired Odoo
languages and add them to the website's languages to expose the language picker.
Swedish also serves Swedish-speaking Finnish customers; Danish serves the Danish
region. Greenlandic, Faroese and Norwegian Nynorsk are not supplied or claimed
as app-supported languages. Vipps controls its own hosted page and app language;
the module catalogs translate Odoo, not the remote service.

An update expands the old DK-only/DKK-only payment-method defaults and changes
the default display names to `Vipps / MobilePay`. Empty or customized method
restrictions and customized names are preserved. No technical identifiers,
credentials, accounting history or currencies on existing transactions change.
Check the sales-unit region explicitly on any previously customized non-Danish
provider. The separate January 2027 logo cutover remains pending.

Payment creation requires a real HTTPS website domain/base URL. The addon
rejects HTTP configuration before contacting Vipps; it cannot turn an HTTP
listener into HTTPS by changing the URL scheme. Configure a trusted TLS endpoint
and proxy routing first. Do not expose the test instance publicly with the
default administrator password.

Capture modes:

- **Manual:** full or repeated partial captures. Danish/Finnish sales units
  require partial-capture enablement from Vipps MobilePay.
- **Delivery:** preserves the existing policy: capture the entire remaining
  authorization on the first completed delivery, even a partial delivery.
  Later backorders do not capture again. Use manual captures if money must
  follow each individual shipment.
- **After delay:** capture at the first five-minute cron run on/after the
  configured number of hours since authorization. A zero-hour delay is allowed.

Cancellation releases **all** remaining reserved funds, not an arbitrary smaller
part. Refund individual capture transactions after partial captures; do not
refund their aggregate parent again.

The official [Report API guide](https://developer.vippsmobilepay.com/docs/APIs/report-api/report-api-quick-start/)
states that reports are **production-only**, not available in the payment
sandbox. This addon's legacy `/settlement/v1/ledgers/{id}/entries` call is not in
the current published specification. Local synthetic-report accounting success
does not validate that adapter or authorize production payment testing.

## Validation in this migration workspace

There is no root test command or addon CI configuration. Odoo discovers only
test modules imported by [tests/__init__.py](tests/__init__.py):

- [Settlement tests](tests/test_fees_reconciliation.py): 28 tests.
- [Feature flags](tests/test_feature_support.py): 1 test.
- [Odoo 18 regression tests](tests/test_odoo18.py): 12 tests.
- [Lifecycle tests](tests/test_payment_lifecycle.py): 28 tests.
- [HTTP checkout/webhook tests](tests/test_payment_http.py): 10 tests.
- [Delivery/accounting acceptance](tests/test_payment_acceptance.py): 15 tests.
- [Nordic market tests](tests/test_nordic.py): 11 tests, including cross-border
  country/currency combinations and preservation of customized upgrade records.
- [Localization tests](tests/test_nordic_localization.py): 6 tests for current
  catalogs, placeholders/references, Odoo loading and public frontend translations.
- [Frontend phone tests](tests/test_payment_form.mjs): 5 Node tests.

Journal configuration also has a non-superuser regression test: when the
accounting payment method is missing, the addon uses Odoo's standard provider
setup helper rather than trying to create it with the settings user's rights.

The ten other historical `test_*.py` files are not registered and were **not**
counted as passing. Several reference obsolete addon APIs or fixtures.
The sixteen `simulation_test_*.py` scripts are not evidence of working Odoo
integration; many simulate copied logic.

From the migration workspace root, with local database connection settings
configured and an explicitly authorized disposable database:

```bash
docker compose run --rm --no-deps -T odoo18 odoo \
  -d mobilepay18_test \
  --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons/custom \
  -i mobilepay_payment --without-demo=all \
  --test-enable --test-tags=/mobilepay_payment \
  --stop-after-init --http-port=18078 --max-cron-threads=0
```

For the update check, replace `-i mobilepay_payment` with `-u mobilepay_payment`.
Both commands change the named database. Inspect the complete logs and module
state, not just the exit code. Do not run these commands against a customer or
non-disposable migration database. Do not use the workspace restore script for
addon tests.

Run the standalone frontend regressions from the migration workspace root:

```bash
node --test addons/custom/mobilepay_payment/tests/test_payment_form.mjs
```

These execute the actual payment-form extension with a stubbed Odoo host; they
are not a replacement for the real browser and merchant-app acceptance gates.

The HTTP tests require a real nonzero HTTP port. The separate local Chromium
run used an isolated Odoo server with synthetic API responses and outbound HTTP
blocked; it did not contact Vipps. Full evidence is in the migration report.

## Next work

Migrate and validate the remote Report API adapter, then complete merchant
test-unit/app and public HTTPS webhook acceptance. Review remaining recovery,
multi-company/access, localization and customer-database checks in the
[migration report](MIGRATION-18.0.md). Installation success and mocked acceptance
are not payment acceptance or approval for production use.
