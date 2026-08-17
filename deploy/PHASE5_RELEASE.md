# Phase 5 production release and rollback

Phase 5 is developed on the `phase5` branch and must not be deployed incrementally. Production remains on the Phase 4 baseline until the Phase 5 release candidate has passed the local and server-side gates below.

## Release gates before merging

On Windows from `E:\budget-app`:

```powershell
cd E:\budget-app\backend
.\.venv\Scripts\python.exe -m pytest -q --no-cov
.\.venv\Scripts\python.exe -m app.cli demo-reset
.\.venv\Scripts\python.exe -m app.cli release-readiness

cd E:\budget-app\frontend
npm run typecheck
npm test -- --run
Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
npm run build

cd E:\budget-app
git diff --check
git status
```

The local release rehearsal may report warnings for production-only paths, Plaid credentials, and scheduled workers. It must report zero hard failures.

## Merge the release candidate

Only after Phase 5F is committed and pushed:

```powershell
cd E:\budget-app
git switch main
git pull
git merge --no-ff phase5
git push
git log -3 --oneline
```

Record both the pre-merge `main` commit and the resulting merge commit before touching production.

## Production backup before code cutover

On the E2 VM, first create and verify a fresh backup while the known-good Phase 4 application is still running:

```bash
sudo systemctl start budget-db-backup.service
sudo systemctl status budget-db-backup.service --no-pager
sudo systemctl start budget-backup-verify.service
sudo systemctl status budget-backup-verify.service --no-pager
ls -lah /var/lib/budget-app/backups
```

Do not continue if backup creation or verification fails.

## Pull code and migrate

```bash
sudo -iu budgetapp
cd /opt/budget-app/current
git pull
git log -3 --oneline
exit
```

Run Alembic under the production environment file rather than exporting secrets into the shell:

```bash
sudo systemd-run --wait --collect --pipe \
  --unit=budget-phase5-migrate-$(date +%s) \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/alembic upgrade head
```

Verify the migration head:

```bash
sudo systemd-run --wait --collect --pipe \
  --unit=budget-phase5-schema-$(date +%s) \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/alembic current
```

## Restart API and run preflight

```bash
sudo systemctl restart budget-api
sudo systemctl status budget-api --no-pager
curl -fsS http://127.0.0.1:8000/api/health && echo
curl -fsS http://127.0.0.1:8000/api/ready && echo
sudo /opt/budget-app/current/deploy/scripts/phase5-production-preflight.sh
```

The preflight intentionally checks the secret-free release readiness command, Nginx, loopback-only Uvicorn binding, schema head, security posture, Plaid Production readiness, worker history, and required timers.

## Frontend deployment

Build on Windows using Node 24:

```powershell
cd E:\budget-app\frontend
npm ci
npm run typecheck
npm test -- --run
Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
npm run build

pscp -i "E:\EXC.ppk" -r .\dist\* ubuntu@159.54.164.35:/tmp/budget-frontend-phase5/
```

Before `rsync --delete`, verify that the upload directory is populated:

```bash
find /tmp/budget-frontend-phase5 -maxdepth 2 -type f -print | head -30
```

Preserve the currently served frontend for rollback, then swap the new assets:

```bash
sudo rm -rf /opt/budget-app/frontend-rollback
sudo cp -a /opt/budget-app/current/frontend/dist /opt/budget-app/frontend-rollback
sudo rsync -a --delete /tmp/budget-frontend-phase5/ /opt/budget-app/current/frontend/dist/
sudo chown -R budgetapp:budgetapp /opt/budget-app/current/frontend/dist
sudo chmod -R o+rX /opt/budget-app/current/frontend/dist
```

Hard-refresh the browser and smoke-test Dashboard, Accounts, Transactions, Budget, Plan, Calendar, Insights, Advisor, Reports, Trends, Settings, Plaid sync, Sankey drill-through, Trends drill-through, Calendar activity, and Ask Budget handoffs.

## Rollback

Rollback must keep application code and Alembic schema in agreement. Phase 4 code expects schema `20260815_0020`; do not simply reset Git while leaving the database at the Phase 5 head.

1. Stop user-facing writes if a rollback is required during active use.
2. Create another emergency backup of the current database if possible.
3. Restore the previous frontend from `/opt/budget-app/frontend-rollback`.
4. Reset `/opt/budget-app/current` to the recorded pre-merge Phase 4 commit.
5. Downgrade the database to the Phase 4 schema:

```bash
sudo systemd-run --wait --collect --pipe \
  --unit=budget-phase5-rollback-schema-$(date +%s) \
  --service-type=exec \
  --uid=budgetapp \
  --gid=budgetapp \
  --working-directory=/opt/budget-app/current/backend \
  --property=EnvironmentFile=/etc/budget-app/budget.env \
  /opt/budget-app/venv/bin/alembic downgrade 20260815_0020
```

The Phase 5D migration is additive; downgrading to `0020` drops the Phase 5 account-balance history table. It does not intentionally delete the pre-existing Phase 4 users, accounts, transactions, budgets, Plaid items, or planning data. The fresh pre-release backup remains the authoritative recovery point.

6. Restart `budget-api`, verify `/api/health` and `/api/ready`, restore the frontend rollback directory into `current/frontend/dist`, and smoke-test the Phase 4 application.

Never restore a database backup over the live database merely to fix a frontend-only problem.
