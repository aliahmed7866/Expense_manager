#!/data/data/com.termux/files/usr/bin/bash
set -u

APP_DIR="${EXPENSE_APP_DIR:-$HOME/Expense_manager}"
BRANCH="${EXPENSE_BRANCH:-main}"
INTERVAL="${EXPENSE_DEPLOY_INTERVAL:-60}"
REPOSITORY="${EXPENSE_REPOSITORY_URL:-https://github.com/aliahmed7866/Expense_manager.git}"
STATE_DIR="${EXPENSE_STATE_DIR:-$HOME/.local/state/expense-manager}"
STATUS_FILE="$STATE_DIR/deploy-status.txt"
LOG_FILE="$STATE_DIR/deploy.log"
LAST_SUCCESSFUL_FILE="$STATE_DIR/last_successful_sha"
DEPLOYED_UPDATE=0
mkdir -p "$STATE_DIR"

timestamp() {
  date '+%Y-%m-%dT%H:%M:%S%z'
}

log_message() {
  printf '%s %s\n' "$(timestamp)" "$1" >> "$LOG_FILE"
}

write_status() {
  status_state="$1"
  status_message="$2"
  status_sha="${3:-}"
  status_tmp="$STATUS_FILE.tmp"
  {
    printf 'state=%s\n' "$status_state"
    printf 'message=%s\n' "$status_message"
    printf 'sha=%s\n' "$status_sha"
    printf 'updated_at=%s\n' "$(timestamp)"
  } > "$status_tmp"
  mv "$status_tmp" "$STATUS_FILE"
}

public_git() {
  GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.interactive=never "$@"
}

deploy_once() {
  if [ ! -d "$APP_DIR/.git" ]; then
    write_status "error" "Pocketwise checkout is missing: $APP_DIR"
    log_message "ERROR checkout missing: $APP_DIR"
    return 1
  fi
  cd "$APP_DIR" || return 1

  if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    write_status "blocked" "Tracked local changes are preventing an automatic update."
    log_message "BLOCKED tracked local changes prevent deployment"
    return 1
  fi

  write_status "checking" "Checking GitHub for a Pocketwise update."
  remote_sha="$(public_git ls-remote "$REPOSITORY" "refs/heads/$BRANCH" 2>>"$LOG_FILE" | awk 'NR==1{print $1}')"
  if [ -z "$remote_sha" ]; then
    write_status "error" "Could not read $BRANCH from GitHub. See deploy.log."
    log_message "ERROR unable to resolve remote branch $BRANCH"
    return 1
  fi

  local_sha="$(git rev-parse HEAD 2>/dev/null || true)"
  deployed_sha="$(cat "$LAST_SUCCESSFUL_FILE" 2>/dev/null || true)"
  if [ "$remote_sha" = "$local_sha" ] && [ "$remote_sha" = "$deployed_sha" ]; then
    write_status "current" "Pocketwise is up to date." "$remote_sha"
    return 0
  fi

  write_status "updating" "Installing Pocketwise $remote_sha." "$remote_sha"
  log_message "UPDATE local=${local_sha:-missing} remote=$remote_sha"
  if ! public_git fetch --quiet "$REPOSITORY" "$BRANCH" 2>>"$LOG_FILE"; then
    write_status "error" "GitHub fetch failed. See deploy.log." "$remote_sha"
    log_message "ERROR fetch failed"
    return 1
  fi
  fetched_sha="$(git rev-parse FETCH_HEAD 2>/dev/null || true)"
  if [ "$fetched_sha" != "$remote_sha" ]; then
    write_status "error" "Fetched commit did not match the remote branch." "$remote_sha"
    log_message "ERROR fetched SHA mismatch: ${fetched_sha:-missing}"
    return 1
  fi
  if [ "$(git branch --show-current 2>/dev/null)" != "$BRANCH" ]; then
    if ! git checkout --quiet "$BRANCH" 2>>"$LOG_FILE"; then
      write_status "blocked" "Could not switch the checkout to $BRANCH." "$remote_sha"
      log_message "BLOCKED checkout of $BRANCH failed"
      return 1
    fi
  fi
  if ! git merge --ff-only --quiet "$fetched_sha" 2>>"$LOG_FILE"; then
    write_status "blocked" "The local branch cannot fast-forward. See deploy.log." "$remote_sha"
    log_message "BLOCKED fast-forward failed"
    return 1
  fi
  if ! bash "$APP_DIR/termux/install-service.sh" >>"$LOG_FILE" 2>&1; then
    write_status "error" "Files updated, but the Pocketwise service failed to restart." "$remote_sha"
    log_message "ERROR service install or health check failed"
    return 1
  fi

  printf '%s\n' "$remote_sha" > "$LAST_SUCCESSFUL_FILE"
  write_status "deployed" "Pocketwise updated and restarted successfully." "$remote_sha"
  log_message "SUCCESS deployed $remote_sha"
  DEPLOYED_UPDATE=1
}

if [ "${1:-}" = "--once" ]; then
  deploy_once
  exit $?
fi

while true; do
  DEPLOYED_UPDATE=0
  deploy_once || true
  if [ "$DEPLOYED_UPDATE" = "1" ]; then
    exec bash "$APP_DIR/termux/auto-deploy.sh"
  fi
  sleep "$INTERVAL"
done
