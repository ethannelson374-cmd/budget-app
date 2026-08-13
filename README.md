# Budget

Budget is a single-user-first personal finance dashboard built as a lightweight
modular monolith. Phase 1 provides secure first-run account setup, a persistent
demo environment, category and income settings, and a calculated monthly
dashboard. Phase 2A adds writeable manual accounts and transactions so the
production dashboard can use real user-entered financial data before bank sync
is enabled. It is designed to run on an Oracle Cloud E2 Micro VM without
containers.

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

Plaid/live bank synchronization, recurring-charge analysis, budgets, goals,
debt workflows, forecasts, AI insights, reports, and deployment automation are
still intentionally deferred to later Phase 2/3 work.

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
| `ENCRYPTION_KEY` | Accepted and reserved for Phase 2 Plaid-token encryption |
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
