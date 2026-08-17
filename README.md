# Budget

Budget is a single-user-first personal finance dashboard built as a lightweight
modular monolith. Phase 1 provides secure first-run account setup, a persistent
demo environment, category and income settings, and a calculated monthly
dashboard. Phase 2A adds writeable manual accounts and transactions, Phase 2B
adds secure Plaid bank connections, Phase 2C adds cursor-based transaction sync,
Phase 2D adds transaction intelligence and signed webhook refresh, Phase 3A adds
annual/monthly budgets, Phase 3B adds goals, debt planning, and cash-flow
forecasting, and Phase 3C adds deterministic insights plus Ask Budget with
user-approved action plans. It is designed to run on an Oracle Cloud E2 Micro VM
without containers.

## Phase 1 features

- Secure first-owner setup, login, logout, expiring database-backed sessions,
  CSRF protection, login throttling, and security audit events.
- Responsive React interface for setup, login, dashboard, accounts,
  transactions, and settings.
- Deterministic demo data that works without Oracle or other external services.
- MySQL-compatible SQLAlchemy models and Alembic migrations.
- Oracle MySQL HeatWave production connectivity over the private VCN with
  required encrypted TLS and negotiated-cipher enforcement.
- Nginx static hosting/reverse proxy and a hardened single-worker systemd unit.
- Backend, frontend, accessibility, and browser smoke tests.

## Phase 2A features

- Create, edit, and delete manual accounts with signed balances, optional
  available balance/credit limit, currency, subtype, and masked last four.
- Create, edit, and delete manual transactions with account/category ownership
  checks, signed amount rules, pending state, notes, and audit events.
- `manual`/`plaid` source markers keep provider-managed records read-only once
  Plaid is introduced while preserving manual adjustments.
- Dashboard, account, and transaction views immediately reflect manual records.

## Phase 2B features

- Plaid Link and OAuth return handling for Sandbox/Production bank connections.
- AES-GCM encrypted Plaid access tokens, connected institutions/accounts, balance
  import, duplicate-Item prevention, and disconnect.

## Phase 2C features

- Incremental `/transactions/sync` ingestion with a persisted cursor per Plaid
  Item and atomic added/modified/removed patching.
- Pending-to-posted reconciliation through Plaid transaction identifiers, PFCv2
  metadata storage, category mapping, and Budget's inflow/outflow sign convention.
- Manual **Sync now** on connected institutions plus a lightweight systemd timer
  that runs the same CLI sync path for webhook-requested or stale Items.
- Connected account balances are refreshed from transaction-sync responses while
  manual records remain unaffected and Plaid transactions remain read-only.

Later phases add deterministic/AI-assisted planning, reports, production-readiness
controls, notifications, and Plaid Production/update-mode support while keeping the
same small-install FastAPI/MySQL deployment model.

## Architecture

```text
Browser
  -> HTTPS / Nginx
       -> React/Vite static files
       -> /api/* -> Uvicorn/FastAPI on 127.0.0.1:8000
                       -> SQLAlchemy/PyMySQL
                       -> MySQL HeatWave private endpoint
```

Production runs one synchronous Uvicorn worker. Nginx serves the compiled
frontend, so no Node process runs after deployment. Redis, Celery, Docker, and
an embedded scheduler are not required. See [Architecture](docs/ARCHITECTURE.md)
and [deployment instructions](deploy/README.md) for the detailed decisions.

## Prerequisites

- Python 3.12
- Node.js 24 LTS and npm
- Git
- Windows 11 and PowerShell for the documented local workflow
- Oracle MySQL HeatWave only for production or optional MySQL compatibility
  testing

## Local demo setup (Windows PowerShell)

From the repository root:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item ..\.env.example .env
python -m app.cli demo-reset
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second PowerShell window:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Choose **Explore demo** to sign in to the
deterministic sample workspace. The Vite development server forwards `/api`
requests to FastAPI.

The demo reset command is idempotent and destructive only to the configured
demo SQLite file. It refuses to operate in production or against MySQL.

## Configuration

For local development, copy `.env.example` to `backend/.env`. Production uses
the systemd environment file `/etc/budget-app/budget.env`; do not deploy a
repository `.env` file.

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development`, `test`, or `production` |
| `DEMO_MODE` | Enables the isolated SQLite demo and demo login |
| `DEMO_DB_PATH` | Local demo database path; never used in production |
| `APP_SECRET` | HMAC root for privacy-preserving throttle/audit identifiers |
| `SESSION_SECRET` | HMAC root for stored session and CSRF digests |
| `ENCRYPTION_KEY` | Encrypts stored Plaid access tokens with authenticated encryption |
| `BOOTSTRAP_TOKEN` | One-time 256-bit production setup credential |
| `ALLOWED_HOSTS` | Comma-separated public and loopback hosts accepted by FastAPI |
| `LOG_LEVEL` | Application log level |
| `DB_HOST` | HeatWave internal FQDN matching its TLS certificate |
| `DB_PORT` | MySQL TCP port, normally `3306` |
| `DB_NAME` | Dedicated application schema |
| `DB_USER` | Least-privilege application database user |
| `DB_PASSWORD` | Database password |
| `DB_SSL_REQUIRED` | Strict `true`/`false`; production requires `true` |
| `DB_SSL_MODE` | `REQUIRED` (default), `VERIFY_CA`, or `VERIFY_IDENTITY` |
| `DB_SSL_CA` | CA file path required by `VERIFY_CA` / `VERIFY_IDENTITY` |
| `PLAID_CLIENT_ID` | Plaid API client ID; server-side only |
| `PLAID_SECRET` | Plaid Sandbox or Production secret; server-side only |
| `PLAID_ENV` | `sandbox` (default) or `production` |
| `PLAID_REDIRECT_URI` | HTTPS OAuth return route, e.g. `https://budget.example.com/plaid/oauth` |
| `PLAID_WEBHOOK_URI` | Optional signed Plaid webhook endpoint, e.g. `https://budget.example.com/api/v1/plaid/webhook` |
| `PLAID_PRODUCTS` | Comma-separated Link products; Phase 2B defaults to `transactions` |
| `PLAID_COUNTRY_CODES` | Comma-separated country codes; default `US` |
| `AI_ENABLED` | Enables the server-side Ask Budget provider; requires the selected provider key when true |
| `AI_PROVIDER` | Advisor provider adapter; Phase 3C-2 supports `gemini` and `openai` |
| `GEMINI_API_KEY` | Server-side Gemini API credential; never exposed to the frontend |
| `GEMINI_MODEL` | Gemini model used by Ask Budget; defaults to `gemini-3.6-flash` |
| `OPENAI_API_KEY` | Optional server-side OpenAI API credential when `AI_PROVIDER=openai` |
| `OPENAI_MODEL` | OpenAI Responses API model; defaults to `gpt-5.6` |
| `AI_TIMEOUT_SECONDS` | Provider request timeout, default `45` |
| `AI_MAX_TOOL_CALLS` | Maximum read-only Budget tools requested per answer, default `4` |
| `AI_REQUESTS_PER_MINUTE` | Per-user Advisor request limit in this one-worker deployment, default `12` |

The database connection is assembled with `sqlalchemy.URL.create()` from the
individual `DB_*` settings. A combined database URL is not a supported setting
and cannot override them. Secret values are not included in API responses,
readiness details, exceptions, or application logs.

### Generate production secrets

Generate independent values for each secret. On Ubuntu:

```bash
openssl rand -hex 32
```

On Windows PowerShell:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
-join ($bytes | ForEach-Object { $_.ToString('x2') })
```

Do not reuse one generated value across multiple variables.

### Phase 2B bank connections

Phase 2B adds Plaid Link, encrypted Item credentials, connected institution/account import, OAuth return handling, duplicate-Item prevention, and disconnect. Start in Plaid Sandbox.

Phase 2B adds the `cryptography` runtime dependency. After applying this change, refresh both committed Python lock artifacts from `backend` before committing or deploying:

```powershell
uv lock
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock
```


### Phase 2C transaction synchronization

Each Plaid Item stores its `/transactions/sync` cursor and only advances it after
all pages of one update have been collected and applied atomically. A mutation-
during-pagination response restarts the entire page loop from the original
cursor. A newly connected Item may initially report `NOT_READY` with an empty
cursor; Budget records the status without treating that normal warm-up response
as a failure and retries on a later sync. The importer requests PFCv2 plus
original descriptions, negates Plaid's outflow-positive amount convention at the
provider boundary, reconciles pending/posted transactions, and maps high-level
PFC categories into Budget's existing category set with `Other` as a fallback.

Manual sync is available from **Accounts → Sync now**. Production can also run:

```bash
python -m app.cli sync-plaid
python -m app.cli sync-plaid --item-id <connection-id>
```

The supplied `budget-sync.timer` wakes every minute. Phase 2D marks Items from a
verified Plaid webhook for prompt synchronization and keeps a 15-minute stale
fallback, so polling and webhook refresh share the same tested sync engine.


## Database and migrations

SQLite is allowed only in explicit demo and test modes. Production refuses to
start with demo mode, missing `DB_*` settings, or database TLS disabled.
`DB_SSL_MODE` defaults to `REQUIRED` for backward compatibility. The current OCI
HeatWave service-defined certificate deployment uses `REQUIRED`; use
`VERIFY_IDENTITY` with an explicit `DB_SSL_CA` when the DB is moved to a
certificate chain that the application can trust.

Run migrations from `backend`:

```powershell
alembic upgrade head
```

Migration and runtime configuration use the same programmatic connection
factory. For optional MySQL integration tests, use a disposable empty schema
whose name ends in `_test`; the guard refuses any other schema name.
The opt-in TLS/migration harness and its `TEST_DB_*` contract are documented in
[`backend/tests/README.md`](backend/tests/README.md).

Python resolution is committed in `backend/uv.lock`; production pip installs
use its hash-pinned `backend/requirements.lock` export. Frontend resolution is
committed in `frontend/package-lock.json`, so `npm ci` is reproducible.

## First production start

Before starting the service for the first time, place a fresh random 256-bit
value in the protected environment file:

```text
BOOTSTRAP_TOKEN=<random 256-bit value>
```

The setup screen sends it once in the `X-Bootstrap-Token` header over HTTPS.
The token is constant-time compared with the environment value and is never
stored in the database, returned by the API, written to browser storage, or
logged. After setup succeeds, remove `BOOTSTRAP_TOKEN` from the environment
file and restart `budget-api`; the initialized application no longer requires
it.

Do not expose the uninitialized application publicly before this value is in
place. Full systemd, Nginx, TLS, permissions, and manual deployment steps are
in [deploy/README.md](deploy/README.md).

## Current OCI network

Production currently uses this fixed private topology:

- VCN: `10.0.0.0/16`
- E2 VM: `10.0.0.16` in subnet `10.0.0.0/24`
- MySQL HeatWave: `10.0.1.14` in subnet `10.0.1.0/24`
- Database-subnet **Security List**: stateful TCP ingress to destination port
  `3306`, source `10.0.0.16/32`, all source ports

The active database rule is a subnet Security List, not an NSG. An NSG may
replace it later. Confirm the E2 subnet permits outbound traffic and never open
ports `3306` or `8000` to the internet.

## Commands

Backend (from `backend`):

```powershell
ruff format --check .
ruff check .
mypy app
pytest
python -m app.cli demo-reset
python -m app.cli reset-password --username <username>
```

The reset-password command prompts interactively and revokes active sessions;
it never accepts a password as a command-line argument.

Frontend (from `frontend`):

```powershell
npm ci
npm run lint
npm run typecheck
npm run test:run
npm run build
npm run test:e2e
```

Browser tests expect the demo API and Vite server to be running unless the
script starts them through Playwright configuration.

## API health

- `GET /api/health` is a minimal public liveness check.
- `GET /api/ready` verifies database readiness. Production Nginx blocks public
  access; deployment checks it directly on `127.0.0.1:8000`.

## Manual financial records

Phase 2A adds authenticated, CSRF-protected write routes alongside the existing
read routes:

- `POST /api/v1/accounts`, `PATCH /api/v1/accounts/{account_id}`, and
  `DELETE /api/v1/accounts/{account_id}` for manual accounts.
- `POST /api/v1/transactions`, `PATCH /api/v1/transactions/{transaction_id}`,
  and `DELETE /api/v1/transactions/{transaction_id}` for manual transactions.

Every write is owner-scoped and audited. Records marked `source_type=plaid` are
provider-managed and return `409` from manual edit/delete routes. Deleting a
manual account cascades its transactions through the existing account-owner
foreign key.

All application-generated API failures use a request-correlated envelope:

```json
{"error":{"code":"example_code","message":"Safe message","request_id":"..."}}
```

Nginx-generated transport failures remain generic and disclose no application
detail; the supplied templates provide the same envelope for their explicit
HTTPS-required and rate-limit responses.

## Troubleshooting

- **Production reports that initialization is unavailable:** add a valid
  256-bit `BOOTSTRAP_TOKEN` before the first start, then restart the service.
- **Database connection fails:** verify `DB_HOST` resolves from the VM, the
  database subnet Security List allows `10.0.0.16/32` to TCP `3306`, and E2
  egress permits the connection.
- **TLS connection fails:** confirm `DB_SSL_REQUIRED=true`. The current OCI
  service-defined certificate deployment uses `DB_SSL_MODE=REQUIRED`. If using
  `VERIFY_CA` or `VERIFY_IDENTITY`, configure `DB_SSL_CA` with the trusted CA
  file; `VERIFY_IDENTITY` also requires `DB_HOST` to match the certificate.
- **Login cookie is missing:** production cookies require HTTPS, and Uvicorn
  must trust forwarded headers only from loopback Nginx.
- **Frontend routes return 404:** install the supplied Nginx SPA fallback while
  keeping `/api/` in the dedicated proxy location.
- **A 1 GB build runs out of memory:** build the frontend off-host when
  possible. A small swap file may protect an occasional on-host build but is
  not a substitute for low runtime memory usage.

## Security notes

Financial records are always queried through the authenticated owner. Account
identifiers are masked in the UI. Passwords use Argon2id; session tokens are
opaque and only keyed digests are stored. Unsafe authenticated requests require
a session-bound CSRF token and same-origin validation. Never commit `.env`
files, database dumps, credentials, or generated secrets.

See [Architecture](docs/ARCHITECTURE.md) for residual risks and the current
security boundary.


## Phase 2D transaction intelligence

Phase 2D adds signed Plaid `SYNC_UPDATES_AVAILABLE` webhook intake, user transaction overrides, reusable matching rules, merchant normalization, local recurring-pattern detection, and a Recurring screen. Provider merchant/category/kind values remain stored separately from Budget's interpretation so user changes are reversible. The Plaid webhook JWT is verified with the Plaid JWK, a five-minute replay window, and the raw request-body SHA-256 before any webhook is accepted. The periodic sync timer now runs every minute but only synchronizes Items explicitly marked by a webhook or whose last transaction sync is at least 15 minutes old.


## Phase 3A budget planning

Phase 3A adds annual and monthly budgeting on top of the transaction-intelligence
layer. Users can set one annual plan and let Budget derive monthly baselines,
use a fixed monthly amount, or distribute a category goal differently across
all twelve months. Individual months can override the annual plan or become a
standalone budget, and any month can copy the previous month's effective base
plan.

Budget category actuals always use the interpreted transaction values from
Phase 2D: category overrides, kind overrides, transfer treatment, refunds, and
spending exclusions are honored. Per-category rollover supports `off`,
`surplus`, and `surplus_and_deficit`. Rollover changes monthly availability but
does not rewrite the annual goal.

The Budget screen exposes Month and Year views. Month view includes planned and
actual income, base budget, rollover-adjusted availability, spending,
unallocated income, remaining budget, upcoming recurring obligations, and a
conservative safe-to-spend figure. Safe-to-spend reserves the larger of
remaining category budgets or detected upcoming recurring expenses so the same
obligation is not blindly double-counted. Year view reports annual goals and
year-to-date progress.

Budget APIs:

- `GET/PUT /api/v1/budget/years/{year}/plan`
- `GET /api/v1/budget/years/{year}`
- `GET/PUT/DELETE /api/v1/budget/months/{YYYY-MM}`
- `POST /api/v1/budget/months/{YYYY-MM}/copy-previous`

Migration `20260813_0006` creates the annual-plan, custom-month-distribution,
monthly-budget, and category-allocation tables. All records are owner-scoped
with composite category ownership foreign keys.

## Phase 3B financial planning and forecasting

Phase 3B adds a **Plan** workspace for savings goals, debt payoff planning,
forward-looking cash projections, and read-only what-if scenarios. Goals may be
tracked manually or linked to one depository/investment account; linked balances
update automatically and one account can back only one linked goal. Manual goals
can record contributions without creating artificial bank transactions.

Debt records can be manual or linked to a credit/loan account. Budget compares a
minimum-payment baseline with avalanche, snowball, or custom priority plans.
Per-debt extra payments stay earmarked to that debt first; the global strategy
extra pool and payment capacity freed by paid-off debts then roll toward the
selected strategy target. The payoff simulator reports projected payoff dates
and interest savings without changing the user's real budget.

Forecasting combines depository cash, Phase 2D recurring income/expenses, Phase
3A flexible budget reserves, active goal contributions, and planned debt
payments into 30/60/90-day projections. Linked goal balances are treated as
earmarked reserves rather than spendable cash. If no recurring income pattern
has been detected, planned budget income is used as a conservative fallback.
Forecasts are estimates based on current balances and assumptions, not guaranteed
future balances.

Scenario mode can temporarily model extra debt payments, goal-contribution
changes, spending reductions, and a new monthly expense. Scenario calculations
are rolled back after the response and do not mutate goals, debts, budgets, or
forecast assumptions.

Phase 3B also tightens Phase 3A safe-to-spend: linked goal reserves are protected,
and goal/debt monthly commitments are added only to the extent they are not
already covered by remaining `Savings` or `Debt payments` category budgets.

Planning APIs:

- `GET/POST /api/v1/planning/goals`
- `PATCH/DELETE /api/v1/planning/goals/{goal_id}`
- `POST /api/v1/planning/goals/{goal_id}/contributions`
- `GET/POST /api/v1/planning/debts`
- `PATCH/DELETE /api/v1/planning/debts/{debt_id}`
- `PUT /api/v1/planning/debts/strategy`
- `GET /api/v1/planning/forecast`
- `PUT /api/v1/planning/forecast/assumptions`
- `POST /api/v1/planning/forecast/scenario`

Migration `20260813_0007` creates financial goals/contributions, debts, debt
strategy settings, and forecast assumptions. No new runtime dependency is
required for Phase 3B.


## Phase 3C-1 deterministic insight engine

Phase 3C-1 adds explainable, non-AI financial signals over the transaction-intelligence,
budget, recurring, goal, debt, and forecasting layers. Budget scores active signals as
critical, important, opportunity, or FYI; stores insight history and dismissal state; and
surfaces the highest-priority items on the Dashboard and a dedicated Insights page.

The engine never asks a language model to calculate financial facts. Every amount, date,
variance, payoff opportunity, and forecast warning is produced by Budget's deterministic
services. The stored evidence payload is intentionally sanitized and becomes the future
input boundary for Phase 3C-2 Ask Budget. Migration `20260813_0008` creates the
owner-scoped insight history table.


## Phase 3C-2 Ask Budget AI Advisor

Phase 3C-2 adds a read-only conversational Advisor over Budget's deterministic
financial engines. The `/advisor` workspace automatically treats questions as
quick answers, deeper analysis, or what-if scenarios. It can call only an
explicit allowlist of read-only Budget tools for cash forecasts, goals, debt,
scenarios, category spending, recurring summaries, active insights, and
purchase-affordability checks. Financial facts displayed as evidence cards are
calculated by Budget rather than by the language model.

Provider adapters are isolated behind the same interface. Gemini uses the native Gemini REST API with function calling, SSE streaming, and structured JSON output; the OpenAI adapter remains available as a fallback.
OpenAI requests set `store=false`; Gemini uses its native generate-content API without a server-side conversation store. Context is deliberately sanitized: Plaid
access tokens, routing/account numbers, session/CSRF/bootstrap secrets, raw
webhook payloads, and other credentials are never part of the Advisor context.
Merchant names and transaction descriptions are withheld unless the user opts
in through Settings. Merchant-looking insight text is also generalized while
merchant sharing is disabled.

Advisor conversations are owner-scoped. Users may disable Ask Budget, disable
history entirely for a private session, delete saved Advisor history, or opt in
to merchant/description sharing. Private mode uses a transient owner-scoped
conversation shell for the streaming request and removes it after either a
successful response or a pre-stream planning failure. Phase 3C-2 model tools
remain read-only; Phase 3C-3 adds a separate validated approval path for proposed
financial-plan changes.

Advisor APIs:

- `GET /api/v1/advisor/status`
- `GET/POST/DELETE /api/v1/advisor/conversations`
- `GET/DELETE /api/v1/advisor/conversations/{conversation_id}`
- `POST /api/v1/advisor/conversations/{conversation_id}/messages/stream`

Migration `20260813_0009` adds Advisor privacy preferences plus owner-scoped
conversation/message history. No provider SDK or new daemon is required; the
backend uses the existing HTTPS runtime and the frontend consumes same-origin
server-sent events.

## Phase 3C-3 Advisor actions and financial playbooks

Phase 3C-3 closes the loop between an Advisor recommendation and Budget's existing
planning services. Ask Budget may include a small structured action proposal in a
response, but the model never receives a mutation tool and cannot write financial
data. Budget validates the proposed target IDs and values, simulates the changes
inside its deterministic budget/goal/debt/forecast engines, rolls the simulation
back, and stores only a reviewable proposal.

The first action allowlist supports current-month category budget targets, goal
monthly contributions, per-debt extra payments, debt strategy/extra-budget settings,
and forecast reserve assumptions. No action can move money, initiate a payment,
change a bank connection, delete a transaction, or contact a financial institution.

Each proposal has a deterministic before/after preview and a 24-hour expiry. The
apply endpoint re-checks the proposal's preconditions so a recommendation cannot
overwrite changes made after it was generated. Applying requires an authenticated
CSRF-protected user request. Undo is also guarded: Budget compares the current
resource state with the state written by the proposal and refuses to overwrite newer
manual edits. Applied and undone operations are recorded separately from the AI
conversation and are audit logged. Private/no-history Advisor sessions do not create
action proposals.

Advisor action APIs:

- `GET /api/v1/advisor/proposals/{proposal_id}`
- `POST /api/v1/advisor/proposals/{proposal_id}/apply`
- `POST /api/v1/advisor/proposals/{proposal_id}/reject`
- `POST /api/v1/advisor/proposals/{proposal_id}/undo`

Migration `20260814_0010` adds owner-scoped proposals, proposal actions, deterministic
preview/rollback state, and apply/undo execution history. It adds no new external
runtime dependency.


### Phase 3D reporting snapshots

Phase 3D begins with owner-scoped daily `financial_snapshots`. `python -m app.cli snapshot-reports` upserts one row per user per local calendar day, preserving deterministic Budget, goal, debt, and forecast metrics for historical reporting. The supplied `budget-snapshot.timer` runs hourly so every timezone receives at least one daily capture without tying snapshot timing to the host timezone. The Reports page reads live current values plus stored snapshot history; later 3D checkpoints add transaction-derived spending/budget analytics, goal/debt history, exports, and Advisor report context.

### Phase 3D Stage 2 spending and budget analytics

The Reports workspace now adds deterministic transaction-derived spending/cash-flow and budget-performance views on top of the daily snapshot foundation. `GET /api/v1/reports/spending` supports 30-day, 3-month, 6-month, YTD, and 1-year ranges with income/spending/net cash flow series, prior-period category deltas, top merchants, recurring-vs-discretionary classification, and current-month spending pace. `GET /api/v1/reports/budget` exposes monthly budget-vs-actual rows plus current-year/YTD category utilization and projected year-end spend. Report tables link back to filtered Transactions rather than duplicating transaction detail storage. No new database migration is required for this checkpoint.

### Phase 3D Stage 3 — goals, debt, and forecast analytics

The Reports `Goals & Debt` section combines current goal progress, manual contribution activity, debt payoff modeling, daily reporting snapshots, and the existing deterministic 30/60/90-day forecast engine. Snapshot history drives aggregate goal/debt trajectories and lets Budget score matured forecasts against the actual spendable cash captured on the target date. Forecast accuracy remains empty until enough daily snapshot history exists; no historical values are reconstructed or invented.

### Phase 3D Stage 4 — report center, exports, and Advisor handoff

The Reports workspace now closes Phase 3D with named saved views, reproducible export history, and direct Ask Budget handoff. Users can save a report configuration containing a range plus any combination of Overview, Spending, Budget, and Goals & Debt. The Report Center reopens those configurations and keeps recent CSV/PDF exports available for later download.

Exports are generated server-side from Budget's deterministic reporting services. Each export stores both the normalized report payload and the exact generated file bytes, plus a SHA-256 integrity digest, so later downloads remain identical even if live financial data or the renderer changes. CSV output neutralizes spreadsheet-formula-like text while preserving numeric values. PDF output is generated without an external PDF runtime and presents report KPIs, category detail, budget performance, goals, debt, and forecast data in a compact financial-report layout.

`Ask Budget` can be launched from any Reports section. The frontend sends only the selected report section and range; the backend rebuilds the report context from owner-scoped deterministic services rather than trusting client-supplied financial values. Report context is bounded before it reaches the provider, and merchant names remain excluded unless the user's existing Advisor merchant-sharing preference is enabled.

Report Center APIs:

- `GET/POST /api/v1/reports/saved`
- `PUT/DELETE /api/v1/reports/saved/{report_id}`
- `GET/POST /api/v1/reports/exports`
- `GET /api/v1/reports/exports/{export_id}/download`
- `DELETE /api/v1/reports/exports/{export_id}`

Migration `20260814_0012` adds owner-scoped saved report configurations and exact export history. Stage 4 adds no new provider SDK, daemon, external rendering service, or public listener.

### Phase 4 Stage 1 — private-family identity and account security

Phase 4 begins by replacing Budget's one-owner-only authentication assumptions with a small, invite-only multi-user identity layer. The initial owner remains the administrator. Administrators can invite family members by email; accepting an invitation creates a fully owner-scoped Budget user with a fresh onboarding state and the existing default category catalog. There is no public registration endpoint.

Users can authenticate with a local password or an explicitly linked Google OpenID Connect identity. A Google account is never silently attached merely because its email matches an existing Budget user: an existing local user must sign in first and link Google from Settings. A Google-first account can be created only from a valid invitation whose email matches Google's verified email claim. Invitation acceptance also verifies the invited email because possession of the single-use invitation is the account-creation proof; Google accounts additionally require Google's verified-email claim.

Security Settings now includes active-session management, password reset, Google connection management, optional TOTP for password sign-in, one-time recovery codes, administrator invitation/user controls, and self-service account deletion. Password reset invalidates all existing sessions. TOTP secrets and recovery codes are encrypted at rest with the existing application encryption key. Google OAuth state and nonce values, invitation tokens, reset tokens, session tokens, and 2FA challenge tokens are stored only as keyed digests rather than plaintext.

Google and SMTP are optional. With `EMAIL_DELIVERY=disabled`, the administrator can copy private invitation and password-reset links directly from Settings, which keeps the app useful for a small trusted family deployment without adding a mail provider. Migration `20260814_0013` adds the Stage 1 identity/security records and marks the existing owner as the first administrator.

### Phase 4 Stage 2 — reliability and backups

The private-family deployment now includes admin-only operational health, scheduled logical DB
backups, retention, integrity verification, guarded restore drills, and structured request
logging. Local/demo backups are full-restored into a disposable SQLite database for verification;
production MySQL restore drills require a separate empty `budget_restore_*` database so the live
database can never be selected accidentally. See `deploy/README.md` for the systemd units and
production procedure.

### Phase 4 Stage 3 — onboarding and customizable dashboard
The Dashboard now has per-user card ordering/resizing/hiding, presets, guided onboarding, data-freshness indicators, app-wide toast feedback, and an embedded Ask Budget chat card with contextual prompts and full-Advisor continuation.

### Phase 4 Stage 5 Plaid Production readiness

Stage 5 makes the Plaid environment explicit per connected Item and adds update-mode repair flows before the server is switched from Sandbox to Production. Existing Items created before this migration are marked `sandbox`; Plaid Items are not portable across environments, so a Sandbox test connection must be removed and linked again after Production credentials are enabled.

Connection cards expose a small user-facing health model (`Connected`, `Needs attention`, or a Sandbox/Production mismatch) rather than raw provider state. `ITEM_LOGIN_REQUIRED`, expiring authorization, planned disconnects, revoked permission, and newly detected accounts can launch Link in update mode. Update mode reuses the existing encrypted access token; Budget never exchanges the Link `public_token` again for an updated Item.

For safe local testing, a Sandbox connection can be forced into the login-required state with:

```powershell
.\.venv\Scripts\python.exe -m app.cli plaid-sandbox-reset-login
# If more than one Sandbox connection exists, pass --item-id <connection-id>.
```

Then open **Accounts → Reconnect** and complete Link. The command refuses to run when `PLAID_ENV` is not `sandbox`.

Before the eventual production cutover, run the secret-free preflight from the production environment:

```bash
python -m app.cli plaid-readiness
```

The preflight requires Production mode, configured credentials, HTTPS redirect/webhook URLs, Transactions, and no remaining Sandbox Items. It prints configuration state and connection counts but never prints Plaid secrets or access tokens.

### Phase 4 Stage 6 — performance and maintenance

Stage 6 keeps the private/family deployment bounded without introducing queues, caches, or a second runtime. Migration `20260815_0019` extends the primary transaction date index with the stable `id` tie-breaker used by transaction pagination and adds expiry/retention indexes for sessions, invitations, password-reset tokens, login throttles, and report exports.

`python -m app.cli run-maintenance` performs conservative database housekeeping. It removes only expired authentication artifacts, old audit events, and reproducible report-export blobs beyond the configured age/count limits. It never automatically deletes transactions, accounts, budgets, goals, financial snapshots, notifications, Advisor history, or Plaid Items. The supplied `budget-maintenance.timer` runs this bounded cleanup daily and records its result in the existing operational heartbeat table.

Admin **System health** now shows the maintenance worker, report-export database storage, active retention policy, and a low-free-space warning using the configured minimum. The defaults keep 7 days of expired auth artifacts, 365 days of audit history, report exports for 90 days with at most 50 per user, and warn when the backup volume falls below 2 GB free.

### Phase 4 Stage 7 — privacy and import

Stage 7 closes Phase 4 with user-controlled data portability. Settings now offers a secret-free JSON export of the user's Budget data, a complete transactions CSV export, a CSV import template, idempotent CSV history import into manual accounts, and the existing self-service account deletion flow in one Data & privacy panel. CSV import is intentionally limited to manual accounts so historical files cannot create duplicate provider-managed Plaid transactions; repeated imports use a deterministic row fingerprint and are skipped safely.

Ask Budget privacy is also more explicit: merchant names, transaction descriptions, custom goal/debt names, conversation retention, and the Advisor itself are independent controls. Goal and debt names are private by default while deterministic planning amounts and projections remain available to the Advisor.

### Phase 5A — security hardening

Phase 5 begins with an adversarial hardening pass before the visual redesign and new analytics. Production now refuses weak/reused application secrets and wildcard `ALLOWED_HOSTS`, validates that configured public/OAuth/Plaid URLs belong to an allowed host, blocks explicitly cross-site state-changing browser requests, places a bounded request-size guard in FastAPI, and marks every API response non-cacheable with defense-in-depth security headers.

Sensitive full-data and transaction exports are recorded in the existing audit trail without logging exported content. `python -m app.cli security-audit` prints a secret-free posture report covering configuration, bootstrap removal, schema currency, database TLS mode, coarse database-grant scope, and protected-file/backup permissions. Warnings are intentionally distinct from hard failures so the current OCI HeatWave `REQUIRED` TLS mode can remain operational while certificate-identity verification is evaluated separately.

The production Nginx template adds tighter connection/body timeouts, raises the body ceiling only enough to support the JSON-wrapped Stage 7 2 MB CSV importer, and rate-limits password reset, two-factor, invitation acceptance, and CSV-import entry points. Dependabot plus an opt-in/pull-request security workflow continuously audit pinned Python and production npm dependencies. Cross-user ownership regression tests explicitly verify that guessed financial resource IDs remain inaccessible.


### Phase 5B — Aurora Ledger visual identity

Phase 5B establishes Budget's new liquid-glass design system without shipping Phase 5 to production yet. Desktop navigation is an icon-first glass rail with a draggable edge that snaps between icon-only, compact-label, and full widths. Dashboard widgets now use three deliberate sizes — Compact, Standard, and Hero — and resize by dragging the lower-right glass grip instead of cycling a size button. The existing per-user dashboard preference API persists those three sizes; legacy Phase 4 `small`, `medium`, `wide`, and `large` values are translated automatically on read.

The visual system uses an atmospheric navy/indigo/violet canvas, translucent refractive surfaces, richer financial typography, and gradient data-visualization primitives. It deliberately avoids perspective tricks that distort values: Phase 5C can build the Sankey and later 3D-feeling visualizations on top of this foundation while preserving truthful geometry, reduced-motion behavior, keyboard resize controls, and the mobile navigation fallback.

### Phase 5C — cash flow and volumetric Sankey

Phase 5C turns cash flow into an interactive, reusable analytics model rather than a decorative chart. `GET /api/v1/cash-flow` derives a conserved flow graph directly from owner-scoped transactions and supports month, calendar-year, and bounded custom ranges. Transfers and user-excluded transactions are omitted from the map; refunds are modeled as cash inflows rather than silently reducing expense ribbons, and an explicit cash-shortfall source balances periods whose outflows exceed inflows. Positive residual cash is shown as retained cash. Provider and manually categorized debt/savings expenses keep their distinct financial meaning.

The Dashboard cash-flow widget now follows the Phase 5B Compact/Standard/Hero information-density model. Compact presents headline cash-flow figures, Standard renders a condensed flow map, and Hero exposes the full optical-glass Sankey with range controls, proportional volumetric flow tubes, prior-period comparisons, transaction counts, transaction drill-down, and an `Ask Budget` handoff for the selected flow. Visual depth is created with lighting, transparency, shadows, and specular layers while ribbon widths remain proportional to the underlying values. No new runtime chart dependency or database migration is required; the production schema remains `20260815_0020` until the coordinated Phase 5 release.
