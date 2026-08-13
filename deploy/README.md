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
ENCRYPTION_KEY=<existing-key-reserved-for-phase-2>
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
active sessions. `ENCRYPTION_KEY` is loaded and redacted but reserved for Phase
2 Plaid-token encryption. Secret values must never appear in logs or API output.

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
