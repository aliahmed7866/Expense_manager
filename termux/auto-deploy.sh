#!/data/data/com.termux/files/usr/bin/bash
set -u

APP_DIR="${EXPENSE_APP_DIR:-$HOME/Expense_manager}"
BRANCH="${EXPENSE_BRANCH:-main}"
INTERVAL="${EXPENSE_DEPLOY_INTERVAL:-60}"
STATE_DIR="${EXPENSE_STATE_DIR:-$HOME/.local/state/expense-manager}"
mkdir -p "$STATE_DIR"

while true; do
  cd "$APP_DIR" || exit 1
  if [ -z "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    remote_sha="$(git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | awk 'NR==1{print $1}')"
    local_sha="$(git rev-parse HEAD 2>/dev/null || true)"
    deployed_sha="$(cat "$STATE_DIR/last_successful_sha" 2>/dev/null || true)"
    if [ -n "$remote_sha" ] && { [ "$remote_sha" != "$local_sha" ] || [ "$remote_sha" != "$deployed_sha" ]; }; then
      git fetch --quiet origin "$BRANCH" && git checkout --quiet "$BRANCH" && git merge --ff-only --quiet "origin/$BRANCH" && \
        bash "$APP_DIR/termux/install-service.sh" && printf '%s\n' "$remote_sha" > "$STATE_DIR/last_successful_sha"
    fi
  fi
  sleep "$INTERVAL"
done
