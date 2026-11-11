# Nordic localization (Odoo 18)

English is the source language. The Odoo 18 export in
`mobilepay_payment.pot` contains 249 current terms. Each catalog covers the
entire inventory (996 translations across four catalogs), including checkout,
JavaScript validation, backend configuration, payment lifecycle messages,
accounting, and scheduled actions.

| Catalog | Odoo language | Scope |
| --- | --- | --- |
| `da.po` | `da_DK` | Danish |
| `fi.po` | `fi_FI` | Finnish |
| `nb.po` | `nb_NO` | Norwegian Bokmål |
| `sv.po` | `sv_SE` | Swedish, also usable by Swedish-speaking Finnish customers |

Odoo 18's `odoo.tools.translate.get_po_paths` loads the base-language catalog
before any regional override; `da.po` and `nb.po` therefore work with the
regional language codes above. No Greenlandic or Faroese translation is
provided or implied by customer-country support. The Danish sales region uses
Danish; customers can select one of the available website languages.

The `ir.http` frontend-module hook exposes this module's two JavaScript
validation messages through `/website/translations/<unique>` to public
visitors. Asset inclusion alone does not publish custom payment translations.
The same hook exists in the Odoo 17 and Odoo 18 core payment module.

## Maintenance and validation

Export a genuine POT from the updated, installed module on Odoo 18 before
refreshing catalogs. Preserve Odoo's extracted comments, model/XML references,
placeholders, HTML, and technical identifiers. Do not retain obsolete terms,
fuzzy entries, empty translations, or unreviewed English fallback text.
Unchanged brand names and shared terminology such as `Status` are intentional.
These translations require native-language review before production acceptance.

Register `tests/test_nordic_localization.py` in `tests/__init__.py`.
On an explicitly disposable, already-installed Odoo 18 test database, run:

```sh
odoo --database=<disposable-test-db> --update=mobilepay_payment \
  --test-enable --test-tags=/mobilepay_payment:TestNordicLocalization \
  --stop-after-init
```

Use the workspace's configured addon paths and database connection options.
Do not restore/drop a database for localization validation. The tests verify
exact inventory/context/reference parity, completeness, formatting, language
aliases, Python translation loading, public website-controller JavaScript
payloads, actual translated checkout QWeb rendering, and a translated backend
field. Database language activation and translation imports run within
`TransactionCase` rollback; no user's language settings are changed. The
controller test uses Odoo's `MockRequest`, not a real browser/network request.

Fresh installation, module update, full-suite/log inspection and native
linguistic acceptance remain separate validation gates; static catalog checks
alone do not establish production readiness.
