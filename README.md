# Budget

Budget is a single-user-first personal finance dashboard built as a lightweight
modular monolith. Phase 1 provides secure first-run account setup, a persistent
demo environment, category and income settings, and a calculated monthly
dashboard. Phase 2A adds writeable manual accounts and transactions, Phase 2B
adds secure Plaid bank connections, and Phase 2C adds cursor-based Plaid
transaction synchronization with manual and scheduled refresh. It is designed to
run on an Oracle Cloud E2 Micro VM without containers.

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
  that runs the same CLI sync path every 15 minutes.
- Connected account balances are refreshed from transaction-sync responses while
  manual records remain unaffected and Plaid transactions remain read-only.

Webhook-triggered synchronization, recurring-charge analysis, budgets, goals,
debt workflows, forecasts, AI insights, reports, and deployment automation are
still intentionally deferred to later work.

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

The supplied `budget-sync.timer` runs the same CLI path approximately every 15
minutes. Webhook-triggered sync is intentionally deferred so polling and webhooks
share one tested synchronization engine later.


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
