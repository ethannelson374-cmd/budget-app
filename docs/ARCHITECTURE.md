# Budget architecture and security decisions

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
scheduler, production Node process, or multi-service orchestration in the
current deployment.

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

The Phase 1 migration establishes:

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

The Phase 2A migration adds `source_type` to accounts and transactions, with
`manual` and `plaid` as the only accepted values. This lets manual CRUD remain
available without making future provider-managed records mutable through the
same endpoints.

## Secret, bootstrap, and authentication design

All secret settings are opaque/redacted and the settings object is never logged
or serialized:

| Variable | Phase 1 use |
| --- | --- |
| `APP_SECRET` | Domain-separated HMAC key for privacy-preserving throttle and audit identifiers. |
| `SESSION_SECRET` | HMAC key for session-token and CSRF-token digests. Rotation invalidates active sessions. |
| `ENCRYPTION_KEY` | Derives the authenticated-encryption key for stored Plaid access tokens. |
| `BOOTSTRAP_TOKEN` | Environment-only authorization for creation of the first owner. |
| `DB_PASSWORD` | Passed only to programmatic database connection construction. |

Logs, exception details, error responses, readiness output, audit metadata, and
test snapshots must not contain these values. Phase 2B uses `ENCRYPTION_KEY` only server-side to protect long-lived Plaid access tokens before they are written to the database.

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

Phase 2A adds owner-scoped manual financial CRUD without changing the one-worker
runtime model. Accounts and transactions now carry a `source_type` of `manual`
or `plaid`. Only `manual` records may be edited or deleted through these CRUD
endpoints; this is a forward-compatible boundary for Plaid-managed records.
Mutations require the existing authenticated session, CSRF token, and same-origin
checks and write sanitized audit events. Account deletion relies on the existing
database ownership foreign keys and cascades its transactions.

Webhook-driven synchronization, advanced category rules, budgets, recurring
detection, forecasting, goals, debt workflows, snapshots, AI, reports,
MFA/social login/email recovery, offline financial access, full OCI
provisioning, certificate automation, backup/restore automation, and automated
rollback remain deferred.


## Plaid Item boundary (Phase 2B)

Plaid credentials are server-only. FastAPI creates Link tokens and exchanges one-time public tokens. The resulting long-lived access token is encrypted with AES-GCM using a purpose-derived key from `ENCRYPTION_KEY`, with per-token random nonces and authenticated context binding the owner and Plaid Item. HeatWave stores ciphertext and nonce, never plaintext access tokens.

Connected accounts are marked `source_type=plaid` and attached to a user-owned `plaid_items` record. Manual CRUD continues to reject provider-managed accounts. Disconnect calls Plaid `/item/remove` before deleting the local Item and its connected accounts.

## Plaid transaction synchronization (Phase 2C)

Each Item owns one incremental Transactions cursor. The sync service retrieves all
available pages before mutating local transaction state or advancing the cursor;
if Plaid reports a mutation during pagination, collection restarts from the
original cursor. This keeps the cursor and the local added/modified/removed patch
atomic from Budget's perspective.

Plaid transaction amounts are normalized once at the integration boundary to
Budget's signed convention. PFCv2 primary/detailed/confidence metadata and the raw
original description are retained for later categorization and recurring-charge
work. Pending-to-posted replacements delete the earlier pending record when the
posted transaction references its Plaid identifier. Plaid transactions remain
provider-managed and read-only through manual CRUD endpoints.

Automatic polling uses a short-lived systemd oneshot invoked by a persistent
timer rather than adding a queue or long-running scheduler to the E2 Micro VM.
The authenticated **Sync now** API uses the same service. Webhook verification can
later trigger this same engine without duplicating transaction reconciliation.


## Phase 2D intelligence boundary

Plaid-originated values remain provider truth on each transaction. Budget stores display-merchant, category, kind, and spending-exclusion overrides separately and applies ordered user rules only to Plaid transactions that have not been explicitly tuned. Recurring streams are derived locally from posted, non-transfer, non-excluded transactions with at least three observations and a recognized cadence; they are projections, not provider guarantees. Plaid `SYNC_UPDATES_AVAILABLE` webhooks are signature/body-hash verified and only mark an Item as sync-needed. A lightweight systemd timer consumes those hints while retaining a 15-minute stale-item safety net.


## Phase 3A budgeting boundary

Budget planning remains inside the modular monolith and adds no background
worker or external dependency. Annual plans provide the default monthly
baseline; month records are either standalone budgets or explicit overrides.
Annual category rows support even, fixed-monthly, and twelve-month custom
distribution. Monthly availability is calculated as base allocation plus
derived rollover, while annual goals remain stable.

Actual budget spending is calculated from the Phase 2D effective transaction
interpretation rather than raw Plaid metadata. Transfers and excluded
transactions do not consume spending budgets, refunds reduce spending, and
category/kind overrides are honored. Safe-to-spend is intentionally
deterministic and explainable; no AI inference is involved in Phase 3A.

## Phase 3C-1 insight boundary

Financial insights remain deterministic and inside the modular monolith. The insight engine
consumes normalized transaction interpretation, budget views, recurring streams, financial
goals, debt simulations, and cash forecasts; it does not call a language model or send
financial data to an external AI provider. Each signal stores an owner-scoped fingerprint,
priority score, explanation evidence, recommended next step, history state, and a route back
to the underlying Budget feature.

Refreshing insights upserts currently applicable signals and resolves conditions that no
longer apply. Dismissed signals stay dismissed while the same fingerprint remains active, so
a refresh cannot immediately resurrect something the user intentionally hid. The sanitized
explanation payload is the intended future boundary for Phase 3C-2 rather than raw Plaid
payloads, credentials, account numbers, or provider tokens.
