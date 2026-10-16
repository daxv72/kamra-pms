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

## GitHub Actions sul fork (`daxv72/kamra-pms`)

Questo fork usa i workflow ereditati dal repo ufficiale (`.github/workflows/`). Sono **attivi** solo i tre che verificano il codice; i quattro che pubblicano release, immagini Docker o fanno deploy sono **disattivati** a mano (`gh workflow disable`), perché sul fork creerebbero tag/release finti o tenterebbero push verso `ghcr.io/kamra-pms`. Nei file non c'è nessun controllo `github.repository == 'Kamra-PMS/...'`: lo spegnimento è solo nelle impostazioni del fork, non nel codice.

| Workflow | Stato | Si avvia | Durata tipica |
| --- | --- | --- | --- |
| **CI** (`ci.yml`) | attivo | push su `main`/`develop`, ogni PR | ~5 min |
| **Linters** (`linters.yml`) | attivo | push su `main`/`develop`, ogni PR, manuale | ~30 s |
| **Deploy smoke** (`deploy-smoke.yml`) | attivo | PR che toccano `deploy/**` o il workflow stesso, manuale | ~8 min (timeout 90) |
| Nightly, release-please, Release, VPS Doctor | **disattivati** | — | — |

Regola pratica: **una PR verso `develop` fa partire CI + Linters**; il merge su `develop` li rilancia sul risultato. Se uno è rosso, non mergiare. CI **non si può lanciare a mano** (non ha `workflow_dispatch`): per ri-eseguirlo usa "Re-run jobs" sulla run, oppure fai un push sulla PR.

### CI — `ci.yml`

È il cancello principale: dice se il codice compila e se la logica di business (soldi, disponibilità, ruoli) è ancora corretta. Permessi minimi (`contents: read`: legge il repo, non scrive niente). `concurrency` per ref: un nuovo push sulla stessa PR/branch **annulla** la run precedente ancora in corso. Ha due job indipendenti che girano in parallelo.

**Job 1 — "Frontend typecheck & build"** (Node 24):
1. `npm ci` in `frontend/` — installa le dipendenze esattamente come in `package-lock.json`.
2. `npm run build` = `tsc -b && vite build` — controlla i tipi TypeScript di tutta la SPA e la compila in `kamra/public/frontend`. Fallisce se c'è un errore di tipo o di build.
3. "Verify production serve base" — controlla che `index.html` punti agli asset sotto `/assets/kamra/frontend/assets/`. Se la `base` di Vite fosse sbagliata, `/kamra` in produzione mostrerebbe una pagina bianca senza errori visibili.
Nota: il job ricompila nel runner ma **non confronta** il risultato con l'output committato; se cambi il frontend devi comunque committare `kamra/public/frontend` rigenerato.

**Job 2 — "Backend eval harness"** (timeout 25 min): costruisce da zero un'installazione Frappe vera e ci fa girare tutti i test di backend.
1. Avvia un **MariaDB 11.8** come servizio Docker (root/root, porta 3306) e aspetta che sia pronto (healthcheck).
2. Installa Python 3.14, Node 24, `redis-server`, il client MariaDB e `yarn`.
3. Imposta MariaDB in `utf8mb4` / `utf8mb4_unicode_ci` (richiesto da Frappe).
4. `bench init` con **Frappe v16.25.0** fissato a quel tag (la punta del branch `version-16` ha un bug in `frappe/locale.py`), senza config Redis e senza build degli asset; punta cache/queue/socketio sull'unico Redis 6379.
5. `bench get-app payments`, `bench get-app kamra` dal codice della PR, crea il sito `test.localhost` e installa Kamra (`install-app` esegue anche `after_install`: ruoli, permessi, Website Settings), poi `developer_mode 1`.
6. **Eval harness** (`kamra.scripts.eval_harness.execute()` via `bench console`): ~180 controlli deterministici su prezzi, tasse, folio, disponibilità, night audit, ruoli, country pack, channel manager, banquet, privacy… Ogni controllo gira in un savepoint annullato. Il job passa solo se il riepilogo è `N/N passed` (tutti verdi, qualunque sia N).
7. **Unit test banquet** (`kamra.tests.test_banquet`) — deve terminare con `OK`.
8. **Unit test night audit / ledger / audit schedulati**: `test_night_audit`, `test_ledger_audit`, `test_folio_leaks`, `test_bill_settlement`, `test_health`, `test_scheduled_jobs`. Accetta `OK` oppure `OK (expected failures=N)` (bug noti fissati come "attesi").
9. **Front-desk persona journey** (`kamra.scripts.frontdesk_eval`): simula il percorso di un receptionist end-to-end; deve dare `13/13 passed`.
10. **Fresh-install correctness**: su un'installazione appena fatta verifica che esistano i ruoli (Front Desk, Housekeeping, Finance, Revenue Manager, Kamra Agent, Hotel Admin), che `Reservation` abbia DocPerm, che la SPA compilata e `www/kamra.py` siano presenti e che la regola di route `/kamra/<path:app_path>` sia registrata.
Cosa NON copre: i test che non sono elencati qui (es. `test_www_kamra`, `test_channel_manager_*`) non girano in CI — vanno lanciati a mano con `bench run-tests --module`.

Equivalente in locale: `bench --site kamra.test console` → `from kamra.scripts.eval_harness import execute; execute()`. Su `kamra.test` il check "channel manager" fallisce perché il sito ha valuta di sistema EUR e il test invia un webhook in INR: è un limite del test, non un bug (in CI il sito nuovo non ha questo default).

### Linters — `linters.yml`

Richiesto dalla review del **Frappe Cloud Marketplace**. Due job paralleli, permessi in sola lettura.
1. **"Semgrep Rules"** (Python 3.13): scarica le regole ufficiali `frappe/semgrep-rules` e il pacchetto `r/python.lang.correctness`, ed esegue Semgrep **solo a severità ERROR** (le WARNING — traduzioni, whitelist guest, type hint — si rivedono a mano). Blocca pattern pericolosi tipici di Frappe: SQL costruito a mano, `frappe.db.commit()` fuori posto, `frappe.set_user`, accessi a file da input utente, ecc. Un'eccezione voluta si dichiara con `# nosemgrep: <regola> -- motivo` **sulla stessa riga** del codice segnalato (attenzione: il formatter di ruff può spostare il commento su un'altra riga e rendere inefficace l'eccezione).
2. **"Marketplace install simulation"**: esegue `python kamra/scripts/marketplace_install_check.py`, che senza database simula i controlli di Frappe Cloud: `pyproject.toml` (nome `kamra`, metadati), `hooks.py` (hook obbligatori, route rule), licenza e pacchetto, SPA pre-compilata presente in `kamra/public/frontend`, testi del listing, e che non ci siano `frappe.set_user` / `frappe.db.commit` senza `nosemgrep` sulla stessa riga.

Non esegue ruff/prettier/eslint: quelli girano solo in locale con `pre-commit run --files <file>` (l'hook git non è installato in questo checkout).

### Deploy smoke — `deploy-smoke.yml`

Prova da zero il percorso di **self-hosting con Docker** (`deploy/install.sh`), come farebbe un albergatore su una VPS. Parte solo se una PR tocca `deploy/**` o questo workflow (o se lo lanci a mano); per le PR normali non gira. Timeout 90 min, sola lettura.
1. Libera spazio disco sul runner (rimuove .NET, Android SDK, GHC, CodeQL).
2. `sudo bash deploy/install.sh` con sito `smoke.kamra.test`: costruisce l'immagine Docker **con il codice della PR/branch** (`KAMRA_GIT_URL` = il repo da cui arriva la PR, `KAMRA_BRANCH` = il branch), crea il sito, avvia i container.
3. "Site answers": chiama `/api/method/ping` su `127.0.0.1:8080` (header `Host: smoke.kamra.test`) fino a 30 volte ogni 5 s; deve rispondere 200.
4. Ri-esegue `install.sh`: deve essere **idempotente** (non rompe nulla e conserva la password del DB).
5. `install.sh update`: ricostruisce l'immagine e lancia `bench migrate`, come un aggiornamento reale.
6. Ricontrolla che il sito risponda dopo l'update.
7. Solo se qualcosa fallisce: stampa le ultime 200 righe dei log `docker compose`.
Lanciato a mano su `develop` ricostruisce l'immagine dal tuo fork (~8 min): utile per verificare che il fork resti installabile.

### Workflow disattivati sul fork (e perché)

- **Nightly** (`nightly.yml`, ogni giorno 21:30 UTC): se `develop` ha commit nuovi con CI verde, costruisce e pubblica `ghcr.io/kamra-pms/kamra:nightly`, crea una prerelease GitHub "nightly" e fa deploy via SSH su nightly.kamrapms.com. Sul fork il push dell'immagine fallirebbe (registry dell'org ufficiale) e creerebbe prerelease sul fork.
- **release-please** (`release-please.yml`, push su `main`): apre/aggiorna la PR di release che alza `__version__` e scrive `CHANGELOG.md`; quando viene mergiata crea il tag `vX.Y.Z` e chiama Release. Sul fork genererebbe versioni e tag che non corrispondono a quelle ufficiali.
- **Release** (`release.yml`, tag `v*`): crea la GitHub Release, pubblica `ghcr.io/kamra-pms/kamra:<tag>` e `:latest`, deploy SSH su demo.kamrapms.com.
- **VPS Doctor** (`vps-doctor.yml`, solo manuale): diagnostica in sola lettura del server di produzione via SSH (`df`, `docker ps/inspect`, log). Senza i secret `DEPLOY_*` non ha senso sul fork.

Riattivare: `gh workflow enable <file>.yml --repo daxv72/kamra-pms`; stato: `gh api repos/daxv72/kamra-pms/actions/workflows --jq '.workflows[] | "\(.state)\t\(.path)"'`.

Avviso noto, innocuo: "Node.js 20 is deprecated … forced to run on Node.js 24" su `actions/checkout@v4`, `actions/setup-node@v4` (e `setup-python@v5`). I job passano; si risolve passando a `checkout@v5`, `setup-node@v5`, `setup-python@v6`. Lasciato com'è di proposito per non divergere dai workflow upstream (eviterebbe conflitti al riallineamento di `develop`).
