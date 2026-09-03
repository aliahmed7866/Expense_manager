#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
APP_DIR="${EXPENSE_APP_DIR:-$HOME/Expense_manager}"
SERVICE_DIR="$PREFIX/var/service/expense-manager-deploy"
mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_DIR/run" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
exec 2>&1
cd "$APP_DIR"
exec bash "$APP_DIR/termux/auto-deploy.sh"
EOF
chmod +x "$SERVICE_DIR/run"
sv-enable expense-manager-deploy >/dev/null 2>&1 || true
sv restart expense-manager-deploy >/dev/null 2>&1 || sv up expense-manager-deploy >/dev/null 2>&1 || true
echo "[Expense Manager] Auto-deploy enabled."
