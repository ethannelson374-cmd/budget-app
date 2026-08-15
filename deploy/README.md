# Manual Budget deployment

This directory contains the small-VM production configuration for the Budget
application. The target is an Oracle Cloud E2 Micro VM running Ubuntu with 1 GB
RAM. It deliberately uses no Docker, no Node process, one Uvicorn worker, and a
same-origin Nginx frontend.

This is a manual deployment procedure. It does not automate provisioning,
certificate issuance, releases, rollback, backups, or restore.

## Active OCI network topology

The production database rule is currently implemented by the **database
subnet Security List**. An NSG is not part of the active MySQL path.

| Component | Address |
| --- | --- |
| VCN | `10.0.0.0/16` |
| E2 subnet | `10.0.0.0/24` |
| E2 private IP | `10.0.0.16` |
| MySQL subnet | `10.0.1.0/24` |
| MySQL private IP | `10.0.1.14` |

The database subnet Security List has this stateful ingress rule:

| Setting | Value |
| --- | --- |
| Source type | CIDR |
| Source | `10.0.0.16/32` |
| IP protocol | TCP |
| Source ports | All |
| Destination port | `3306` |

This permits only the current E2 VM address to initiate a MySQL connection.
Confirm that the E2 subnet outbound rules permit the corresponding connection.
Do not add public ingress for MySQL `3306`; Uvicorn binds only to loopback and
must not expose `8000`. Public ingress should be limited to `80`/`443`, plus SSH
from an explicitly restricted administration source.

### OCI Ubuntu host-firewall note

The deployed OCI Ubuntu image also has a host-level `iptables` policy in
addition to UFW and the subnet Security List. On this VM the stock chain had a
catch-all reject before UFW's later rules, so inbound HTTP/HTTPS reached the VNIC
but was rejected before Nginx could answer. Keep explicit stateful accepts for
TCP `80` and `443` above that reject and persist them:

```bash
sudo iptables -I INPUT 5 -m conntrack --ctstate NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 5 -m conntrack --ctstate NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Verify ordering with `sudo iptables -L INPUT -n -v --line-numbers`; the 80/443
ACCEPT entries must appear before the catch-all REJECT. UFW should still allow
`Nginx Full`, and OCI Security List ingress for public HTTP/HTTPS remains
`0.0.0.0/0` to destination TCP ports `80` and `443`. Never open `8000` or
`3306` publicly.

An NSG could replace the Security List rule in a later network revision if
resource-scoped policy is desired. That is a future option, not a description of
the current deployment.

## 1. Prepare Ubuntu and a release

Install Python 3.12, its venv support, Nginx, build tools required by the locked
Python dependencies, and a MySQL client for diagnostics. Build the React bundle
on a workstation or in CI; do not keep Node on this 1 GB VM.

Create a non-login service account and deployment directories:

```bash
sudo adduser --system --group --home /var/lib/budget-app budgetapp
sudo install -d -o root -g budgetapp -m 0750 /etc/budget-app
sudo install -d -o root -g root -m 0755 /opt/budget-app/releases
sudo install -d -o root -g root -m 0755 /var/www/letsencrypt
sudo python3.12 -m venv /opt/budget-app/venv
sudo /opt/budget-app/venv/bin/python -m pip install --upgrade pip
```

Copy a release (including `backend`, the prebuilt `frontend/dist`, `deploy`, and
the dependency lockfiles) to a versioned directory below
`/opt/budget-app/releases/`. Point `/opt/budget-app/current` at that directory.
Install backend dependencies from the committed, hash-pinned production export;
do not run a floating dependency upgrade during deployment:

```bash
sudo /opt/budget-app/venv/bin/pip install --require-hashes \
  -r /opt/budget-app/current/backend/requirements.lock
```

Keep the release owned by root and read-only to `budgetapp`. The service writes
only to the systemd-managed `/var/lib/budget-app` state directory.

## 2. Configure secrets and HeatWave

Create `/etc/budget-app/budget.env`, owned by `root:budgetapp` with mode `0640`.
Use the existing production values for `APP_SECRET`, `SESSION_SECRET`, and
`ENCRYPTION_KEY`; do not rotate them as part of a routine deployment.

```dotenv
APP_ENV=production
DEMO_MODE=false
APP_SECRET=<existing-secret>
SESSION_SECRET=<existing-secret>
ENCRYPTION_KEY=<existing-key>
BOOTSTRAP_TOKEN=<random-256-bit-value>
ALLOWED_HOSTS=budget.example.com,127.0.0.1,localhost
LOG_LEVEL=INFO

DB_HOST=<mysql-internal-fqdn>
DB_PORT=3306
DB_NAME=<database-name>
DB_USER=<database-user>
DB_PASSWORD=<database-password>
DB_SSL_REQUIRED=true
DB_SSL_MODE=REQUIRED
DB_SSL_CA=
```

Keep the public hostname and both loopback names in `ALLOWED_HOSTS`. The public
hostname protects proxied browser traffic, while `127.0.0.1` and `localhost`
allow the documented host-local liveness and readiness checks.

`budget.env` uses systemd `EnvironmentFile` syntax; it is not a shell script.
Quote values containing whitespace, `#`, quotes, or backslashes according to
systemd's environment-file rules (single quotes are simplest when the value has
no single quote). Do not `source` the file and do not URL-encode
`DB_PASSWORD`—reserved URL characters are passed literally and handled safely
by SQLAlchemy's programmatic `URL.create()` construction.

Before the **first application start**, generate and add a bootstrap token with
at least 256 bits of entropy. For example, `openssl rand -hex 32` produces a
64-character hexadecimal token with 256 random bits. Put the result only in the
environment file:

```dotenv
BOOTSTRAP_TOKEN=<output-from-openssl-rand-hex-32>
```

Never place the token in a command argument, URL/query string, Git, a deployment
transcript, or a ticket. Both supplied Budget Nginx site templates disable
access logging, and Nginx does not log request headers or bodies here. Error
logs can still include a request target, which is another reason secrets must
never appear in URLs. The application compares the
`X-Bootstrap-Token` header in constant time and stores only an
installation-complete marker, never the token itself.

`APP_SECRET` keys privacy-preserving throttle/audit identifiers.
`SESSION_SECRET` protects session and CSRF token digests; rotating it invalidates
active sessions. `ENCRYPTION_KEY` is loaded and redacted and encrypts Plaid access tokens with
authenticated encryption. Secret values must never appear in logs or API output.

Use the private HeatWave internal FQDN for `DB_HOST`; in the current OCI
deployment it resolves inside the VCN to `10.0.1.14`. `DB_SSL_REQUIRED=true` is
always mandatory in production. The current HeatWave service-defined
certificate deployment uses `DB_SSL_MODE=REQUIRED`, which enforces encrypted
transport and verifies after connect that a TLS cipher was negotiated.

For a future certificate chain that can be explicitly trusted, set
`DB_SSL_MODE=VERIFY_CA` or preferably `VERIFY_IDENTITY` and set `DB_SSL_CA` to
the readable CA file path. `VERIFY_IDENTITY` also validates `DB_HOST` against
the certificate identity. The application constructs its SQLAlchemy URL from
the individual `DB_*` fields. `DATABASE_URL` is never the source of truth.

Lock down the file after editing:

```bash
sudo chown root:budgetapp /etc/budget-app/budget.env
sudo chmod 0640 /etc/budget-app/budget.env
```

## 3. Install and verify systemd

```bash
sudo install -o root -g root -m 0644 \
  /opt/budget-app/current/deploy/systemd/budget-api.service \
  /etc/systemd/system/budget-api.service
sudo systemd-analyze verify /etc/systemd/system/budget-api.service
sudo systemctl daemon-reload
```

Do not start the service yet. Migrations are a separate, explicit deployment
step and TLS must be ready before first-user setup. Run Alembic from the backend
working directory in a transient service. Its `EnvironmentFile` property makes
systemd parse the exact same environment file as the API without treating
database passwords as shell source code:

```bash
sudo systemd-run --wait --collect --pipe \
  --unit=budget-migrate \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/alembic upgrade head
```

Do not use `source`, `.`, `env`, `systemctl show-environment`, or shell tracing
to load or inspect this file. The transient unit is collected when it finishes;
its exit status must be successful before deployment continues.

## 4. Bootstrap HTTP, obtain TLS, and enable HTTPS

Replace every `budget.example.com` in the selected template with the real host.
Install the shared snippets:

```bash
sudo install -o root -g root -m 0644 \
  /opt/budget-app/current/deploy/nginx/budget-security-headers.conf \
  /etc/nginx/snippets/budget-security-headers.conf
sudo install -o root -g root -m 0644 \
  /opt/budget-app/current/deploy/nginx/budget-api-proxy.conf \
  /etc/nginx/snippets/budget-api-proxy.conf
```

Install `budget-bootstrap-http.conf` as the only enabled Budget site and run
`sudo nginx -t` before reloading Nginx. This temporary site supports the ACME
HTTP-01 webroot at `/var/www/letsencrypt` and public liveness at `/api/health`.
It returns `426` without proxying all other API paths, so FastAPI cannot accept
setup credentials or the bootstrap token over cleartext HTTP. Do not open or use
the setup form until the final HTTPS site is active.

Obtain the certificate with the operator's chosen ACME client. Certificate
automation remains operator-managed. Then install `budget-https.conf`, update its host
and certificate paths, disable the bootstrap site, and verify/reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Only one supplied site template may be enabled at a time because both define
the `$budget_hsts` HTTP-context map. The final site:

- serves the ACME path over HTTP, rejects `/api` and `/api/...` over HTTP with a
  JSON `426` (without redirecting or replaying unsafe requests), and redirects
  other HTTP traffic to the configured HTTPS host;
- serves `/opt/budget-app/current/frontend/dist` with SPA fallback;
- proxies `/api/...` to `127.0.0.1:8000` without removing `/api`;
- returns `404` for public `/api/ready` while leaving the loopback endpoint
  available to host-local monitoring;
- rate-limits first-user setup and login, returning a JSON `429` with
  `Retry-After`;
- marks API responses `no-store`, revalidates HTML/manifest files, and caches
  Vite's hashed `/assets/` files immutably; and
- supplies TLS and browser security headers.

Both supplied site templates disable Nginx access logging. Operational events
remain available in error logs and journald. Nginx error logs can contain a
request target, so never place financial values or secrets in a URL; the app
uses a header for the one-time bootstrap credential.

## 5. First start and first-user setup

Once the final HTTPS site is active and migrations succeeded:

```bash
sudo systemctl enable --now budget-api
curl --fail --silent http://127.0.0.1:8000/api/health
curl --fail --silent http://127.0.0.1:8000/api/ready
sudo systemctl status budget-api --no-pager
```

Complete `/setup` through the HTTPS origin. Enter the bootstrap token only into
the setup form; the frontend holds it in component memory and sends it in the
`X-Bootstrap-Token` header. After setup succeeds, remove the
`BOOTSTRAP_TOKEN=...` line from `/etc/budget-app/budget.env` and restart the API:

```bash
sudo systemctl restart budget-api
```

An initialized installation starts without the token. An uninitialized
production installation without it fails readiness with a generic remediation
message and no secret material.

## Operations and checks

Use journald without dumping the environment:

```bash
journalctl -u budget-api --since today
systemctl show budget-api -p MainPID -p MemoryCurrent -p MemoryPeak -p TasksCurrent
ss -lnt
```

Expected listeners are Nginx on public `80`/`443` and Uvicorn on
`127.0.0.1:8000`; no listener on this VM should expose `3306`. From an approved
external host, verify that neither `8000` nor `3306` is reachable. From the VM,
verify that MySQL negotiates TLS and reports a non-empty cipher. If the
deployment later moves to `VERIFY_IDENTITY`, also verify the configured CA and
hostname identity using the same internal FQDN as the application.

The unit caps the API at 384 MB, raises pressure at 300 MB, and limits
concurrency and tasks. Prefer off-VM frontend builds. If an emergency on-VM
build is unavoidable, provision a small encrypted/restricted swap file first,
stop the API during the build if necessary, remove Node afterward, and monitor
memory pressure. Swap is a safety valve, not a substitute for the one-worker
design.

For each manual release: install locked dependencies, run migrations explicitly,
verify `nginx -t` and `systemd-analyze verify`, switch the release symlink,
restart `budget-api`, and check loopback liveness/readiness plus one HTTPS
frontend/API smoke path. The repository intentionally supplies no automated rollback;
database compatibility must be considered before switching back to an older
release.


## Phase 2B Plaid Sandbox configuration

1. In the Plaid Dashboard, add `https://budget.od3ssa.com/plaid/oauth` to Allowed Redirect URIs.
2. Add the Sandbox credentials only to `/etc/budget-app/budget.env` (never to Git):

```text
PLAID_CLIENT_ID=<sandbox-client-id>
PLAID_SECRET=<sandbox-secret>
PLAID_ENV=sandbox
PLAID_REDIRECT_URI=https://budget.od3ssa.com/plaid/oauth
PLAID_WEBHOOK_URI=https://budget.od3ssa.com/api/v1/plaid/webhook
PLAID_PRODUCTS=transactions
PLAID_COUNTRY_CODES=US
```

3. Restart `budget-api` after updating the environment. The existing `ENCRYPTION_KEY` encrypts Plaid access tokens before they are written to HeatWave.
4. Reinstall `budget-security-headers.conf` and reload Nginx; Phase 2B allows the official Plaid Link CDN and Sandbox/Production Plaid API origins required by Link.
5. Keep Sandbox Items separate from Production; changing `PLAID_ENV` does not migrate an Item.

The frontend receives only the short-lived Link token and one-time public token flow. Long-lived Plaid access tokens stay server-side and encrypted at rest.

## Phase 2C Plaid transaction synchronization

After applying migration `20260813_0004`, install the timer units alongside the
API service:

```bash
sudo install -o root -g root -m 0644 \
  /opt/budget-app/current/deploy/systemd/budget-sync.service \
  /etc/systemd/system/budget-sync.service
sudo install -o root -g root -m 0644 \
  /opt/budget-app/current/deploy/systemd/budget-sync.timer \
  /etc/systemd/system/budget-sync.timer
sudo systemd-analyze verify /etc/systemd/system/budget-sync.service \
  /etc/systemd/system/budget-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now budget-sync.timer
```

The timer runs a one-shot `python -m app.cli sync-plaid` process roughly every
15 minutes and does not add Redis, Celery, or a persistent worker. Verify it with:

```bash
systemctl list-timers budget-sync.timer
sudo systemctl start budget-sync.service
sudo journalctl -u budget-sync.service -n 50 --no-pager
```

The Accounts page also exposes **Sync now** for an authenticated, CSRF-protected
manual refresh. Both paths use the same cursor-based sync service. A first sync
can legitimately return `NOT_READY` with no cursor while Plaid prepares history;
leave the Item active and allow a later timer/manual run to retry it. Plaid Item
credentials remain encrypted at rest and neither the CLI nor journal output logs
access tokens. Do not add `/transactions/refresh` to the periodic timer; it is a
separate optional Plaid refresh operation rather than normal incremental sync.


### Phase 2D webhook deployment

Set `PLAID_WEBHOOK_URI=https://budget.od3ssa.com/api/v1/plaid/webhook` and restart `budget-api`. The next `budget-sync.service` run updates pre-existing Plaid Items with `/item/webhook/update`; newly linked Items receive the webhook URL during Link-token creation. Keep `budget-sync.timer` enabled: it checks every minute, services webhook-marked Items quickly, and falls back to a sync when an Item has been stale for 15 minutes. Webhook requests are unauthenticated at the application-session layer but are rejected unless the `Plaid-Verification` ES256 JWT validates against Plaid's JWK and its body hash matches the exact raw request bytes.

## Phase 3C-1 insight engine deployment

Apply migration `20260813_0008` before restarting `budget-api`. No new daemon, queue, Node
process, external AI service, environment variable, or public listener is required. Insight
refresh runs synchronously through the authenticated API and stores only deterministic,
owner-scoped signal history in MySQL. Build the Vite frontend off-host and replace the live
`frontend/dist` bundle using the normal manual release procedure.


## Phase 3C-2 Ask Budget deployment

Apply migration `20260813_0009` before restarting `budget-api`. Configure the
provider only in `/etc/budget-app/budget.env`; never place the API key in Git,
frontend environment variables, Nginx configuration, URLs, or shell history
that is retained/shared:

```text
AI_ENABLED=true
AI_PROVIDER=gemini
GEMINI_API_KEY=<server-side-key>
GEMINI_MODEL=gemini-3.6-flash
# OpenAI remains supported as an optional fallback:
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6
AI_TIMEOUT_SECONDS=45
AI_MAX_TOOL_CALLS=4
AI_REQUESTS_PER_MINUTE=12
```

Restart `budget-api` after changing the environment, then verify `/api/health`,
`/api/ready`, and the authenticated `/api/v1/advisor/status` route. The VM needs
outbound HTTPS access to the configured provider; no new inbound port, queue,
daemon, Node process, or database listener is required. Nginx proxies the
Advisor's same-origin streaming response through the existing `/api/` route, and
the API sends `X-Accel-Buffering: no` plus `Cache-Control: no-store`.

Build the frontend off-host as usual. Before the production bundle swap, verify
that the uploaded Vite bundle contains `/advisor` and `Ask Budget`. After the
swap, test one quick question, one scenario, the Insights **Ask Budget about
this** handoff, saved history, and private/no-history mode. Provider failures
should surface as generic Advisor errors; logs and audit events must not contain
provider response bodies or secret values.

## Phase 3C-3 Advisor actions deployment

Phase 3C-3 adds migration `20260814_0010`. Pull the release, run `alembic upgrade
head` through the existing `budgetapp` systemd-run migration pattern, and verify
`alembic current` reports `20260814_0010 (head)` before restarting `budget-api`.
No new environment variables, daemon, inbound port, or provider credential is
required beyond the Phase 3C-2 Advisor configuration.

Build and upload the Vite bundle off-host using the normal release procedure. Before
the swap, verify the bundle contains `Apply changes`, `Undo plan`, and `/advisor`.
After deployment, use a non-destructive test plan to verify: a proposal renders a
deterministic before/after preview; nothing changes before approval; Apply updates
only the displayed Budget/Plan settings; Undo restores them; changing a target after
proposal creation causes a stale-plan `409` rather than overwriting the newer value;
and private Advisor mode does not create a proposal.


## Reporting snapshots (Phase 3D)

Install the hourly snapshot worker alongside the existing Plaid sync timer:

```bash
sudo cp /opt/budget-app/current/deploy/systemd/budget-snapshot.service /etc/systemd/system/budget-snapshot.service
sudo cp /opt/budget-app/current/deploy/systemd/budget-snapshot.timer /etc/systemd/system/budget-snapshot.timer
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/budget-snapshot.service /etc/systemd/system/budget-snapshot.timer
sudo systemctl enable --now budget-snapshot.timer
```

The timer wakes hourly. The command upserts the current local calendar day's snapshot for each user, so repeated runs are safe and do not create duplicate daily history.

## Phase 3D report center and exports

The completed Phase 3D release adds migration `20260814_0012` on top of the reporting snapshot schema. Apply migrations before restarting the API and verify the database is at head:

```bash
sudo systemd-run \
  --wait \
  --collect \
  --pipe \
  --unit=budget-phase3d-migrate \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/alembic upgrade head

sudo systemd-run \
  --wait \
  --collect \
  --pipe \
  --unit=budget-phase3d-verify \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/alembic current
```

Expected head is `20260814_0012`. Stage 4 adds no new environment variable, inbound port, daemon, PDF service, or provider credential. Keep the Stage 1 `budget-snapshot.timer` enabled because Goals/Debt trajectory and forecast-accuracy reporting rely on the daily history it maintains.

Build the frontend off-host and use the normal verified `dist` swap. After deployment, smoke-test all four Reports tabs and then: save/reopen a named report; create and download both CSV and PDF exports; download a prior export again from Report Center; and launch **Ask Budget** from Spending, Budget, and Goals & Debt at least once. With Advisor merchant sharing disabled, report-based Advisor questions must not expose top-merchant names. Export responses should be private/no-store and include the stored SHA-256 integrity header.

## Phase 4 Stage 1 identity/security deployment

Phase 4 Stage 1 adds migration `20260814_0013`. It also makes `PyJWT` an explicit runtime requirement for Google ID-token validation, so synchronize the production virtual environment before restarting the API:

```bash
sudo /opt/budget-app/venv/bin/pip install -r /opt/budget-app/current/backend/requirements.txt
```

Then migrate through the existing owner-scoped service environment and verify head:

```bash
sudo systemd-run \
  --wait \
  --collect \
  --pipe \
  --unit=budget-phase4-stage1-migrate \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/alembic upgrade head

sudo systemd-run \
  --wait \
  --collect \
  --pipe \
  --unit=budget-phase4-stage1-verify \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/alembic current
```

Expected head is `20260814_0013`.

Budget remains invite-only. The existing installation owner becomes the first administrator and can create invitations under Settings -> Security -> Family access. SMTP is optional; with email delivery disabled the UI returns a private invitation/reset URL for the administrator to copy to the intended family member.

### Google OpenID Connect

Google login is optional. Create a Google OAuth web client and register the exact callback used by the environment. For local Vite development the callback is:

```text
http://localhost:5173/api/v1/auth/google/callback
```

For the current production site it is:

```text
https://budget.od3ssa.com/api/v1/auth/google/callback
```

Production `/etc/budget-app/budget.env` should use server-side values only:

```text
PUBLIC_APP_URL=https://budget.od3ssa.com
GOOGLE_CLIENT_ID=<google-web-client-id>
GOOGLE_CLIENT_SECRET=<google-web-client-secret>
GOOGLE_REDIRECT_URI=https://budget.od3ssa.com/api/v1/auth/google/callback
```

Do not put the Google client secret in Vite variables or the frontend bundle. The callback travels through the existing same-origin Nginx `/api/` proxy; no new listener or inbound port is required.

Existing password users should connect Google while already authenticated in Settings. Budget deliberately refuses to silently merge a new Google identity into an existing account based on email alone. New Google-first users require a valid invitation and must use the Google account matching the invited email.

### Optional SMTP delivery

For a private family install, SMTP can remain disabled:

```text
EMAIL_DELIVERY=disabled
```

To deliver invitations and reset links by email, configure:

```text
PUBLIC_APP_URL=https://budget.od3ssa.com
EMAIL_DELIVERY=smtp
SMTP_HOST=<smtp-host>
SMTP_PORT=587
SMTP_USERNAME=<smtp-username>
SMTP_PASSWORD=<smtp-password>
SMTP_FROM_EMAIL=<from-address>
SMTP_STARTTLS=true
```

SMTP failures fail back to a manual administrator link rather than blocking account recovery. Password-reset responses exposed to unauthenticated callers remain non-enumerating.

After migration/configuration, restart `budget-api`, verify `/api/health` and `/api/ready`, then build and deploy the Vite bundle through the normal off-host `dist` swap. Smoke-test: local password login, invitation acceptance, session revocation, TOTP plus one recovery code, Google link/login if configured, password reset, and an account-delete confirmation with a disposable invited user.

If the sole administrator is locked out while SMTP is disabled and no Google identity is linked, use the existing interactive server-side recovery command from the protected application host rather than exposing a public recovery bypass:

```bash
sudo systemd-run \
  --pty \
  --wait \
  --collect \
  --unit=budget-owner-password-recovery \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/python -m app.cli reset-password --username <owner-username>
```

The command prompts for the new password without putting it in shell history and revokes the user's active sessions.

## Phase 4 Stage 2 reliability and backups

Phase 4 Stage 2 adds migration `20260814_0014` and an admin-only reliability view. The
migration stores only the most recent status/heartbeat for a few scheduled jobs; it does not
copy financial data into a second application table.

### Backup configuration

Production must use an absolute backup directory. The supplied systemd units are hardened for:

```text
BACKUP_DIR=/var/lib/budget-app/backups
BACKUP_RETENTION_DAILY=7
BACKUP_RETENTION_WEEKLY=4
BACKUP_RETENTION_MONTHLY=12
BACKUP_MAX_AGE_HOURS=36
MYSQLDUMP_PATH=mysqldump
MYSQL_PATH=mysql
```

Archives and manifests are created mode `0600` inside a mode `0700` directory owned by
`budgetapp`. The production logical dump uses the existing TLS-protected MySQL connection
settings and never places the database password in process arguments; a short-lived mode-0600
MySQL option file is created in a private temporary directory instead. Backup files contain
financial data, encrypted Plaid credentials, Advisor history, and identity records, so treat
the backup directory as sensitive data and include it in the VM/storage encryption and access
controls.

The backup format is a gzip-compressed `mysqldump` plus a sidecar JSON manifest containing only
the archive name, schema revision, size, SHA-256 digest, database type, and creation time. The
dump deliberately uses `--single-transaction`, `--quick`, `--skip-lock-tables`, and
`--no-tablespaces` so the application DB account does not need broad server-level privileges.

Before enabling the timers, confirm both MySQL client programs exist:

```bash
command -v mysqldump
command -v mysql
```

Do not enable the timer until both commands resolve. Install the MySQL client package for the
VM's Ubuntu release if either is absent.

### Install the timers

After applying migration `20260814_0014`, copy and verify the four new units:

```bash
sudo cp /opt/budget-app/current/deploy/systemd/budget-db-backup.service /etc/systemd/system/
sudo cp /opt/budget-app/current/deploy/systemd/budget-db-backup.timer /etc/systemd/system/
sudo cp /opt/budget-app/current/deploy/systemd/budget-backup-verify.service /etc/systemd/system/
sudo cp /opt/budget-app/current/deploy/systemd/budget-backup-verify.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify \
  /etc/systemd/system/budget-db-backup.service \
  /etc/systemd/system/budget-db-backup.timer \
  /etc/systemd/system/budget-backup-verify.service \
  /etc/systemd/system/budget-backup-verify.timer
```

Run the first backup and verification manually before enabling schedules:

```bash
sudo systemctl start budget-db-backup.service
sudo systemctl status budget-db-backup.service --no-pager
sudo journalctl -u budget-db-backup.service -n 50 --no-pager

sudo systemctl start budget-backup-verify.service
sudo systemctl status budget-backup-verify.service --no-pager
sudo journalctl -u budget-backup-verify.service -n 50 --no-pager
```

Then enable the daily backup and weekly integrity check:

```bash
sudo systemctl enable --now budget-db-backup.timer budget-backup-verify.timer
sudo systemctl list-timers budget-db-backup.timer budget-backup-verify.timer --all
```

The backup timer runs daily at 08:15 UTC with up to 20 minutes of randomized delay. The verify
timer runs weekly on Sunday at 09:15 UTC with up to 30 minutes of randomized delay. Both are
persistent, so a missed run is recovered after the VM next starts.

### Restore drills

`verify-backup` validates the newest manifest, SHA-256 digest, gzip stream, and MySQL dump
structure. That is an integrity check, not a substitute for a restore drill.

For local SQLite/demo mode, `restore-test-backup` performs a complete restore to a disposable
temporary SQLite database, runs `PRAGMA integrity_check`, and verifies the Alembic revision:

```bash
python -m app.cli backup-db
python -m app.cli verify-backup
python -m app.cli restore-test-backup
```

For production MySQL, create an **empty disposable database** named with the
`budget_restore_` prefix and grant the Budget DB account access to only that disposable target.
Never use the live `DB_NAME`. Then run:

```bash
sudo systemd-run \
  --wait \
  --collect \
  --pipe \
  --unit=budget-restore-drill \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/python -m app.cli restore-test-backup \
  --target-db-name budget_restore_YYYYMMDD
```

The command refuses the configured live `DB_NAME`, refuses target names outside the guarded
`budget_restore_*` namespace, requires an empty target, restores the newest archive, and checks
that its `alembic_version` matches the manifest. It intentionally leaves the disposable target
in place for operator inspection; drop it afterward using the database administration path,
not the Budget application account unless that permission was deliberately granted.

### Operations status and logging

The existing `budget-sync` and `budget-snapshot` CLI commands now update one-row operational
heartbeats, as do backup and verification jobs. Admins can view the safe aggregate status at:

```text
GET /api/v1/operations/status
```

The Settings page renders this as **Reliability & backups -> System health**. It reports schema
revision, latest successful worker times, backup age, archive count/size, and free disk space.
It does not expose database credentials, backup contents, Plaid tokens, provider responses, or
financial records. A failed or stale critical job produces an in-app admin attention state;
email/push notification delivery remains a later notifications-stage concern.

API journal logs remain JSON, but request metadata is now emitted as structured fields
(`request_id`, method, route, status, and duration) so a UI request ID can be correlated directly
with the corresponding journal entry. `/api/ready` additionally rejects a known production
schema revision that does not match the application's Alembic head.

## Phase 4 Stage 3 dashboard experience
Stage 3 adds migration `20260814_0015` for owner-scoped dashboard preferences. It adds no new environment variable, daemon, listener, or external provider. Apply `alembic upgrade head`; expected head is `20260814_0015`.
