#!/bin/bash
# ============================================================================
# AutoApply — macOS Setup Script
# Downloads, installs, and configures everything needed to run AutoApply worker
# ============================================================================
set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

REQUIRED_PYTHON="3.11"
REQUIRED_NODE="18"
INSTALL_DIR="$HOME/autoapply"

print_banner() {
  echo ""
  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}${BOLD}║         AutoApply — macOS Setup              ║${NC}"
  echo -e "${CYAN}${BOLD}║   Automated Job Application Engine           ║${NC}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════╝${NC}"
  echo ""
}

log_step() { echo -e "\n${BOLD}[$1/$TOTAL_STEPS]${NC} $2"; }
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
log_fail() { echo -e "  ${RED}✗${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }

TOTAL_STEPS=9

# ── Helpers ──────────────────────────────────────────────────────────────────

version_gte() {
  # Returns 0 if $1 >= $2 (semantic version comparison)
  printf '%s\n%s' "$2" "$1" | sort -V -C
}

check_command() {
  command -v "$1" &>/dev/null
}

install_or_update_brew() {
  if check_command brew; then
    log_ok "Homebrew already installed ($(brew --version | head -1))"
  else
    log_info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add to PATH for Apple Silicon
    if [[ -f /opt/homebrew/bin/brew ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
      echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    fi
    log_ok "Homebrew installed"
  fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

print_banner

echo -e "${BOLD}This script will:${NC}"
echo "  1. Install Homebrew (if missing)"
echo "  2. Install/verify Python $REQUIRED_PYTHON+"
echo "  3. Install/verify Node.js $REQUIRED_NODE+"
echo "  4. Install OpenClaw CLI"
echo "  5. Install Playwright browsers"
echo "  6. Clone AutoApply repository"
echo "  7. Install all dependencies"
echo "  8. Configure environment variables"
echo "  9. Verify the setup"
echo ""
echo -e "${YELLOW}Estimated time: 5-10 minutes${NC}"
echo ""
read -p "Press Enter to continue (or Ctrl+C to cancel)..."

# ── Step 1: Homebrew ─────────────────────────────────────────────────────────
log_step 1 "Checking Homebrew..."
install_or_update_brew

# ── Step 2: Python ───────────────────────────────────────────────────────────
log_step 2 "Checking Python..."

PYTHON_CMD=""
for cmd in python3.12 python3.11 python3; do
  if check_command "$cmd"; then
    PY_VER=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    if version_gte "$PY_VER" "$REQUIRED_PYTHON"; then
      PYTHON_CMD="$cmd"
      break
    fi
  fi
done

if [[ -n "$PYTHON_CMD" ]]; then
  log_ok "Python found: $($PYTHON_CMD --version) ($PYTHON_CMD)"
else
  log_info "Installing Python via Homebrew..."
  brew install python@3.12
  PYTHON_CMD="python3.12"
  log_ok "Python installed: $($PYTHON_CMD --version)"
fi

# Ensure pip is available
if ! "$PYTHON_CMD" -m pip --version &>/dev/null; then
  log_info "Installing pip..."
  "$PYTHON_CMD" -m ensurepip --upgrade
fi
log_ok "pip available: $($PYTHON_CMD -m pip --version | head -1)"

# ── Step 3: Node.js ─────────────────────────────────────────────────────────
log_step 3 "Checking Node.js..."

if check_command node; then
  NODE_VER=$(node --version | grep -oE '[0-9]+' | head -1)
  if [[ "$NODE_VER" -ge "$REQUIRED_NODE" ]]; then
    log_ok "Node.js found: $(node --version)"
  else
    log_warn "Node.js $(node --version) is too old (need v$REQUIRED_NODE+)"
    log_info "Installing Node.js via Homebrew..."
    brew install node
    log_ok "Node.js installed: $(node --version)"
  fi
else
  log_info "Installing Node.js via Homebrew..."
  brew install node
  log_ok "Node.js installed: $(node --version)"
fi

log_ok "npm available: $(npm --version)"

# ── Step 4: OpenClaw CLI ────────────────────────────────────────────────────
log_step 4 "Checking OpenClaw CLI..."

if check_command openclaw; then
  OC_VER=$(openclaw --version 2>&1 || echo "unknown")
  log_ok "OpenClaw already installed ($OC_VER)"
else
  log_info "Installing OpenClaw CLI..."
  npm install -g openclaw
  log_ok "OpenClaw installed: $(openclaw --version 2>&1 || echo 'installed')"
fi

echo ""
echo -e "  ${YELLOW}NOTE: OpenClaw Pro subscription (\$20/mo) is required for browser automation.${NC}"
echo -e "  ${YELLOW}Sign up at: https://openclaw.com/pricing${NC}"

# ── Step 5: Playwright ──────────────────────────────────────────────────────
log_step 5 "Installing Playwright browsers..."

"$PYTHON_CMD" -m pip install --quiet playwright 2>/dev/null
"$PYTHON_CMD" -m playwright install chromium
log_ok "Playwright Chromium installed"

# ── Step 6: Clone repo ──────────────────────────────────────────────────────
log_step 6 "Setting up AutoApply..."

if [[ -d "$INSTALL_DIR" ]]; then
  log_ok "AutoApply directory exists at $INSTALL_DIR"
  cd "$INSTALL_DIR"
  if [[ -d ".git" ]]; then
    log_info "Pulling latest changes..."
    git pull origin main 2>/dev/null || log_warn "Git pull failed — using existing files"
  fi
else
  log_info "Cloning AutoApply..."
  if check_command git; then
    git clone https://github.com/snehitvaddi/AutoApply.git "$INSTALL_DIR" 2>/dev/null || {
      log_warn "Git clone failed (repo may be private). Creating directory..."
      mkdir -p "$INSTALL_DIR"
    }
  else
    log_info "Installing git..."
    brew install git
    git clone https://github.com/snehitvaddi/AutoApply.git "$INSTALL_DIR" 2>/dev/null || {
      log_warn "Git clone failed. Creating directory..."
      mkdir -p "$INSTALL_DIR"
    }
  fi
  cd "$INSTALL_DIR"
fi

# ── Step 7: Install dependencies ────────────────────────────────────────────
log_step 7 "Installing dependencies..."

# Python worker deps
if [[ -f "packages/worker/requirements.txt" ]]; then
  log_info "Installing Python packages..."
  "$PYTHON_CMD" -m pip install --quiet -r packages/worker/requirements.txt
  log_ok "Python packages installed"
else
  log_warn "packages/worker/requirements.txt not found — skipping"
fi

# Node.js web deps
if [[ -f "packages/web/package.json" ]]; then
  log_info "Installing Node.js packages..."
  cd packages/web && npm install --silent 2>/dev/null && cd ../..
  log_ok "Node.js packages installed"
else
  log_warn "packages/web/package.json not found — skipping"
fi

# ── Step 8: Environment configuration ───────────────────────────────────────
log_step 8 "Configuring environment..."

ENV_FILE="$INSTALL_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  log_ok ".env file already exists"
  log_info "To reconfigure, edit: $ENV_FILE"
else
  echo ""
  echo -e "${BOLD}Enter your configuration (press Enter to skip optional fields):${NC}"
  echo ""

  read -p "  Supabase URL (https://xxx.supabase.co): " SUPABASE_URL
  read -p "  Supabase Anon Key: " SUPABASE_ANON
  read -p "  Supabase Service Role Key: " SUPABASE_SERVICE
  read -p "  App URL [https://autoapply-web.vercel.app]: " APP_URL
  APP_URL="${APP_URL:-https://autoapply-web.vercel.app}"
  read -p "  Telegram Bot Token (optional): " TELEGRAM_TOKEN
  read -p "  Worker ID [worker-1]: " WORKER_ID
  WORKER_ID="${WORKER_ID:-worker-1}"

  # Generate encryption key
  ENCRYPTION_KEY=$(openssl rand -hex 32)

  cat > "$ENV_FILE" <<ENVEOF
# AutoApply Environment Configuration
# Generated by setup-mac.sh on $(date)

# Supabase
NEXT_PUBLIC_SUPABASE_URL=$SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=$SUPABASE_ANON
SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE
SUPABASE_URL=$SUPABASE_URL
SUPABASE_SERVICE_KEY=$SUPABASE_SERVICE

# App
NEXT_PUBLIC_APP_URL=$APP_URL
ENCRYPTION_KEY=$ENCRYPTION_KEY

# Worker
WORKER_ID=$WORKER_ID
POLL_INTERVAL=10
APPLY_COOLDOWN=30
RESUME_DIR=/tmp/autoapply/resumes
SCREENSHOT_DIR=/tmp/autoapply/screenshots

# Telegram (optional)
TELEGRAM_BOT_TOKEN=$TELEGRAM_TOKEN

# Stripe (optional — set these if enabling billing)
# STRIPE_SECRET_KEY=
# STRIPE_WEBHOOK_SECRET=
# STRIPE_STARTER_PRICE_ID=
# STRIPE_PRO_PRICE_ID=

# Redis rate limiting (optional)
# UPSTASH_REDIS_REST_URL=
# UPSTASH_REDIS_REST_TOKEN=

# Google OAuth for Gmail (optional — Pro tier)
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
ENVEOF

  log_ok ".env file created at $ENV_FILE"
fi

# Create required directories
mkdir -p /tmp/autoapply/resumes /tmp/autoapply/screenshots
log_ok "Worker directories created"

# ── Step 9: Verify ──────────────────────────────────────────────────────────
log_step 9 "Verifying setup..."

PASS=0
FAIL=0

check_verify() {
  if $1; then
    log_ok "$2"
    ((PASS++))
  else
    log_fail "$2"
    ((FAIL++))
  fi
}

check_verify "check_command $PYTHON_CMD" "Python ($($PYTHON_CMD --version 2>&1))"
check_verify "check_command node" "Node.js ($(node --version 2>&1))"
check_verify "check_command npm" "npm ($(npm --version 2>&1))"
check_verify "check_command openclaw" "OpenClaw CLI"
check_verify "$PYTHON_CMD -c 'import playwright' 2>/dev/null" "Playwright (Python)"
check_verify "$PYTHON_CMD -c 'import supabase' 2>/dev/null" "Supabase client (Python)"
check_verify "$PYTHON_CMD -c 'import httpx' 2>/dev/null" "httpx (Python)"
check_verify "test -f $ENV_FILE" "Environment config (.env)"
check_verify "test -d /tmp/autoapply/resumes" "Worker directories"

echo ""
echo -e "${BOLD}════════════════════════════════════════════════${NC}"
if [[ $FAIL -eq 0 ]]; then
  echo -e "${GREEN}${BOLD}  Setup complete! All $PASS checks passed.${NC}"
else
  echo -e "${YELLOW}${BOLD}  Setup done with $FAIL issue(s). $PASS/$((PASS+FAIL)) checks passed.${NC}"
fi
echo -e "${BOLD}════════════════════════════════════════════════${NC}"

echo ""
echo -e "${BOLD}Next steps:${NC}"
echo ""
echo "  1. Start the worker:"
echo -e "     ${CYAN}cd $INSTALL_DIR/packages/worker${NC}"
echo -e "     ${CYAN}source ../../.env && $PYTHON_CMD worker.py${NC}"
echo ""
echo "  2. Run the job scanner:"
echo -e "     ${CYAN}cd $INSTALL_DIR/packages/worker${NC}"
echo -e "     ${CYAN}source ../../.env && $PYTHON_CMD -m scanner.run${NC}"
echo ""
echo "  3. Start the web app (development):"
echo -e "     ${CYAN}cd $INSTALL_DIR/packages/web${NC}"
echo -e "     ${CYAN}npm run dev${NC}"
echo ""
echo -e "  ${YELLOW}Need help? See docs/CLIENT-ONBOARDING.md${NC}"
echo ""
