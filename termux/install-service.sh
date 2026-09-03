#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

APP_DIR="${EXPENSE_APP_DIR:-$HOME/Expense_manager}"
PORT="${EXPENSE_PORT:-8082}"
CONFIG_DIR="${EXPENSE_CONFIG_DIR:-$HOME/.config/expense-manager}"
ENV_FILE="${EXPENSE_ENV_FILE:-$CONFIG_DIR/env}"
VENV_DIR="$APP_DIR/.venv"
SERVICE_DIR="$PREFIX/var/service/expense-manager"
AYCF_REGISTRY="${AYCF_ADMIN_REGISTRY:-$HOME/.config/aycf/apps.json}"

cd "$APP_DIR"
command -v sv >/dev/null 2>&1 || pkg install -y termux-services
[ -d "$VENV_DIR" ] || python -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install -q -r requirements.txt

mkdir -p "$CONFIG_DIR" "$SERVICE_DIR" "$(dirname "$AYCF_REGISTRY")"
chmod 700 "$CONFIG_DIR"
if [ ! -f "$ENV_FILE" ]; then
  SECRET="$($VENV_DIR/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  printf "export EXPENSE_SECRET_KEY='%s'\nexport EXPENSE_BIND_HOST='127.0.0.1'\nexport EXPENSE_PORT='%s'\n" "$SECRET" "$PORT" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

cat > "$SERVICE_DIR/run" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
exec 2>&1
cd "$APP_DIR"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
exec "$VENV_DIR/bin/python" termux/run-web.py
EOF
chmod +x "$SERVICE_DIR/run"

"$VENV_DIR/bin/python" "$APP_DIR/termux/register-admin.py" "$AYCF_REGISTRY" "$PORT"
sv-enable expense-manager >/dev/null 2>&1 || true
sv restart expense-manager >/dev/null 2>&1 || sv up expense-manager >/dev/null 2>&1 || true

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "[Expense Manager] Ready: http://127.0.0.1:$PORT"
    sv restart aycf-admin >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 2
done
echo "[Expense Manager] Health check failed."
sv status expense-manager || true
exit 1
