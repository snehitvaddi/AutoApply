#!/bin/bash
# ============================================================================
# AutoApply — macOS Auto-Update Script
# Pulls latest code, updates dependencies, and restarts worker if running.
# Runs daily via launchd (installed by setup-mac.sh) or manually.
# ============================================================================

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTALL_DIR="$HOME/autoapply"
LOG_DIR="$INSTALL_DIR/logs"
LOG_FILE="$LOG_DIR/update-$(date +%Y-%m-%d).log"
ENV_FILE="$INSTALL_DIR/.env"
LOCK_FILE="/tmp/autoapply-update.lock"
LAST_UPDATE_FILE="$INSTALL_DIR/.last-update"
UPDATE_INTERVAL_DAYS=5
QUIET_MODE="${1:-}"  # pass --quiet to suppress banner (for cron)

mkdir -p "$LOG_DIR"

# ── Logging ─────────────────────────────────────────────────────────────────

log() { echo -e "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
log_ok()   { log "${GREEN}✓${NC} $1"; }
log_warn() { log "${YELLOW}⚠${NC} $1"; }
log_fail() { log "${RED}✗${NC} $1"; }
log_info() { log "${CYAN}→${NC} $1"; }

# ── Check if update is needed ──────────────────────────────────────────────

needs_update() {
  # Always update if no timestamp file
  if [ ! -f "$LAST_UPDATE_FILE" ]; then
    return 0
  fi

  LAST_TS=$(cat "$LAST_UPDATE_FILE" 2>/dev/null || echo "0")
  NOW_TS=$(date +%s)
  ELAPSED=$(( (NOW_TS - LAST_TS) / 86400 ))

  if [ "$ELAPSED" -ge "$UPDATE_INTERVAL_DAYS" ]; then
    return 0  # needs update
  else
    return 1  # still fresh
  fi
}

# If called with --check, only run if stale (for login triggers)
if [ "$QUIET_MODE" = "--check" ]; then
  if ! needs_update; then
    # Last update was recent, skip silently
    exit 0
  fi
fi

# ── Lock (prevent concurrent updates) ──────────────────────────────────────

if [ -f "$LOCK_FILE" ]; then
  LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if kill -0 "$LOCK_PID" 2>/dev/null; then
    log_warn "Update already running (PID $LOCK_PID). Skipping."
    exit 0
  else
    rm -f "$LOCK_FILE"
  fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# ── Visual Banner ──────────────────────────────────────────────────────────

if [ "$QUIET_MODE" != "--quiet" ]; then
  echo ""
  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}${BOLD}║        AutoApply — Checking for updates...       ║${NC}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════╝${NC}"

  if [ -f "$LAST_UPDATE_FILE" ]; then
    LAST_TS=$(cat "$LAST_UPDATE_FILE" 2>/dev/null || echo "0")
    NOW_TS=$(date +%s)
    DAYS_AGO=$(( (NOW_TS - LAST_TS) / 86400 ))
    if [ "$DAYS_AGO" -gt 0 ]; then
      echo -e "  ${YELLOW}Last updated: ${DAYS_AGO} day(s) ago${NC}"
    else
      echo -e "  ${GREEN}Last updated: today${NC}"
    fi
  else
    echo -e "  ${YELLOW}First update check${NC}"
  fi
  echo ""
fi

# ── Start ───────────────────────────────────────────────────────────────────

log ""
log "═══════════════════════════════════════════════════"
log "${BOLD}AutoApply Auto-Update — $(date '+%Y-%m-%d %H:%M:%S')${NC}"
log "═══════════════════════════════════════════════════"

if [ ! -d "$INSTALL_DIR" ]; then
  log_fail "AutoApply not found at $INSTALL_DIR. Run setup first."
  exit 1
fi

cd "$INSTALL_DIR" || exit 1

# ── Step 1: Pull latest code ────────────────────────────────────────────────

log_info "Checking for updates..."

if [ -d ".git" ]; then
  # Stash any local changes (user's .env modifications etc)
  LOCAL_CHANGES=$(git status --porcelain 2>/dev/null | grep -v "^??" | wc -l | tr -d ' ')
  if [ "$LOCAL_CHANGES" -gt 0 ]; then
    log_info "Stashing $LOCAL_CHANGES local change(s)..."
    git stash --quiet 2>/dev/null
    STASHED=true
  fi

  # Fetch and check if there are updates
  git fetch origin main --quiet 2>/dev/null

  LOCAL_HASH=$(git rev-parse HEAD 2>/dev/null)
  REMOTE_HASH=$(git rev-parse origin/main 2>/dev/null)

  if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    log_ok "Already up to date (${LOCAL_HASH:0:7})"
    UPDATES_PULLED=false
  else
    BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null)
    log_info "Pulling $BEHIND new commit(s)..."
    git pull origin main --quiet 2>/dev/null
    if [ $? -eq 0 ]; then
      NEW_HASH=$(git rev-parse HEAD 2>/dev/null)
      log_ok "Updated: ${LOCAL_HASH:0:7} → ${NEW_HASH:0:7}"
      UPDATES_PULLED=true

      # Show what changed
      log_info "Changes:"
      git log --oneline "${LOCAL_HASH}..HEAD" 2>/dev/null | while read -r line; do
        log "    $line"
      done
    else
      log_fail "Git pull failed"
      UPDATES_PULLED=false
    fi
  fi

  # Restore local changes
  if [ "$STASHED" = true ]; then
    git stash pop --quiet 2>/dev/null
    log_info "Restored local changes"
  fi
else
  log_warn "Not a git repo — skipping code update"
  UPDATES_PULLED=false
fi

# ── Step 2: Update dependencies (only if code changed) ──────────────────────

if [ "$UPDATES_PULLED" = true ]; then
  # Detect Python
  PYTHON_CMD=""
  for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
      PYTHON_CMD="$cmd"
      break
    fi
  done

  # Python dependencies
  if [ -n "$PYTHON_CMD" ] && [ -f "packages/worker/requirements.txt" ]; then
    log_info "Updating Python packages..."
    "$PYTHON_CMD" -m pip install --quiet --upgrade -r packages/worker/requirements.txt 2>/dev/null
    log_ok "Python packages updated"
  fi

  # Check if LLM SDK needs update
  if [ -f "$ENV_FILE" ]; then
    LLM_PROV=$(grep "^LLM_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
    LLM_BACK=$(grep "^LLM_BACKEND_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)

    if [ "$LLM_PROV" = "anthropic" ] || [ "$LLM_BACK" = "anthropic" ]; then
      "$PYTHON_CMD" -m pip install --quiet --upgrade anthropic 2>/dev/null
    fi
    if [ "$LLM_PROV" = "openai" ] || [ "$LLM_BACK" = "openai" ]; then
      "$PYTHON_CMD" -m pip install --quiet --upgrade openai 2>/dev/null
    fi
  fi

  # Node.js dependencies
  if [ -f "packages/web/package.json" ] && command -v npm &>/dev/null; then
    log_info "Updating Node.js packages..."
    (cd packages/web && npm install --silent 2>/dev/null)
    log_ok "Node.js packages updated"
  fi

  # OpenClaw CLI
  if command -v npm &>/dev/null; then
    log_info "Updating OpenClaw CLI..."
    npm update -g openclaw 2>/dev/null
    log_ok "OpenClaw CLI updated"
  fi
else
  log_info "No code changes — skipping dependency updates"
fi

# ── Step 3: Restart worker if running ───────────────────────────────────────

WORKER_PID=$(pgrep -f "python.*worker\.py" 2>/dev/null | head -1)

if [ -n "$WORKER_PID" ] && [ "$UPDATES_PULLED" = true ]; then
  log_info "Restarting worker (PID $WORKER_PID)..."
  kill "$WORKER_PID" 2>/dev/null
  sleep 2

  # Restart worker in background
  if [ -n "$PYTHON_CMD" ] && [ -f "packages/worker/worker.py" ]; then
    cd packages/worker
    if [ -f "$ENV_FILE" ]; then
      set -a; source "$ENV_FILE" 2>/dev/null; set +a
    fi
    nohup "$PYTHON_CMD" worker.py >> "$LOG_DIR/worker.log" 2>&1 &
    NEW_PID=$!
    cd "$INSTALL_DIR"
    log_ok "Worker restarted (PID $NEW_PID)"
  fi
elif [ -n "$WORKER_PID" ]; then
  log_ok "Worker running (PID $WORKER_PID) — no restart needed"
else
  log_info "Worker not running — skipping restart"
fi

# ── Step 4: Health check ────────────────────────────────────────────────────

log_info "Running health check..."

HEALTH_PASS=0
HEALTH_FAIL=0

check_health() {
  if $1 2>/dev/null; then
    log_ok "$2"
    ((HEALTH_PASS++))
  else
    log_fail "$2"
    ((HEALTH_FAIL++))
  fi
}

check_health "test -f $ENV_FILE" ".env exists"
check_health "test -d packages/worker" "Worker code present"

if [ -n "$PYTHON_CMD" ]; then
  check_health "$PYTHON_CMD -c 'import playwright' 2>/dev/null" "Playwright installed"
  check_health "$PYTHON_CMD -c 'import supabase' 2>/dev/null" "Supabase SDK installed"
fi

check_health "command -v openclaw &>/dev/null" "OpenClaw CLI available"

# Check Supabase connectivity
if [ -f "$ENV_FILE" ]; then
  SB_URL=$(grep "^NEXT_PUBLIC_SUPABASE_URL=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
  if [ -n "$SB_URL" ]; then
    check_health "curl -sf '${SB_URL}/rest/v1/' -o /dev/null --max-time 5" "Supabase API reachable"
  fi
fi

# ── Summary ─────────────────────────────────────────────────────────────────

log ""
log "═══════════════════════════════════════════════════"
if [ "$UPDATES_PULLED" = true ]; then
  log "${GREEN}${BOLD}Update complete.${NC} Health: $HEALTH_PASS passed, $HEALTH_FAIL failed."
else
  log "${GREEN}${BOLD}No updates available.${NC} Health: $HEALTH_PASS passed, $HEALTH_FAIL failed."
fi
log "═══════════════════════════════════════════════════"
log "Log saved to: $LOG_FILE"

# Save last-update timestamp
date +%s > "$LAST_UPDATE_FILE"

# Show completion banner
if [ "$QUIET_MODE" != "--quiet" ]; then
  echo ""
  if [ "$UPDATES_PULLED" = true ]; then
    echo -e "${GREEN}${BOLD}  ✓ AutoApply updated successfully!${NC}"
  else
    echo -e "${GREEN}${BOLD}  ✓ AutoApply is up to date.${NC}"
  fi
  echo -e "  ${CYAN}Next check: in $UPDATE_INTERVAL_DAYS days or on next login${NC}"
  echo ""
fi

# Cleanup old logs (keep 30 days)
find "$LOG_DIR" -name "update-*.log" -mtime +30 -delete 2>/dev/null
