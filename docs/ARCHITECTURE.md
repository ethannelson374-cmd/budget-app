# Phase 1 architecture and security decisions

## System shape

Budget is a lightweight modular monolith sized for one Oracle Cloud E2 Micro VM
with 1 GB RAM:

```text
Browser --HTTPS--> Nginx :443 --HTTP/loopback--> Uvicorn/FastAPI :8000
                                                    |
                                                    | MySQL/TLS over VCN
                                                    v
                                           HeatWave 10.0.1.14:3306
```

Nginx serves the React/Vite static bundle and is the only public application
listener. FastAPI runs synchronously as a single Uvicorn worker under systemd.
SQLAlchemy/PyMySQL owns database access. There is no Docker, Redis, Celery,
scheduler, production Node process, or multi-service orchestration in Phase 1.

Backend modules separate configuration/database setup, ORM models, schemas,
authentication/session services, dashboard calculations, and API routers while
remaining one deployable process. The frontend is one TypeScript application
with routes for setup, login, dashboard, accounts, transactions, and settings.
Production is same-origin, so CORS is not enabled; Vite proxies `/api` only in
local development.

## Configuration and database boundary

Configuration comes from individually named environment fields. Production
requires `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and
`DB_SSL_REQUIRED=true`. `DB_SSL_MODE` defaults to `REQUIRED`; optional
`DB_SSL_CA` is mandatory for `VERIFY_CA` and `VERIFY_IDENTITY`. The application creates a SQLAlchemy `URL` object
programmatically with `URL.create("mysql+pymysql", ...)`; runtime and Alembic use
the same factory. `DATABASE_URL` is neither read nor treated as authoritative.
This avoids ambiguous precedence and safely represents reserved characters in
database passwords.

SQLite is restricted to explicit demo/test operation. Production rejects
SQLite, demo mode, missing database fields, and disabled database TLS. The
small-VM MySQL engine uses a bounded pool (two persistent connections, one
overflow connection), pre-ping, LIFO reuse, recycling, and finite connect/read/
write timeouts.

For HeatWave, production always requires TLS. `DB_SSL_MODE=REQUIRED` encrypts
the connection and is the current mode for the OCI service-defined certificate
deployment. `VERIFY_CA` validates a CA file supplied by `DB_SSL_CA`, while
`VERIFY_IDENTITY` additionally validates `DB_HOST` against the certificate and
is the preferred future mode with a user-defined/trusted certificate chain.
Readiness verifies database connectivity and a non-empty negotiated TLS cipher
but never returns hostnames, credentials, or connection strings.

The initial migration establishes:

- a singleton installation-complete record;
- users, one-to-one user settings, opaque sessions, persistent login throttles,
  and sanitized audit events; and
- institutions, user-owned accounts, categories, and transactions.

Every owned data query is constrained by the authenticated user. Foreign keys,
unique constraints, duplicate-import protection, and user/date/account/category
indexes enforce the same boundary below the API layer. Money uses
`DECIMAL(19,4)` and is serialized as strings. UTC event timestamps and financial
posting dates are separate. Account balances are owner-perspective signed
values; transactions use positive inflows and negative outflows. Transfers are
excluded from spending and refunds reduce spending. Cross-currency values are
reported separately rather than implicitly converted.

## Secret, bootstrap, and authentication design

All secret settings are opaque/redacted and the settings object is never logged
or serialized:

| Variable | Phase 1 use |
| --- | --- |
| `APP_SECRET` | Domain-separated HMAC key for privacy-preserving throttle and audit identifiers. |
| `SESSION_SECRET` | HMAC key for session-token and CSRF-token digests. Rotation invalidates active sessions. |
| `ENCRYPTION_KEY` | Accepted and redacted, but reserved for reversible Plaid-token encryption in Phase 2. |
| `BOOTSTRAP_TOKEN` | Environment-only authorization for creation of the first owner. |
| `DB_PASSWORD` | Passed only to programmatic database connection construction. |

Logs, exception details, error responses, readiness output, audit metadata, and
test snapshots must not contain these values. Phase 1 stores no value requiring
reversible application encryption, so `ENCRYPTION_KEY` is intentionally unused
beyond validation/redaction.

Before the first production start, the operator places a randomly generated
256-bit-or-stronger `BOOTSTRAP_TOKEN` in `/etc/budget-app/budget.env`. The setup
form keeps it only in component memory and sends it as `X-Bootstrap-Token` over
HTTPS. The API compares it to the environment secret in constant time. It is
never written to the database in plaintext or hashed form; only installation
completion is persisted. Setup uses a database transaction/lock so simultaneous
requests can create at most one initial owner. After completion, setup returns
`409`, the environment token can be removed, and initialized startup remains
valid. An uninitialized production instance without the token fails readiness
without disclosing configuration details.

Passwords are 12-128 characters, are neither trimmed nor Unicode-normalized,
and are hashed with Argon2id (19 MiB, two iterations, parallelism one). Login
uses the same outward failure for an unknown identity and a wrong password and
runs a dummy verification for unknown users. Persistent HMAC-keyed identity/IP
throttles supplement Nginx's per-IP edge limits.

Sessions are random 256-bit opaque bearer values. Only `SESSION_SECRET` HMAC
digests are stored. They have a 12-hour idle limit, a seven-day absolute limit,
and are revoked on logout or password reset. Production sends the session in a
`__Host-` cookie with `Secure`, `HttpOnly`, `SameSite=Lax`, and `Path=/`.
Each session also owns an unpredictable CSRF token; unsafe requests require its
`X-CSRF-Token` value plus a valid same-origin `Origin`/`Referer` check.

Nginx overwrites forwarded client headers and Uvicorn trusts proxy headers only
from `127.0.0.1`. API responses are `no-store`; HTML and the manifest revalidate;
only Vite's content-hashed assets receive immutable caching. The application
does not install a service worker or cache authenticated financial data.

## OCI network decision

The active topology is:

| Network element | Current production value |
| --- | --- |
| VCN | `10.0.0.0/16` |
| E2 subnet | `10.0.0.0/24` |
| E2 VM | `10.0.0.16` |
| MySQL subnet | `10.0.1.0/24` |
| MySQL endpoint | `10.0.1.14` |

The active MySQL control is the **database subnet Security List**, not an NSG.
Its rule is stateful TCP ingress from CIDR `10.0.0.16/32`, all source ports, to
destination port `3306`. Therefore only the current E2 private address may
initiate the database connection, subject also to the E2 subnet's outbound
policy. MySQL has no public `3306` path. Uvicorn binds to `127.0.0.1:8000` and
Nginx alone accepts public web traffic on `80`/`443`.

A future migration may replace the Security List rule with an NSG for
resource-scoped policy. No NSG is claimed as part of the current database
network path.

## Runtime and operational tradeoffs

One worker is an intentional memory/connection budget, not a high-availability
design. systemd restarts failures, applies process/filesystem hardening, limits
tasks, and caps API memory. Nginx terminates TLS, blocks public readiness, keeps
API failures out of the SPA fallback, rate-limits login/setup, and forwards the
unchanged `/api/...` path. Database migrations are an explicit operator step and
never an application-start side effect.

Frontend builds should happen off the VM. An optional small swap file can make
an exceptional on-VM build less likely to be killed, but no Node process remains
after deployment. The supplied Nginx sites disable access logging; Nginx error
logs may still contain a request target, so secrets must never be put in URLs.
Journald records application operational events without environment values,
request bodies, cookies, authorization headers, bootstrap headers, or CSRF
headers.

Phase 1 deliberately defers Plaid and live synchronization, manual financial
CRUD, advanced category rules, budgets, recurring detection, forecasting,
goals, debt workflows, snapshots, AI, reports, MFA/social login/email recovery,
offline financial access, full OCI provisioning, certificate automation,
backup/restore automation, and automated rollback.
