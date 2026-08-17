#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/budget-app/current}"
ENV_FILE="${ENV_FILE:-/etc/budget-app/budget.env}"
PYTHON="${PYTHON:-/opt/budget-app/venv/bin/python}"
APP_USER="${APP_USER:-budgetapp}"
APP_GROUP="${APP_GROUP:-budgetapp}"

run_app() {
  local unit="$1"
  shift
  sudo systemd-run --wait --collect --pipe \
    --unit="$unit" \
    --service-type=exec \
    --uid="$APP_USER" \
    --gid="$APP_GROUP" \
    --working-directory="$APP_ROOT/backend" \
    --property="EnvironmentFile=$ENV_FILE" \
    "$@"
}

echo "== Budget Phase 5 production preflight =="

echo "[1/5] Nginx configuration"
sudo nginx -t

echo "[2/5] API health"
curl -fsS http://127.0.0.1:8000/api/health
echo
curl -fsS http://127.0.0.1:8000/api/ready
echo

echo "[3/5] Release readiness"
run_app "budget-phase5-release-readiness-$(date +%s)" \
  "$PYTHON" -m app.cli release-readiness --require-production --strict-operations

echo "[4/5] Required timers"
required_timers=(
  budget-sync.timer
  budget-snapshot.timer
  budget-notifications.timer
  budget-db-backup.timer
  budget-backup-verify.timer
  budget-maintenance.timer
)
for timer in "${required_timers[@]}"; do
  sudo systemctl is-enabled --quiet "$timer"
  sudo systemctl is-active --quiet "$timer"
  printf '  %s: enabled + active\n' "$timer"
done

echo "[5/5] API listener exposure"
listener="$(sudo ss -ltnp '( sport = :8000 )' || true)"
printf '%s\n' "$listener"
if printf '%s\n' "$listener" | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]):8000'; then
  echo "ERROR: Uvicorn port 8000 is exposed beyond loopback." >&2
  exit 1
fi
if ! printf '%s\n' "$listener" | grep -Eq '127\.0\.0\.1:8000'; then
  echo "ERROR: Expected loopback Uvicorn listener was not found." >&2
  exit 1
fi

echo "Phase 5 production preflight passed."
