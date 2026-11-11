# MobilePay: Odoo 17 to Odoo 18 migration and acceptance

## Current handoff (2026-11-11)

Further live testing is paused at the operator's request; keep the HTTP-only
local setup unchanged. The latest Nordic follow-up suite has **111 passing
Odoo tests and 5 passing frontend tests**.
The operator reports successful test API authentication, a published Test Mode
provider and Capture on Delivery selected. These are configuration/authentication
results, not completed payment acceptance.

A DKK website pricelist and the existing draft cart were corrected in the
disposable sandbox; company accounting currency remains USD. Phone forwarding
now applies in Test Mode, but actual remote-page acceptance and HTTPS payment
return/webhook delivery remain blocked. Earlier results below describe their
respective historical validation phases.

The prioritized [TODO list](TODO.md) includes HTTPS/test-unit acceptance,
Report API migration, remaining production gates, and the requested
**12 January 2027** DK/FI MobilePay-to-Vipps branding cutover. Official Vipps Blue
logo and SVG paymark libraries were found and linked. No branding assets or
technical identifiers were changed, and no public tunnel was created.

The initial migration was subsequently committed as `2d8209b` and pushed to
`origin/18.0` at the operator's request; `main` was not changed. The Nordic
follow-up below is a separate, locally reviewable change. Earlier test counts,
DK-only coverage descriptions and Git status below are historical evidence.

## Outcome

- Date: 2026-11-11.
- Repository: `addons/custom/mobilepay_payment`, starting commit `1b94dc5`.
- Source: `main`, addon version `17.0.1.1.37`.
- Target: local branch `18.0`, addon version `18.0.1.1.0`.
- Addon: `mobilepay_payment`.
- Runtime: Odoo Community `18.0-20261015`, PostgreSQL 15.
- **PASS:** fresh installation and update, 91 registered Odoo tests.
- **PASS, local mocked acceptance only:** Chromium guest/authenticated payment
  forms, signed webhook HTTP requests, real stock delivery/backorder workflows,
  invoice/payment/refund posting, and synthetic-report clearing reconciliation.
- Migration risk: **HIGH**: money movement, recovery and upstream API contracts.
- Overall payment/production acceptance: **BLOCKED**. No real merchant payment,
  app approval or public reverse-proxy delivery has been accepted. The remote
  settlement adapter also uses an endpoint absent from the published API.
- No commit, push, merge or tag. `main` remains unchanged.

Only the explicitly authorized disposable `mobilepay18_test` database was
created/recreated and changed. No customer backup was read or restored; the
existing migration database was not changed. All payment API responses were
synthetic. No real merchant credentials were used or requested in chat.

## Inventory

### Dependencies and tests

```text
mobilepay_payment
  -> payment
  -> account
  -> website_sale
  -> stock
  -> sale_stock
  -> sale
```

All six declared dependencies resolve on the target; installation loads 73
modules including transitive/auto-installed dependencies.
External Python dependencies: `requests`, `cryptography`, already available.
There is no addon CI, dependency lock or root test command.

Odoo discovers only modules imported in [tests/__init__.py](tests/__init__.py):

| Test module | Tests | Coverage |
| --- | ---: | --- |
| [test_fees_reconciliation.py](tests/test_fees_reconciliation.py) | 28 | Existing settlement tests, corrected fixtures and actual VAT/net balance assertions |
| [test_feature_support.py](tests/test_feature_support.py) | 1 | Provider feature flags |
| [test_odoo18.py](tests/test_odoo18.py) | 12 | Declarations, views, jobs, credentials, headers, rendering and target compatibility |
| [test_payment_lifecycle.py](tests/test_payment_lifecycle.py) | 28 | Void/refund/capture children, amounts, retries, status aggregates, delay scheduling |
| [test_payment_http.py](tests/test_payment_http.py) | 8 | Real generic/shop routes, phone transport/access checks, signed webhooks and return |
| [test_payment_acceptance.py](tests/test_payment_acceptance.py) | 14 | Real invoices/payments/refund wizard, picking/backorder/cancel wizards, settlement reconciliation |
| **Total** | **91** | `0 failed, 0 error(s)` |

Ten historical modules remain unregistered and **NOT RUN**:
`test_api_request_headers`, `test_currency_conversion`, `test_data_encryption`,
`test_frontend_views`, `test_localization`, `test_module_structure`,
`test_oauth2_token_management`, `test_payment_initiation`, `test_phone_formatting`,
`test_webhook_registration`.
Some reference obsolete APIs/XML IDs or incomplete fixtures; property tests
also require undeclared `hypothesis`. Sixteen historical simulation scripts are
not counted as integration evidence.

### Models, controllers and integrations

| File | Models / behavior |
| --- | --- |
| [payment_provider.py](models/payment_provider.py) | Inherits `payment.provider`; encrypted credentials, capture settings, webhook configuration, payment method lines, settlements |
| [payment_transaction.py](models/payment_transaction.py) | Inherits `payment.transaction`; create/redirect, phone, polling, money modifications, aggregates, children, delayed capture, receipt/events |
| [sale_order.py](models/sale_order.py) | Inherits `sale.order`; cancellation hook releases remaining authorizations |
| [stock_picking.py](models/stock_picking.py) | Inherits `stock.picking`; configured delivery capture |
| [mobilepay_settlement.py](models/mobilepay_settlement.py) | `mobilepay.settlement`; payout totals, journal entry, state/note and unique payout constraint |
| [mobilepay_api_client.py](models/mobilepay_api_client.py) | Abstract `mobilepay.api.client`; HTTP, ePayment/webhook/report requests |
| [mobilepay_auth_service.py](models/mobilepay_auth_service.py) | Abstract `mobilepay.auth.service`; OAuth and token cache |

[Main controller](controllers/main.py):
`/payment/mobilepay/status`, `/payment/mobilepay/webhook`,
`/payment/vipps/webhook`, `/payment/mobilepay/return`.
[Portal extension](controllers/payment_portal.py) adds the optional
`mobilepay_phone` kwarg to standard `/payment/transaction` and inherited
`/shop/payment/transaction/<order_id>` handling without bypassing core access
token/order checks. The phone override is context-only, not a partner edit.

External integrations: `api.vipps.no`, `apitest.vipps.no`, OAuth,
ePayment `/epayment/v1`, webhooks `/webhooks/v1`, and the legacy settlement
adapter discussed below. **No live remote API acceptance was performed.**

### Views, assets, security, jobs and reports

- Inherited provider form/list: `payment.payment_provider_form`,
  `payment.payment_provider_list`.
- Inherited transaction form/list: `payment.payment_transaction_form`,
  `payment.payment_transaction_list`.
- Standalone settlement list/form, transaction/settlement actions and menus.
- [QWeb templates](views/mobilepay_templates.xml): inline phone and redirect.
- [PaymentForm JavaScript](static/src/js/payment_form.js) in
  `web.assets_frontend`; legacy widget extension, no custom OWL components.
- [Access CSV](security/ir.model.access.csv): read-only accountants can read
  settlements; invoice users read/write/create; managers have full access.
  No addon record rules. This work was not a security audit or user-ACL signoff.
- Five jobs: status polling (one minute), reservation expiry monitoring (six
  hours), cancelled-order polling (fifteen minutes), settlement sync (daily),
  and new delayed capture (five minutes).
- No Odoo report actions/PDF templates. Remote ledger reports are an external
  integration, not an Odoo report definition.
- Danish `.po`/`.pot`, logos and Apps description. Translation acceptance and
  uninstall hook were not tested.

Existing XML IDs are preserved, including IDs containing `tree`:

```text
payment_provider_mobilepay
payment_method_mobilepay
mobilepay_allow_http_webhooks
ir_cron_mobilepay_status_poll
ir_cron_mobilepay_capture_expiry
ir_cron_mobilepay_cancel_on_order_cancel
ir_cron_mobilepay_reconcile_reports
mobilepay_inline_form
mobilepay_redirect_form
payment_provider_form_mobilepay
payment_provider_tree_mobilepay
payment_transaction_form_mobilepay
payment_transaction_tree_mobilepay
action_mobilepay_transactions
menu_mobilepay_transactions
mobilepay_settlement_view_tree
mobilepay_settlement_view_form
action_mobilepay_settlement
menu_mobilepay_settlements
```

New ID: `ir_cron_mobilepay_auto_capture`.
Access IDs: `access_mobilepay_settlement_readonly`,
`access_mobilepay_settlement_invoice`, `access_mobilepay_settlement_manager`.
Model IDs are generated by Odoo.

## Plan, evidence and implementation

The migration first inventoried dependencies and compared source/target APIs,
ported declarations, installed/updated, then reproduced incomplete business
flows. The requested second phase repaired those flows and ran acceptance.

Local Odoo 17 and 18 implementations were inspected: cron fields; list/provider
views; capture/refund/void hooks and child state propagation; PaymentForm hooks;
portal/shop validation; account payment posting/refund wizard; sale cancellation
and stock validation/backorder hooks; fee tax computations.

Source image:
`sha256:7c936d910d54cb8d2af09db31d9b387b2ec83569d58a7b8ef65254d521a3fc69`.
Target base:
`sha256:7d23249b8dc43d67eee7ffe710dd50a2dd8e41b2c9935bfceea85dab10b396d3`.
Execution used the existing Compose image; no rebuild. Its Dockerfile installs
OpenUpgradeLib from unpinned upstream master, a reproducibility limitation.

Official documentation was checked, including the user-supplied
[AI tools page](https://developer.vippsmobilepay.com/docs/knowledge-base/ai-tools/),
the [Agent Toolkit](https://github.com/vippsas/agent-toolkit/tree/main/plugins/vipps-developer),
and [llms.txt](https://developer.vippsmobilepay.com/llms.txt). The guidance was
read as documentation; no editor plugin was installed. API facts were checked
against the published capture/cancel/refund, webhook authentication and Report
API pages/specification.

| Changed files | Corrections |
| --- | --- |
| [Manifest](__manifest__.py), [cron data](data/ir_cron_data.xml), [settlement views](views/mobilepay_settlement_views.xml), [transaction views](views/payment_transaction_views.xml) | Odoo 18 version/name, removed cron fields, `list` declarations/action modes; new delayed job |
| [API client](models/mobilepay_api_client.py), [auth service](models/mobilepay_auth_service.py) | Odoo 18 system/User-Agent headers |
| [Transactions](models/payment_transaction.py) | Real `_send_void_request`; superclass capture/refund/void child contracts; cumulative confirmed aggregates; remaining amounts; root row locking; stable retry keys; strict finite/minor-unit validation; delayed capture and postprocessing trigger |
| [Provider](models/payment_provider.py), [method data](data/payment_provider_data.xml), [upgrade script](migrations/18.0.1.1.0/post-migrate.py) | Refund availability on the payment method; negative-delay constraint; linked/default clearing payment accounts; settlement move reuse, actual reconciliation state, net payout guard and inclusive fee VAT |
| [Main controller](controllers/main.py) | Canonical HMAC verification over raw bytes and actual path/query; hash validation; root transaction lookup; 503 when authoritative status refresh fails |
| [Portal controller](controllers/payment_portal.py), [initializer](controllers/__init__.py), [frontend](static/src/js/payment_form.js), [templates](views/mobilepay_templates.xml) | Real form hooks, selected inline-form lookup, phone validation/transport, UI recovery; preserve all redirect query parameters including repeated/empty values; remove redirect-token diagnostics |
| [Sale orders](models/sale_order.py), [pickings](models/stock_picking.py) | Real cancellation hook, document notifications rather than nonexistent transaction chatter; savepoints for expected automatic money-operation failures |
| [Provider views](views/payment_provider_views.xml) | Preserve the standard manual-capture field for other providers |
| [Tests](tests/), [README](README.md), [Apps description](static/description/index.html), this report | Regression/acceptance coverage and evidence-based status |

Acceptance exposed additional coupled defects, now corrected: duplicate draft
settlement moves, false "reconciled" status, missing clearing defaults, and VAT
added on top of the reported total fee. A measured pre-fix fee example posted
bank 981.25 instead of reported 985 through an automatic balancing line.
The corrected example posts bank **985**, fee expense **12**, input VAT **3**,
clearing **-1000**, with no bank adjustment.

## Behavior and data migration

- New stored monetary field `payment.transaction.cancelled_amount`.
- `capture_eligible` dependencies now include remaining/cancelled amounts and
  child/source status; partial captures retain remaining authorization.
- Existing model/field names, field types, relational fields, XML IDs, stored
  totals and SQL constraints are preserved. No records or fields are deleted.
- [18.0.1.1.0 post-migration](migrations/18.0.1.1.0/post-migrate.py) changes only
  the seeded payment method's refund capability to `partial`: the original
  record is `noupdate`, so editing its XML alone cannot fix existing installs.
  Fresh installs receive the same setting from XML.
- Existing nonempty journal outstanding accounts are not overwritten. Confirm
  that both the standard bank payment journal and settlement journal use the
  intended clearing setup before accepting money movement.
- **Delivery policy is preserved:** first completed delivery captures the full
  remaining reservation, including when that delivery is partial. Later
  backorders do not capture again. It is not proportional per-shipment capture.
- Vipps cancellation releases **all remaining** authorization; arbitrary smaller
  partial void is explicitly rejected. After partial captures, refund the
  individual capture payments, not their aggregate parent.
- Delayed capture runs on the first five-minute tick at/after the configured
  hours since authorization. Zero hours is valid; failures notify/log and do
  not stop other due transactions.
- Foreign-currency automatic settlement now explicitly errors rather than
  booking foreign amounts as company-currency debits/credits.

Synthetic preservation across update verifies record IDs, ciphertext,
decryptability, capture settings, transaction amounts/reference/state and
settlement amounts/currency. Preserve `mobilepay.encryption_key` for real
credential continuity. **NOT RUN:** actual Odoo 17 customer-database upgrade.
No authorization to restore customer data was implied.

## Validation commands and results

Commands ran from the migration workspace root. Local database connection
arguments were supplied but are omitted here to avoid copying credentials.
Only the authorized disposable database was recreated:

```bash
docker compose exec -T db18 dropdb -U odoo --if-exists mobilepay18_test
docker compose exec -T db18 createdb -U odoo -O odoo mobilepay18_test
docker compose run --rm --no-deps -T odoo18 odoo \
  -d mobilepay18_test \
  --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons/custom \
  -i mobilepay_payment --without-demo=all \
  --test-enable --test-tags=/mobilepay_payment \
  --stop-after-init --http-port=18078 --max-cron-threads=0
```

Update: same command, replacing `-i mobilepay_payment` with
`-u mobilepay_payment`. A real nonzero HTTP port is required by HttpCase.
Static checks use `ast.parse` on all addon Python, `ElementTree.parse` on XML,
`ast.literal_eval` on the manifest and file-reference assertions.

| Validation | Result | Observation |
| --- | --- | --- |
| Python / XML / manifest | PASS | 47 Python files, seven XML files, dependencies and declared files |
| Dependency resolution | PASS | All six declared dependencies installed |
| Fresh install / module update | PASS | 91 tests each, `0 failed, 0 error(s)` |
| Synthetic update preservation | PASS | IDs, ciphertext, configuration and amounts unchanged |
| Fee VAT measurement | PASS | Bank 985, expense 12, input VAT 3, clearing -1000 |
| Local browser acceptance | PASS | Actual Chromium, guest/authenticated form, invalid/edited/cleared phone, restored button, preserved redirect query, no JS errors |
| Signed local webhook HTTP | PASS | Duplicates, tampering, missing auth, alias/query path, retry response and return |
| Real merchant app and public HTTPS delivery | BLOCKED | No merchant test unit credentials/app or public proxy supplied |
| Remote settlement API acceptance | BLOCKED | Production-only API and legacy adapter contract mismatch |
| Customer database / Enterprise / historical tests | NOT RUN | Outside this validation scope |
| Logs and local diff | PASS | Complete failures retained; expected injected errors distinguished from unexpected errors |

The integrated browser could not reach the remote workspace's loopback port.
A local headless Chromium runner was used instead. Missing Playwright/browser
libraries were downloaded and extracted only into the session evidence
directory, not installed into the addon or host system packages.
Its isolated Odoo wrapper mocked payment creation/status and blocked outbound
HTTP. The separate browser harness is not evidence of real Vipps approval.
Temporary browser tooling was removed after testing; scripts and logs remain.

Evidence directory:
`/root/.copilot/session-state/11124bd4-9f34-44c3-9b09-048c3b99d943/files/`.
Final logs/scripts:

- `mobilepay18-acceptance-final-install.log`,
  `mobilepay18-acceptance-final-update.log`.
- `mobilepay18-preservation-setup-final.log`,
  `mobilepay18-preservation-verify-final.log`.
- `mobilepay18-final-state.log`: installed version, disabled provider, refund
  capability, active delayed cron and installed dependencies checked through ORM.
- `mobilepay18-browser-acceptance.js`, `mobilepay18-browser-acceptance.log`,
  `mobilepay18-browser-server.py`.
- `mobilepay18-vat-probe-before.log`, `mobilepay18-vat-probe.log`.
- Original failures: `mobilepay18-readiness.log`,
  `mobilepay18-frontend-probe.log`, `mobilepay18-lifecycle-1.log`,
  `mobilepay18-acceptance-1.log`, `mobilepay18-acceptance-3.log`,
  `mobilepay18-clearing-configuration-failure.log`.
- `report-api-spec.yaml` records the published endpoint contract inspected.

Injected offline/API/create errors, explicit unmatched/FX settlement warnings
and invalid-request responses are expected negative tests. Existing portal-link
accessibility, font/mail-format and Compose volume warnings remain. Removing
redirect-token logging is not a full logging/privacy audit. No application or
browser sandbox started for this task is left running. The pre-existing
workspace application and migration database were left untouched.

## Acceptance checklist status and remaining gates

| Checklist item | Local result | Still required |
| --- | --- | --- |
| Test credentials, HTTPS, account/tax setup | PASS for synthetic accounting configuration | Real test-unit credentials entered by operator; external HTTPS |
| Guest/authenticated checkout, phone and redirect | PASS in actual Chromium | Merchant app approve/decline/abandonment and real order UX |
| Full/repeated partial capture, void, refunds | PASS with confirmed mocks, child records and real accounting | Remote contract acceptance; DK/FI partial-capture enablement |
| Delivery, wizard/backorder, duplicate, errors | PASS on actual stock workflows | Warehouse-user ACLs; business approval of full-first-delivery capture policy |
| Delayed boundary and repeated cron | PASS | Operational scheduling/monitoring with merchant unit |
| Signed webhook, duplicate/error/retry | PASS via local real HTTP routes | Registration/unregistration, actual public reverse proxy and delivery retries |
| Return/webhook ordering and polling | Partial: duplicate/return/status regression coverage | Real ordering, missed-event recovery and lost-response recovery |
| Settlement capture/refund/fee/VAT/net/retry | PASS for synthetic reports and actual reconciled clearing lines | Published remote adapter, authorized real reports and FX review |
| Other providers, normal users, Danish UI, multi-company | View preservation / provider-scoped matching checked | Complete user/ACL/company/localization/Enterprise acceptance |
| Authorized Odoo 17 database upgrade | NOT RUN | Compare real records, encryption key/ciphertext and balances, then update again |

### Remote settlement blocker established from official documentation

The [Report quick start](https://developer.vippsmobilepay.com/docs/APIs/report-api/report-api-quick-start/)
and [published specification](https://developer.vippsmobilepay.com/redocusaurus/report-swagger-id.yaml)
show `/settlement/v1/ledgers` for discovery, then
`/report/v2/ledgers/{ledgerId}/{topic}/dates/{ledgerDate}` or `/feed`.
The current adapter calls `/settlement/v1/ledgers/{ledgerId}/entries`, which is
absent from that specification and assumes an unverified legacy entry shape.
The [official test/go-live guidance](https://github.com/vippsas/agent-toolkit/blob/main/plugins/vipps-developer/skills/test-and-go-live/SKILL.md)
also states Report/Sales APIs are **not available in the test environment**.

Therefore synthetic settlement accounting is not remote settlement acceptance.
The adapter needs a separately validated v2 mapping, pagination/cursor and
deduplication/recovery design before importing real reports. Do not enable a
production payment provider merely to work around this sandbox limitation.

Other open gates: report matching/company isolation for real merchant data,
recovery when remote success precedes a local rollback/status refresh,
asynchronous webhook latency under the real ten-second delivery timeout,
reservation-deadline policy, diagnostic logging/privacy, full-first-delivery
capture policy, and disabled/non-admin provider behavior. The seeded checkout
method remains DK/DKK; backend NOK/EUR helpers are not market acceptance.

**Installation success and local mocked acceptance are not payment acceptance
or approval for production use.**

## Follow-up: journal configuration access error

Saving a bank journal exposed an `account.payment.method` create AccessError.
The custom journal helper tried to create the missing accounting method with
the current user's rights. Odoo intentionally grants no normal group create
access to this model.

The helper now uses core `_setup_payment_method("mobilepay")`, verified in both
Odoo 17 and 18. Core performs this narrowly scoped provider setup itself; no
addon ACLs were broadened and no custom `sudo()` workaround was added.
Existing method lookup and journal-line creation remain under normal rights.
The new test uses a non-superuser accounting/settings manager, explicitly
asserts lack of method-create permission, exercises missing-method recovery,
verifies the clearing account and checks that repeated saves do not duplicate
the line.

The earlier fresh-install evidence remains 91 tests. The follow-up suite has
92 tests (15 delivery/accounting acceptance tests), with results recorded in
`mobilepay18-journal-access-suite.log`; the focused regression is recorded in
`mobilepay18-journal-access-regression.log`. No test database was recreated
for this fix; user-entered settings and credentials were preserved.

## Follow-up: sandbox phone and HTTPS payment returns

The original test-mode phone omission was a workaround, not a required API
contract. It prevented checkout edits from prefilling the remote payment page.
Phone forwarding now applies to both environments; only an explicitly cleared
input omits it. Use a registered Merchant Test user in the sandbox.

The previous return URL logic silently replaced `http` with `https`, producing
a broken return link for the HTTP-only local server. Payment creation now
rejects a non-HTTPS base URL before the remote request, with an explicit
configuration error. A real reachable TLS endpoint is still an infrastructure
prerequisite, not a code-level scheme rewrite. No tunnel was created and no
instance was exposed to a third party.

Official create-payment and Merchant Test documentation were inspected before
this change. Full update suite: **93 tests, zero failures/errors**, recorded in
`mobilepay18-phone-https-suite.log`. Tests cover phone forwarding in Test Mode,
production edited/cleared input, generic/shop routes, and HTTP rejection before
API creation. Earlier 91/92-test results above are historical evidence.
Public HTTPS and actual remote phone-page acceptance remain BLOCKED pending an
operator-provided TLS endpoint and test-app run.

## Follow-up: Nordic countries and translations (18.0.1.2.0)

Source: the committed Odoo 18 integration (`2d8209b`); target remains Odoo 18
Community. This follow-up does not attempt Odoo 19. Risk remains **HIGH** because
currency selection and phone identity affect real money movement; production
acceptance remains **BLOCKED**.

### Findings and plan

The original method's DK/DKK restrictions hid it from Nordic customers despite
the ePayment API's cross-border capability. Backend allowlisting NOK/EUR did
not enforce the sales unit's actual currency. Browser code silently added +45
to every eight-digit phone; it disagreed with the country-aware server code.
The Danish catalog was an incomplete Odoo 17 inventory; other Nordic catalogs
were absent.

The [official Nordic guide](https://developer.vippsmobilepay.com/docs/knowledge-base/across-borders/)
was checked before implementation. It lists Danish/DKK (including Greenland),
Finnish/EUR and Norwegian/NOK wallet sales units; Swedish customers pay
cross-border, not necessarily in SEK. Faroese residents use the Danish region
with a Danish phone number. Odoo 17/18 `payment.provider` currency computation,
compatibility signatures and `payment.method` country/currency filters were
compared with the custom implementation.

Plan: distinguish merchant region from customer country; expand Nordic method
availability; centralize phone normalization on the server; update existing
default records without overwriting operator policy; regenerate current terms,
translate them and test actual translation loading, then rerun the registered
regressions. Keep real payment, HTTPS and report acceptance separate.

### Changed surfaces and data

- [Manifest](./__manifest__.py): `18.0.1.2.0`, Nordic scope; unchanged Odoo/Python
  dependency graph.
- [Provider](./models/payment_provider.py) and
  [configuration view](./views/payment_provider_views.xml): new
  `mobilepay_sales_unit_region` selection, default DK, with DK/DKK, FI/EUR,
  NO/NOK mapping. Standard currency filtering and an independent checkout guard
  enforce the configured merchant currency, including when a filter is empty.
- [Transaction](./models/payment_transaction.py): currency mismatch rejected
  before API creation; customer-country phone normalization supports DK/NO,
  FI/SE trunk zero and Greenland. Explicit international numbers take precedence.
- [Frontend](./static/src/js/payment_form.js),
  [templates](./views/mobilepay_templates.xml) and
  [portal](./controllers/payment_portal.py): neutral Vipps/MobilePay text,
  country-code guidance and no browser-side Danish-prefix rewrite. Existing
  route authentication/access checks and optional clearing behavior remain.
- [Seed data](./data/payment_provider_data.xml): DK/FI/NO/SE/GL/FO customer
  countries, DKK/EUR/NOK method currencies; provider region narrows actual
  available currencies.
- [Translation catalogs](./i18n/): regenerated Odoo 18 POT and 249 complete terms
  in each of Danish, Finnish, Norwegian Bokmal and Swedish (996 translations).
  Contexts, placeholders, markup and current XML references are checked.
  [Public frontend translation hook](./models/ir_http.py) includes the addon in
  website JavaScript translations; the core payment hook only includes `payment`.
  The same source/target Odoo hook was verified before extending it.
- [Upgrade script](./migrations/18.0.1.2.0/post-migrate.py): expands only the
  old exact DK and DKK method restrictions; preserves unrestricted/custom
  lists. Changes only default provider/method names to `Vipps / MobilePay`.
  It is idempotent and preserves custom names and all credential/capture settings.
- [Market tests](./tests/test_nordic.py),
  [HTTP tests](./tests/test_payment_http.py) and
  [frontend tests](./tests/test_payment_form.mjs): country/currency combinations,
  cross-border phone payloads, operator restrictions, other providers and
  preservation/idempotency checks.
- [Localization tests](./tests/test_nordic_localization.py): six checks for
  catalog coverage, references, placeholders and runtime translation surfaces.
- [README](./README.md), [TODO](./TODO.md) and
  [Apps description](./static/description/index.html): updated supported scope
  and deployment prerequisites.

No models, existing fields, XML IDs, API routes or technical provider/method
codes were renamed or removed. No field type, SQL constraint, stored monetary
computation or transaction/accounting relationship changed. The new stored
region field and method availability relations require the versioned upgrade.
Existing non-Danish customized installations must explicitly verify their
merchant region; the migration does not guess it from billing country.
No customer data is discarded. Future DK/FI branding assets are not installed.

### Validation and manual acceptance

- **PASS:** Python AST, XML parsing, manifest data/asset paths and Git whitespace.
- **PASS:** targeted market, phone and migration tests after correcting a
  duplicate synthetic transaction reference in the new test fixture. Complete
  initial failure and successful retest logs are retained in the session.
- **PASS:** 104 registered Odoo tests before the localization follow-up,
  zero failures/errors (`mobilepay18-nordic-runtime-suite.log`).
- **PASS:** full follow-up suite of 111 registered Odoo tests, zero failures or
  errors (`mobilepay18-nordic-final-suite.log`), including four-language public
  frontend payloads, translated QWeb/settings and DKK/EUR/NOK modification flows.
  The first localization run exposed an incomplete `MockRequest` HTTP response
  fixture; binding the real target request response helpers fixed the test
  without bypassing the decorated public controller. Failure/retest logs remain.
- **PASS:** a fresh final Odoo export matched all four catalogs exactly:
  249 terms per language, 996 complete translations. It detected the additional
  `HTTP Routing` model term introduced by the frontend hook; that term was added
  before a final six-test localization retest passed with zero failures/errors
  (`mobilepay18-nordic-localization-final249.log`).
- **PASS:** 5 frontend tests with
  `node --test addons/custom/mobilepay_payment/tests/test_payment_form.mjs`.
  These execute the real extension with a stubbed host, not a real browser.
- **PASS:** a fingerprint comparison before/after the full update confirmed
  existing provider credentials and capture/account settings were unchanged;
  persistent module state is installed at `18.0.1.2.0`.
- **PASS:** Odoo logs inspected. Simulated offline/API/accounting failures and
  invalid-input/webhook warnings are expected negative-path tests. The
  pre-existing provider-view link/button accessibility warning remains unchanged.
- **NOT RUN:** a new fresh installation for this follow-up. The only authorized
  disposable database already contains operator settings and was not recreated.
  Earlier fresh-install evidence applies to the earlier version only.
- **BLOCKED:** real merchant/app approval, HTTPS returns/webhooks and remote
  Report API acceptance. No outbound payment acceptance is claimed.

The Odoo command was the README update command (`-u mobilepay_payment`), with
`--db_host=db18 --db_user=odoo`, HTTP port 18078, cron threads zero and existing
local connection configuration. Only `mobilepay18_test` was changed. No restore,
customer backup access, new public exposure, commit or push was performed for
this follow-up.

Manual acceptance still requires each deployed region's credential/region
agreement, remote phone/app flow, cross-border captures/refunds and signed
webhooks. Have native speakers review translated checkout, settings and
accounting wording. Install the selected Odoo languages and enable them on the
website; the module cannot translate Vipps's hosted page or app. No Greenlandic,
Faroese or Norwegian Nynorsk translation coverage is claimed.
