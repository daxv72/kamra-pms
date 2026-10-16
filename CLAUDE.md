# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Kamra is an open-source, AI-native hotel PMS: a **Frappe v16** app (`kamra/`, Python, MariaDB, depends on the `payments` app) plus a **React 19 + Vite + Tailwind 4** SPA (`frontend/`) served at `/kamra`. A fuller developer guide lives in `.cursor/skills/kamra-dev/` (`SKILL.md`, `architecture.md`); its local paths are specific to one maintainer's machine.

## Commands

Backend commands run inside a Frappe bench (`apps/kamra` is this repo). Dev site is usually `kamra.localhost`.

```bash
# dev setup (see README "Quickstart (development)")
bench init --frappe-branch v16.25.0 frappe-bench && cd frappe-bench
bench get-app payments && bench get-app kamra <this repo>
bench new-site kamra.localhost --admin-password admin
bench --site kamra.localhost install-app kamra
bench serve --port 8000
cd apps/kamra/frontend && npm install && npm run dev      # SPA with hot reload on :5173

bench --site kamra.localhost migrate                       # after editing doctype JSON / adding patches
bench --site kamra.localhost execute kamra.scripts.seed_demo.execute   # demo data (idempotent)
```

**Eval harness** — the main backend test gate (CI requires all checks green). Run via `bench console`, not `bench execute` (eval quirk in v16):

```bash
bench --site kamra.localhost console
>>> from kamra.scripts.eval_harness import execute; execute()
```

Each check is a function decorated with `@check("name")` in `kamra/scripts/eval_harness.py`, runs inside a savepoint that is rolled back, and **must be appended to the tuple in `execute()`** or it never runs. There is no single-check runner: `execute()` wraps the whole run in an outer savepoint and stubs `frappe.db.commit`, so calling `setup()`/`tNN()` by hand leaves data behind unless you replicate that. Add a check for any behaviour you change in pricing, folios, availability, roles or a country pack.

Other backend tests CI runs:

```bash
bench --site test.localhost set-config allow_tests true
bench --site test.localhost run-tests --module kamra.tests.test_banquet   # any kamra.tests.<module>
# front-desk persona journey (console): from kamra.scripts.frontdesk_eval import execute; execute()
```

**Frontend:** `cd frontend && npm run build` (= `tsc -b && vite build`) is the typecheck + build gate. It emits into `kamra/public/frontend`, which **is committed** so `bench get-app` needs no Node — commit the rebuilt output with UI changes. CI also asserts `index.html` references `/assets/kamra/frontend/assets/`.

**Lint:** pre-commit runs ruff (tabs, double quotes, line length 110), prettier and eslint. CI additionally runs Frappe semgrep rules (ERROR severity) and `python kamra/scripts/marketplace_install_check.py`.

**Docs site** (`docs-site/`, VitePress): `npm run build`. After adding/changing endpoints or MCP tools regenerate references with `python3 gen_api.py` and `python3 gen_mcp_tools.py`; a new Python module of endpoints must first be added to `MODULES` in `gen_api.py`.

## Architecture

**One write path.** The staff SPA, guest booking engine (`/book`), housekeeping app (`/hk`), REST clients, the hosted MCP server and the in-app copilot all call the same `@frappe.whitelist()` functions in `kamra/<module>.py`. Never add a second writer (raw SQL that skips the API, an MCP tool computing its own price, a client-trusted amount).

**Money is code.** Quotes, tax, deposits, availability and cancellation fees are computed server-side (`pricing.py`, `folio.py`, `ledger.py`, `cashier.py`, night audit) with `Decimal`. Folios are append-only (voids are reversals); closing assigns the invoice number once; night audit is idempotent per business date. Rate guardrails (owner floor/ceiling) are enforced in `set_room_rate`.

**Authorization lives on the endpoint**, not DocPerms: `@require_roles(...)` from `kamra/authz.py`, placed **below** `@frappe.whitelist()`. Roles: Front Desk, Revenue Manager, Finance, Housekeeping, Hotel Admin (owner/GM), System Manager (IT, `require_it_admin`), Kamra Agent (AI). Data is also property-scoped via Frappe User Permissions. Frappe gotcha: Custom DocPerm rows *replace* built-in perms, so every role needs explicit rows.

**Property modules** (`enabled_modules` on Property, empty = all): `front-desk`, `housekeeping`, `operations`, `fnb`, `events`, `revenue`, `finance`, `booking-engine`, `admin`. MCP tool visibility = user roles ∩ enabled modules.

**MCP:** registry in `kamra/mcp_tools.py` (`TOOLS` of `ToolSpec`, `GROUP_MODULE`). Each tool points at a dotted whitelisted endpoint; set `group`, `mutating=True` for writes, and use `inject_property` rather than asking the model for the property. Hosted at `/mcp` (`mcp_http.py`, OAuth 2.1 + PKCE in `mcp_oauth.py`); `mcp/kamra_mcp.py` is a stdio sidecar using the same list. Agent calls set `frappe.flags.kamra_agent_call` (skips cashier PIN) and mutating calls are logged to Agent Action Log.

**Guest/public surface:** `kamra/public_api.py` is the `allow_guest` surface (booking, self check-in, QR menu) — rate-limited and must never trust prices or amounts from the browser.

**Localization:** country packs in `kamra/localization/` selected via the `kamra_localization` hook in `hooks.py`; `generic.py` is the fallback. Interface documented in `kamra/localization/__init__.py` (`thailand.py` is the smallest example, `india/` shows integrations, `saudi.py` + `kamra/zatca/` e-invoicing). Country-specific tax, IDs or gateways belong in the pack, never in core; the UI must not hardcode `₹`/GST — use `property_locale`.

**Schema & lifecycle:** doctypes in `kamra/kamra/doctype/`; data migrations are patches under `kamra/patches/vNN/` registered in `patches.txt`; `install.py` (`after_install`, `after_migrate`) handles roles/perms. Scheduled jobs (night audit 03:00, hourly ARI push, pre-arrival links, HK escalation, hold expiry, demo reset) and `doc_events` are in `hooks.py`.

**Frontend:** routes in `frontend/src/App.tsx`, prod basename `/kamra` (served by `kamra/www/kamra.py`, which injects the CSRF token). All server calls go through `frontend/src/lib/api.ts` (`call("kamra.api.get_quote", {...})`) — call Kamra endpoints, not raw doctype REST that bypasses Kamra authz. Strings via `frontend/src/lib/i18n.ts` (`npm run i18n:extract` / `i18n:import`).

## Workflow conventions

- PRs target `develop` (default/nightly branch); `main` only moves on releases. Branch names `feat/`, `fix/`, `hotfix/`, `chore/`, `docs/` + kebab slug.
- Conventional Commits (release-please builds the changelog). Versioning is patch-first: `feat:` still ships as a PATCH. Removing/renaming a doctype, whitelisted method or config key is breaking and must be called out. Details in `CONTRIBUTING.md` / `RELEASING.md`.
- Don't force-push `main`/`develop`. Desk (`/app`) is admin-only; the product UI is `/kamra`.
