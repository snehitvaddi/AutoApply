#!/bin/bash
# ============================================================================
# ApplyLoop — macOS Setup Script
# Downloads, installs, and configures everything needed to run ApplyLoop worker
# ============================================================================
set -e

# Parse flags
ADVANCED_MODE=false
for arg in "$@"; do
  case "$arg" in
    --advanced) ADVANCED_MODE=true ;;
  esac
done

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
  echo -e "${CYAN}${BOLD}║         ApplyLoop — macOS Setup               ║${NC}"
  echo -e "${CYAN}${BOLD}║   Automated Job Application Engine           ║${NC}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════╝${NC}"
  echo ""
}

log_step() { echo -e "\n${BOLD}[$1/$TOTAL_STEPS]${NC} $2"; }
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
log_fail() { echo -e "  ${RED}✗${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }

TOTAL_STEPS=11

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
echo "  6. Clone ApplyLoop repository"
echo "  7. Install all dependencies"
echo "  8. Configure LLM provider + install CLI (Claude Code / Codex)"
echo "  9. Generate setup status + AGENTS.md"
echo "  10. Launch LLM CLI for remaining setup (or manual steps)"
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

# OpenClaw onboarding + gateway setup
if check_command openclaw; then
  OC_CONFIG="$HOME/.openclaw/openclaw.json"
  if [[ ! -f "$OC_CONFIG" ]]; then
    log_info "Setting up OpenClaw (browser will open for authentication)..."
    openclaw onboard 2>/dev/null || log_warn "OpenClaw onboard failed. After setup, run: openclaw onboard"
  else
    log_ok "OpenClaw already configured"
  fi

  # Start the gateway (browser automation service)
  log_info "Starting OpenClaw gateway..."
  openclaw gateway start 2>/dev/null && log_ok "OpenClaw gateway started" || log_warn "Gateway start failed. Run: openclaw gateway start"
fi


# ── Step 5: Playwright ──────────────────────────────────────────────────────
log_step 5 "Installing Playwright browsers..."

"$PYTHON_CMD" -m pip install --quiet playwright 2>/dev/null
"$PYTHON_CMD" -m playwright install chromium
log_ok "Playwright Chromium installed"

# ── Step 5b: Optional tools (Himalaya, AgentMail) ─────────────────────────
log_step 5 "Installing optional tools (Himalaya, AgentMail)..."

echo ""
echo -e "  ${CYAN}Himalaya CLI lets the worker read Gmail (OTP codes, confirmations).${NC}"
echo -e "  ${CYAN}AgentMail provides disposable email inboxes for applications.${NC}"
echo ""

# Himalaya CLI (Gmail reading)
if check_command himalaya; then
  log_ok "Himalaya CLI already installed ($(himalaya --version 2>&1 | head -1))"
else
  read -p "  Install Himalaya CLI for Gmail reading? [Y/n]: " INSTALL_HIM
  INSTALL_HIM="${INSTALL_HIM:-Y}"
  if [[ "$INSTALL_HIM" =~ ^[Yy] ]]; then
    log_info "Installing Himalaya via Homebrew..."
    brew install himalaya 2>/dev/null || log_warn "Himalaya install failed — install later: brew install himalaya"
    if check_command himalaya; then
      log_ok "Himalaya installed: $(himalaya --version 2>&1 | head -1)"
    fi
  else
    log_info "Skipping Himalaya — install later: brew install himalaya"
  fi
fi

# AgentMail (disposable inboxes)
if "$PYTHON_CMD" -c "import agentmail" 2>/dev/null; then
  log_ok "AgentMail SDK already installed"
else
  read -p "  Install AgentMail SDK for disposable inboxes? [Y/n]: " INSTALL_AM
  INSTALL_AM="${INSTALL_AM:-Y}"
  if [[ "$INSTALL_AM" =~ ^[Yy] ]]; then
    log_info "Installing AgentMail..."
    "$PYTHON_CMD" -m pip install --quiet agentmail 2>/dev/null || log_warn "AgentMail install failed — install later: pip install agentmail"
    log_ok "AgentMail SDK installed"
  else
    log_info "Skipping AgentMail — install later: pip install agentmail"
  fi
fi

echo ""
echo -e "  ${CYAN}Multi-resume support:${NC} You can upload multiple PDFs with role tags"
echo -e "  ${CYAN}(e.g., 'GenAI Resume.pdf', 'DS Resume.pdf') and the worker will${NC}"
echo -e "  ${CYAN}pick the best match for each job automatically.${NC}"
echo ""

# ── Step 6: Clone repo ──────────────────────────────────────────────────────
log_step 6 "Setting up ApplyLoop..."

if [[ -d "$INSTALL_DIR" ]]; then
  log_ok "ApplyLoop directory exists at $INSTALL_DIR"
  cd "$INSTALL_DIR"
  if [[ -d ".git" ]]; then
    log_info "Pulling latest changes..."
    git pull origin main 2>/dev/null || log_warn "Git pull failed — using existing files"
  fi
else
  log_info "Cloning ApplyLoop..."
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
  log_info "Installing Python packages from requirements.txt..."
  "$PYTHON_CMD" -m pip install --quiet -r packages/worker/requirements.txt
  log_ok "Python packages installed"
else
  log_info "Installing core Python packages directly..."
  "$PYTHON_CMD" -m pip install --quiet supabase httpx playwright cryptography google-auth google-auth-oauthlib google-api-python-client
  log_ok "Core Python packages installed"
fi

# Node.js web deps
if [[ -f "packages/web/package.json" ]]; then
  log_info "Installing Node.js packages..."
  cd packages/web && npm install --silent 2>/dev/null && cd ../..
  log_ok "Node.js packages installed"
else
  log_warn "packages/web/package.json not found — skipping"
fi

# ── Step 8: LLM Provider + CLI Installation ────────────────────────────────
log_step 8 "Configuring LLM provider + installing CLI..."

LLM_PROVIDER="none"; LLM_MODEL=""; LLM_ACCESS_TYPE="none"; LLM_API_KEY_NAME=""; LLM_API_KEY=""
LLM_CLI_TOOL=""

if [[ "$ADVANCED_MODE" == "true" ]]; then
  # ── Advanced mode: full provider selection (--advanced flag) ──
  echo ""
  echo -e "  ${CYAN}One LLM powers everything (chat + OpenClaw backend).${NC}"
  echo -e "  ${CYAN}Pick your provider and access type — that's it.${NC}"
  echo ""
  echo "    1. Claude (Anthropic)     2. GPT (OpenAI)"
  echo "    3. Gemini (Google)        4. Local/Ollama"
  echo "    5. None (skip for now)"
  echo ""
  read -p "  Provider [1-5] (default: 1): " LLM_CHOICE
  LLM_CHOICE="${LLM_CHOICE:-1}"

  case "$LLM_CHOICE" in
    1)
      LLM_PROVIDER="anthropic"
      echo ""
      echo "    1. Subscription (Pro \$20, Max \$100-200/mo)    2. API (pay-per-token)"
      read -p "  Access type [1-2] (default: 2): " AC; AC="${AC:-2}"
      if [[ "$AC" == "1" ]]; then
        LLM_ACCESS_TYPE="subscription"
        echo "    1. Pro (\$20)  2. Max 5x (\$100)  3. Max 20x (\$200)"
        read -p "  Tier [1-3] (default: 1): " ST
        case "$ST" in 2) LLM_MODEL="claude-max-5x" ;; 3) LLM_MODEL="claude-max-20x" ;; *) LLM_MODEL="claude-pro" ;; esac

        log_info "Installing Claude Code CLI..."
        npm install -g @anthropic-ai/claude-code 2>/dev/null || log_warn "Claude Code CLI install failed"
        if check_command claude; then
          log_ok "Claude Code CLI installed"
          log_info "Launching Claude login (browser OAuth)..."
          claude login 2>/dev/null || log_warn "Claude login skipped — run 'claude login' later"
          LLM_CLI_TOOL="claude"
        fi
      else
        LLM_ACCESS_TYPE="api"
        echo "    1. Sonnet 4.6 (recommended)  2. Opus 4.6  3. Haiku 4.5"
        read -p "  Model [1-3] (default: 1): " CM; CM="${CM:-1}"
        case "$CM" in 2) LLM_MODEL="claude-opus-4-6" ;; 3) LLM_MODEL="claude-haiku-4-5-20251001" ;; *) LLM_MODEL="claude-sonnet-4-6" ;; esac
        LLM_API_KEY_NAME="ANTHROPIC_API_KEY"
        read -p "  API Key (console.anthropic.com): " LLM_API_KEY

        log_info "Installing Claude Code CLI..."
        npm install -g @anthropic-ai/claude-code 2>/dev/null || log_warn "Claude Code CLI install failed"
        if check_command claude; then
          log_ok "Claude Code CLI installed"
          if [[ -n "$LLM_API_KEY" ]]; then
            export ANTHROPIC_API_KEY="$LLM_API_KEY"
            log_ok "ANTHROPIC_API_KEY set for Claude Code CLI"
          fi
          LLM_CLI_TOOL="claude"
        fi
      fi
      ;;
    2)
      LLM_PROVIDER="openai"
      echo ""
      echo "    1. Subscription (Plus \$20, Pro \$200/mo)    2. API (pay-per-token)"
      read -p "  Access type [1-2] (default: 2): " AC; AC="${AC:-2}"
      if [[ "$AC" == "1" ]]; then
        LLM_ACCESS_TYPE="subscription"
        echo "    1. Plus (\$20)  2. Pro (\$200)  3. Business (\$30/user)"
        read -p "  Tier [1-3] (default: 1): " ST
        case "$ST" in 2) LLM_MODEL="chatgpt-pro" ;; 3) LLM_MODEL="chatgpt-business" ;; *) LLM_MODEL="chatgpt-plus" ;; esac

        log_info "Installing OpenAI Codex CLI..."
        npm install -g @openai/codex 2>/dev/null || log_warn "Codex CLI install failed"
        if check_command codex; then
          log_ok "Codex CLI installed"
          log_info "Launching Codex login (browser OAuth)..."
          codex login 2>/dev/null || log_warn "Codex login skipped — run 'codex login' later"
          LLM_CLI_TOOL="codex"
        fi
      else
        LLM_ACCESS_TYPE="api"
        echo "    1. GPT-4.1 (recommended)  2. GPT-4.1-mini  3. GPT-4.1-nano  4. o3"
        read -p "  Model [1-4] (default: 1): " OM; OM="${OM:-1}"
        case "$OM" in 2) LLM_MODEL="gpt-4.1-mini" ;; 3) LLM_MODEL="gpt-4.1-nano" ;; 4) LLM_MODEL="o3" ;; *) LLM_MODEL="gpt-4.1" ;; esac
        LLM_API_KEY_NAME="OPENAI_API_KEY"
        read -p "  API Key (platform.openai.com): " LLM_API_KEY

        log_info "Installing OpenAI Codex CLI..."
        npm install -g @openai/codex 2>/dev/null || log_warn "Codex CLI install failed"
        if check_command codex; then
          log_ok "Codex CLI installed"
          if [[ -n "$LLM_API_KEY" ]]; then
            echo "$LLM_API_KEY" | codex login --with-api-key 2>/dev/null || log_warn "Codex API key login failed — run 'codex login' later"
            log_ok "Codex authenticated with API key"
          fi
          LLM_CLI_TOOL="codex"
        fi
      fi
      ;;
    3)
      LLM_PROVIDER="google"
      LLM_MODEL="gemini-2.5-pro"
      LLM_API_KEY_NAME="GOOGLE_AI_API_KEY"
      echo ""
      read -p "  Google AI API Key (get one at aistudio.google.com): " LLM_API_KEY
      if [[ -n "$LLM_API_KEY" ]]; then
        log_ok "Google AI API key saved — $LLM_MODEL"
      else
        log_warn "No API key entered — you can add it to .env later"
      fi
      ;;
    4)
      LLM_PROVIDER="ollama"
      echo ""
      if check_command ollama; then
        log_ok "Ollama detected"
      else
        log_info "Installing Ollama..."
        if check_command brew; then
          brew install ollama
        else
          curl -fsSL https://ollama.com/install.sh | sh
        fi
      fi
      echo ""
      echo "  Select local model:"
      echo "    1. llama3.1:8b               — Good balance (8GB RAM)"
      echo "    2. llama3.1:70b              — High quality (64GB RAM)"
      echo "    3. mistral:7b                — Fast, lightweight"
      echo "    4. Custom model"
      echo ""
      read -p "  Enter choice [1-4] (default: 1): " LOCAL_MODEL
      LOCAL_MODEL="${LOCAL_MODEL:-1}"
      case "$LOCAL_MODEL" in
        2) LLM_MODEL="llama3.1:70b" ;;
        3) LLM_MODEL="mistral:7b" ;;
        4) read -p "  Enter model name: " LLM_MODEL ;;
        *) LLM_MODEL="llama3.1:8b" ;;
      esac
      log_info "Pulling model $LLM_MODEL (this may take a while)..."
      ollama pull "$LLM_MODEL" 2>/dev/null || log_warn "Model pull failed — run 'ollama pull $LLM_MODEL' manually"
      ;;
    5)
      LLM_PROVIDER="none"; LLM_MODEL=""; log_ok "No LLM — configure later via settings or openclaw config"
      ;;
  esac
else
  # ── Default mode: install Codex CLI (simplest path) ──
  echo ""
  echo -e "  ${CYAN}Installing OpenAI Codex as your AI engine (default).${NC}"
  echo -e "  ${CYAN}For advanced LLM options, re-run with: ./setup-mac.sh --advanced${NC}"
  echo ""

  LLM_PROVIDER="openai"
  LLM_MODEL="codex"
  LLM_ACCESS_TYPE="subscription"

  log_info "Installing OpenAI Codex CLI..."
  npm install -g @openai/codex 2>/dev/null || log_warn "Codex CLI install failed"

  if check_command codex; then
    log_ok "Codex CLI installed"
    log_info "Launching Codex login (browser will open)..."
    codex auth 2>/dev/null || log_warn "Codex auth skipped — run 'codex auth' later"
    LLM_CLI_TOOL="codex"
  else
    log_warn "Codex CLI install failed — install manually: npm install -g @openai/codex"
  fi
fi

[[ "$LLM_PROVIDER" != "none" ]] && log_ok "$LLM_PROVIDER / $LLM_MODEL ($LLM_ACCESS_TYPE) — used for chat + OpenClaw"

# Same provider for backend — no separate question
LLM_BACKEND_PROVIDER="$LLM_PROVIDER"; LLM_BACKEND_MODEL="$LLM_MODEL"
echo ""
# Configure OpenClaw with the same LLM
if [[ "$LLM_PROVIDER" != "none" ]] && check_command openclaw; then
  log_info "Configuring OpenClaw to use $LLM_PROVIDER..."
  openclaw config set ai.provider "$LLM_PROVIDER" 2>/dev/null
  [[ -n "$LLM_MODEL" ]] && openclaw config set ai.model "$LLM_MODEL" 2>/dev/null
  [[ -n "$LLM_API_KEY" ]] && openclaw config set ai.apiKey "$LLM_API_KEY" 2>/dev/null
  log_ok "OpenClaw configured with same LLM"
fi

# Install SDK
[[ "$LLM_PROVIDER" == "anthropic" ]] && "$PYTHON_CMD" -m pip install --quiet anthropic 2>/dev/null
[[ "$LLM_PROVIDER" == "openai" ]] && "$PYTHON_CMD" -m pip install --quiet openai 2>/dev/null
[[ "$LLM_PROVIDER" == "google" ]] && "$PYTHON_CMD" -m pip install --quiet google-generativeai 2>/dev/null

# ── Environment configuration ──────────────────────────────────────────────
# Worker token fetches Supabase credentials + profile from the API.
# Falls back to manual prompts if token fetch fails.

ENV_FILE="$INSTALL_DIR/.env"
APP_URL="https://applyloop.vercel.app"

# Hardcoded Supabase connection (admin's shared instance — RLS enforces per-user access)
SUPABASE_URL="https://vegcqubtypvdqlduxhqv.supabase.co"
SUPABASE_ANON="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZlZ2NxdWJ0eXB2ZHFsZHV4aHF2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM3NTkyOTYsImV4cCI6MjA4OTMzNTI5Nn0.MJ24A6INzw2dOkv-TZUchM5WGPI2ZG-WxpEy-GROjfw"

if [[ -f "$ENV_FILE" ]]; then
  log_ok ".env file already exists"
  log_info "To reconfigure, delete $ENV_FILE and re-run"
else
  echo ""
  echo -e "  ${BOLD}Enter your worker token (provided by admin after approval).${NC}"
  read -p "  Worker token: " WORKER_TOKEN

  # Fetch profile + telegram config from API using worker token
  TELEGRAM_TOKEN=""
  TELEGRAM_CHAT_ID=""
  if [[ -n "$WORKER_TOKEN" ]]; then
    log_info "Fetching your profile from ApplyLoop..."
    CONFIG_RESPONSE=$(curl -s -H "X-Worker-Token: $WORKER_TOKEN" "$APP_URL/api/settings/cli-config")

    if echo "$CONFIG_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('data')" 2>/dev/null; then
      # Telegram bot token is global (admin's bot) — fetched from API
      TELEGRAM_TOKEN=$(echo "$CONFIG_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(d.get('telegram_bot_token',''))" 2>/dev/null || echo "")
      TELEGRAM_CHAT_ID=$(echo "$CONFIG_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(d.get('telegram_chat_id',''))" 2>/dev/null || echo "")

      # Write profile.json for worker LLM context
      echo "$CONFIG_RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)['data']
profile = {
  'user': d.get('profile', {}),
  'preferences': d.get('preferences', {}),
  'resumes': d.get('resumes', []),
  'work_experience': d.get('profile', {}).get('work_experience', []),
  'education': d.get('profile', {}).get('education', []),
}
json.dump(profile, open('$INSTALL_DIR/profile.json', 'w'), indent=2)
"
      log_ok "Profile synced"
    else
      log_warn "Could not fetch profile (check your worker token). Continuing..."
    fi
  else
    log_warn "No worker token provided. You can add it to .env later."
  fi

  # Auto-generate worker ID
  WORKER_ID="worker-$(hostname -s | tr '[:upper:]' '[:lower:]')-$RANDOM"

  # Generate encryption key
  ENCRYPTION_KEY=$(openssl rand -hex 32)

  cat > "$ENV_FILE" <<ENVEOF
# ApplyLoop Environment Configuration
# Generated by setup-mac.sh on $(date)

# Worker Token (your unique auth — do not share)
WORKER_TOKEN=$WORKER_TOKEN

# Supabase (shared instance — your data is isolated via row-level security)
NEXT_PUBLIC_SUPABASE_URL=$SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=$SUPABASE_ANON
SUPABASE_URL=$SUPABASE_URL
# SUPABASE_SERVICE_KEY is not needed — worker uses API proxy via WORKER_TOKEN
SUPABASE_SERVICE_KEY=$SUPABASE_ANON

# App
NEXT_PUBLIC_APP_URL=$APP_URL
ENCRYPTION_KEY=$ENCRYPTION_KEY

# Worker
WORKER_ID=$WORKER_ID
POLL_INTERVAL=10
APPLY_COOLDOWN=30
RESUME_DIR=/tmp/autoapply/resumes
SCREENSHOT_DIR=/tmp/autoapply/screenshots

# Telegram (auto-configured from admin)
TELEGRAM_BOT_TOKEN=$TELEGRAM_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
ENVEOF

  log_ok ".env file created at $ENV_FILE"
fi

# Create required directories
mkdir -p /tmp/autoapply/resumes /tmp/autoapply/screenshots
log_ok "Worker directories created"

# Skip database migration for regular users — admin handles migrations
# Migrations require the Supabase database password which only the admin has
log_info "Skipping database migration (handled by admin)..."
SKIP_MIGRATION=true
MIGRATION_SCRIPT=""
if [[ -f "$INSTALL_DIR/packages/web/public/setup/run-migration.py" ]]; then
  MIGRATION_SCRIPT="$INSTALL_DIR/packages/web/public/setup/run-migration.py"
else
  # Download migration script
  MIGRATION_SCRIPT="/tmp/autoapply-migration.py"
  curl -fsSL "https://applyloop.vercel.app/setup/run-migration.py" -o "$MIGRATION_SCRIPT" 2>/dev/null
fi

if [[ "$SKIP_MIGRATION" != "true" ]] && [[ -f "$MIGRATION_SCRIPT" ]]; then
  "$PYTHON_CMD" "$MIGRATION_SCRIPT" "$ENV_FILE"
  if [[ $? -eq 0 ]]; then
    log_ok "Database migration complete"
  else
    log_warn "Migration skipped — run manually from Supabase SQL Editor"
  fi
else
  log_ok "Database is managed by admin — no migration needed on your end"
fi

# ── Auto-Update Setup ──────────────────────────────────────────────────────
log_info "Setting up daily auto-updates..."

# Copy update script into install dir
UPDATE_SCRIPT="$INSTALL_DIR/update.sh"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/update-mac.sh" ]; then
  cp "$SCRIPT_DIR/update-mac.sh" "$UPDATE_SCRIPT"
elif [ -f "$INSTALL_DIR/packages/web/public/setup/update-mac.sh" ]; then
  cp "$INSTALL_DIR/packages/web/public/setup/update-mac.sh" "$UPDATE_SCRIPT"
else
  # Download from the hosted URL
  curl -fsSL "https://applyloop.vercel.app/setup/update-mac.sh" -o "$UPDATE_SCRIPT" 2>/dev/null || true
fi

if [ -f "$UPDATE_SCRIPT" ]; then
  chmod +x "$UPDATE_SCRIPT"

  # Set up launchd plist for daily auto-update (runs at 3 AM daily)
  PLIST_DIR="$HOME/Library/LaunchAgents"
  PLIST_FILE="$PLIST_DIR/com.autoapply.update.plist"
  mkdir -p "$PLIST_DIR"

  cat > "$PLIST_FILE" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.autoapply.update</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$UPDATE_SCRIPT</string>
        <string>--check</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/logs/update-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/logs/update-launchd-error.log</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLISTEOF

  # Load the launch agent
  launchctl unload "$PLIST_FILE" 2>/dev/null
  launchctl load "$PLIST_FILE" 2>/dev/null
  log_ok "Auto-update scheduled: on login + daily 3:00 AM (skips if updated within 5 days)"
  log_info "Manual update anytime: bash $UPDATE_SCRIPT"
else
  log_warn "Could not set up auto-updates — update script not found"
fi

# Write LLM config to .env
if [[ -f "$ENV_FILE" ]]; then
  cat >> "$ENV_FILE" <<LLMEOF

# LLM (single provider for chat + OpenClaw)
LLM_ACCESS_TYPE=$LLM_ACCESS_TYPE
LLM_PROVIDER=$LLM_PROVIDER
LLM_MODEL=$LLM_MODEL
LLM_BACKEND_PROVIDER=$LLM_BACKEND_PROVIDER
LLM_BACKEND_MODEL=$LLM_BACKEND_MODEL
$([ -n "$LLM_API_KEY_NAME" ] && [ -n "$LLM_API_KEY" ] && echo "${LLM_API_KEY_NAME}=${LLM_API_KEY}" || echo "# No API key set")
$([ "$LLM_PROVIDER" == "ollama" ] && echo "OLLAMA_BASE_URL=http://localhost:11434")
LLMEOF
  log_ok "LLM config saved to .env"
fi

echo ""

# ── Step 9: Generate setup status + AGENTS.md ─────────────────────────────
log_step 9 "Generating setup status + AGENTS.md..."

# ── Build status data (used for both console dashboard and AGENTS.md) ──────

# Collect component statuses into arrays for reuse
declare -a STATUS_COMPONENTS=()
declare -a STATUS_CONFIG=()
declare -a STATUS_SERVICES=()
declare -a STATUS_TODOS=()

# --- Component checks ---
add_component() {
  local ok=$1 name=$2 detail=$3
  if $ok; then
    STATUS_COMPONENTS+=("[READY]   $name  $detail")
  else
    STATUS_COMPONENTS+=("[MISSING] $name  $detail")
  fi
}

add_component "check_command $PYTHON_CMD" "Python" "$($PYTHON_CMD --version 2>&1)"
add_component "check_command node" "Node.js" "$(node --version 2>&1)"
add_component "check_command npm" "npm" "$(npm --version 2>&1)"
add_component "check_command git" "Git" "$(git --version 2>&1 | head -1)"
add_component "check_command openclaw" "OpenClaw CLI" "$(openclaw --version 2>&1 || echo '')"
add_component "$PYTHON_CMD -c 'import playwright' 2>/dev/null" "Playwright" ""
add_component "$PYTHON_CMD -c 'import supabase' 2>/dev/null" "Supabase SDK" ""
add_component "$PYTHON_CMD -c 'import httpx' 2>/dev/null" "httpx" ""

# LLM CLI
if [[ -n "$LLM_CLI_TOOL" ]]; then
  add_component "check_command $LLM_CLI_TOOL" "$LLM_CLI_TOOL CLI" "$(command -v $LLM_CLI_TOOL 2>/dev/null || echo '')"
fi

# LLM SDKs
if [[ -f "$ENV_FILE" ]]; then
  L1_PROV=$(grep "^LLM_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
  L2_PROV=$(grep "^LLM_BACKEND_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
fi
[[ "$L1_PROV" == "anthropic" || "$L2_PROV" == "anthropic" ]] && add_component "$PYTHON_CMD -c 'import anthropic' 2>/dev/null" "Anthropic SDK" ""
[[ "$L1_PROV" == "openai" || "$L2_PROV" == "openai" ]] && add_component "$PYTHON_CMD -c 'import openai' 2>/dev/null" "OpenAI SDK" ""
[[ "$L1_PROV" == "google" || "$L2_PROV" == "google" ]] && add_component "$PYTHON_CMD -c 'import google.generativeai' 2>/dev/null" "Google AI SDK" ""
[[ "$L1_PROV" == "ollama" || "$L2_PROV" == "ollama" ]] && add_component "check_command ollama" "Ollama" ""

# --- Config checks ---
add_config() {
  local key=$1 label=$2
  if [[ -f "$ENV_FILE" ]] && grep -q "^${key}=.\+" "$ENV_FILE" 2>/dev/null; then
    STATUS_CONFIG+=("[SET]     $label")
  else
    STATUS_CONFIG+=("[NOT SET] $label  <-- action needed")
  fi
}

add_config "NEXT_PUBLIC_SUPABASE_URL" "Supabase URL          (required)"
add_config "NEXT_PUBLIC_SUPABASE_ANON_KEY" "Supabase Anon Key     (required)"
add_config "SUPABASE_SERVICE_ROLE_KEY" "Supabase Service Key  (not needed - API proxy)"
add_config "ENCRYPTION_KEY" "Encryption Key        (required)"
add_config "WORKER_ID" "Worker ID             (required)"
add_config "TELEGRAM_BOT_TOKEN" "Telegram Bot Token    (optional)"
add_config "STRIPE_SECRET_KEY" "Stripe Secret Key     (optional)"
add_config "GOOGLE_CLIENT_ID" "Google OAuth Client   (optional)"
add_config "LLM_PROVIDER" "LLM Provider          (required)"
add_config "LLM_MODEL" "LLM Model             (required)"
add_config "LLM_BACKEND_PROVIDER" "LLM Backend Provider  (required)"
add_config "LLM_BACKEND_MODEL" "LLM Backend Model     (required)"
add_config "ANTHROPIC_API_KEY" "Anthropic API Key     (if Claude)"
add_config "OPENAI_API_KEY" "OpenAI API Key        (if GPT)"

# --- Service checks ---
if [[ -f "$ENV_FILE" ]]; then
  SB_URL=$(grep "^NEXT_PUBLIC_SUPABASE_URL=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
  if [[ -n "$SB_URL" ]] && curl -sf "${SB_URL}/rest/v1/" -o /dev/null 2>/dev/null; then
    STATUS_SERVICES+=("[ONLINE]  Supabase API")
  else
    STATUS_SERVICES+=("[OFFLINE] Supabase API  <-- check URL/keys")
  fi
else
  STATUS_SERVICES+=("[OFFLINE] Supabase API  <-- no .env file")
fi

if [[ -f "$INSTALL_DIR/packages/worker/worker.py" ]]; then
  STATUS_SERVICES+=("[READY]   Worker code")
else
  STATUS_SERVICES+=("[MISSING] Worker code  <-- repo not cloned?")
fi

if check_command openclaw; then
  OC_STATUS=$(openclaw status 2>&1 || echo "")
  if echo "$OC_STATUS" | grep -qi "pro\|active\|licensed"; then
    STATUS_SERVICES+=("[ACTIVE]  OpenClaw Pro License")
  else
    STATUS_SERVICES+=("[FREE]    OpenClaw Pro License  <-- Pro needed (\$20/mo)")
  fi
fi

if [[ -d "/tmp/autoapply/resumes" ]]; then
  STATUS_SERVICES+=("[READY]   Worker directories")
else
  STATUS_SERVICES+=("[MISSING] Worker directories")
fi

# --- TODO checks ---
add_todo() {
  STATUS_TODOS+=("$1")
}

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^NEXT_PUBLIC_SUPABASE_URL=.\+" "$ENV_FILE" 2>/dev/null; then
  add_todo "(required) Add Supabase credentials to .env"
fi

if ! check_command openclaw; then
  add_todo "(required) Install OpenClaw CLI: npm install -g openclaw"
elif ! (openclaw status 2>&1 | grep -qi "pro\|active\|licensed" 2>/dev/null); then
  add_todo "(required) Activate OpenClaw Pro: https://openclaw.com/pricing"
fi

if ! [[ -f "$INSTALL_DIR/packages/worker/worker.py" ]]; then
  add_todo "(required) Clone the ApplyLoop repo (private — ask admin for access)"
fi

if [[ "$LLM_PROVIDER" == "none" && "$LLM_BACKEND_PROVIDER" == "none" ]]; then
  add_todo "(required) Configure LLM provider — re-run setup or edit .env"
elif [[ -f "$ENV_FILE" ]]; then
  if [[ "$LLM_PROVIDER" == "anthropic" || "$LLM_BACKEND_PROVIDER" == "anthropic" ]] && ! grep -q "^ANTHROPIC_API_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
    add_todo "(required) Add Anthropic API key to .env (console.anthropic.com)"
  fi
  if [[ "$LLM_PROVIDER" == "openai" || "$LLM_BACKEND_PROVIDER" == "openai" ]] && ! grep -q "^OPENAI_API_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
    add_todo "(optional) OpenAI API key not needed if using Codex subscription"
  fi
fi

add_todo "(required) Log in at https://applyloop.vercel.app and complete onboarding"
add_todo "(not needed) Database migration handled by admin — skip this"
add_todo "(required) Start the worker: cd packages/worker && $PYTHON_CMD worker.py"

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^STRIPE_SECRET_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
  add_todo "(optional) Set up Stripe billing keys in .env"
fi

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^GOOGLE_CLIENT_ID=.\+" "$ENV_FILE" 2>/dev/null; then
  add_todo "(optional) Set up Google OAuth for Gmail connect"
fi

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^TELEGRAM_BOT_TOKEN=.\+" "$ENV_FILE" 2>/dev/null; then
  add_todo "(optional) Configure Telegram bot for notifications (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)"
fi

# ── Write AGENTS.md ────────────────────────────────────────────────────────
AGENTS_FILE="$INSTALL_DIR/AGENTS.md"

{
  cat <<'AGENTSHEADER'
# ApplyLoop — Agent Context

## What is ApplyLoop?
ApplyLoop is an automated job application engine. It consists of:
- A **web dashboard** (Next.js) for configuration and monitoring
- A **Python worker** that runs locally, scanning for jobs and submitting applications
- An **OpenClaw CLI** for controlling the worker and managing settings
- **Playwright** for browser automation (form filling, resume uploads)

The worker polls Supabase for pending job applications, uses Playwright to fill out
application forms, and reports results back to the dashboard.

AGENTSHEADER

  echo "## System Info"
  echo ""
  echo "- **Install Directory:** $INSTALL_DIR"
  echo "- **Python Command:** $PYTHON_CMD"
  echo "- **OS:** macOS $(sw_vers -productVersion 2>/dev/null || echo 'unknown')"
  echo "- **LLM Provider:** $LLM_PROVIDER ($LLM_ACCESS_TYPE)"
  echo "- **LLM Model:** $LLM_MODEL"
  echo "- **LLM CLI:** ${LLM_CLI_TOOL:-none}"
  echo "- **.env Path:** $ENV_FILE"
  echo ""

  echo "## Setup Status"
  echo ""
  echo "Generated on: $(date)"
  echo ""
  echo "### Installed Components"
  echo '```'
  for line in "${STATUS_COMPONENTS[@]}"; do
    echo "  $line"
  done
  echo '```'
  echo ""

  echo "### Configuration (.env)"
  echo '```'
  for line in "${STATUS_CONFIG[@]}"; do
    echo "  $line"
  done
  echo '```'
  echo ""

  echo "### Services & Connections"
  echo '```'
  for line in "${STATUS_SERVICES[@]}"; do
    echo "  $line"
  done
  echo '```'
  echo ""

  echo "## TODO — Remaining Tasks"
  echo ""
  if [[ ${#STATUS_TODOS[@]} -eq 0 ]]; then
    echo "Nothing! Setup is fully complete."
  else
    local_i=0
    for todo in "${STATUS_TODOS[@]}"; do
      ((local_i++))
      echo "$local_i. $todo"
    done
  fi
  echo ""

  cat <<AGENTSCMDS
## OpenClaw Commands Reference

\`\`\`bash
openclaw config set ai.provider <provider>   # Set LLM provider
openclaw config set ai.model <model>         # Set LLM model
openclaw config set ai.apiKey <key>          # Set API key
openclaw config get                          # Show current config
openclaw status                              # Show license/status
openclaw start                               # Start worker via OpenClaw
\`\`\`

## API Endpoints (Settings)

| Endpoint | Purpose |
|----------|---------|
| \`GET /api/settings\`       | Get current user settings |
| \`PUT /api/settings\`       | Update user settings |
| \`GET /api/usage\`          | Get usage metrics |
| \`GET /api/auth/me\`        | Current user info |
| \`POST /api/extract-job-metadata\` | Parse job description |

## How to Update .env

\`\`\`bash
# Open in default editor
\${EDITOR:-nano} $ENV_FILE

# Or set a specific variable via shell:
echo 'NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co' >> $ENV_FILE
\`\`\`

## Database Migration

\`\`\`bash
cd $INSTALL_DIR
$PYTHON_CMD packages/web/public/setup/run-migration.py $ENV_FILE
\`\`\`

## Starting the Worker

\`\`\`bash
cd $INSTALL_DIR/packages/worker
$PYTHON_CMD worker.py
\`\`\`

## Starting the Web App (Development)

\`\`\`bash
cd $INSTALL_DIR/packages/web
npm run dev
\`\`\`
AGENTSCMDS

} > "$AGENTS_FILE"

log_ok "AGENTS.md written to $AGENTS_FILE"

# ── Print console status dashboard ─────────────────────────────────────────

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║                  SETUP STATUS DASHBOARD                     ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"

# --- Installed Components ---
echo -e "${BOLD}║  INSTALLED COMPONENTS                                       ║${NC}"
echo -e "${BOLD}╠──────────────────────────────────────────────────────────────╣${NC}"

status_line() {
  local ok=$1 name=$2 detail=$3
  if $ok; then
    printf "  ${GREEN}[READY]${NC}   %-22s %s\n" "$name" "$detail"
  else
    printf "  ${RED}[MISSING]${NC} %-22s %s\n" "$name" "$detail"
  fi
}

status_line "check_command $PYTHON_CMD" "Python" "$($PYTHON_CMD --version 2>&1)"
status_line "check_command node" "Node.js" "$(node --version 2>&1)"
status_line "check_command npm" "npm" "$(npm --version 2>&1)"
status_line "check_command git" "Git" "$(git --version 2>&1 | head -1)"
status_line "check_command openclaw" "OpenClaw CLI" "$(openclaw --version 2>&1 || echo '')"
status_line "$PYTHON_CMD -c 'import playwright' 2>/dev/null" "Playwright" ""
status_line "$PYTHON_CMD -c 'import supabase' 2>/dev/null" "Supabase SDK" ""
status_line "$PYTHON_CMD -c 'import httpx' 2>/dev/null" "httpx" ""

# LLM CLI
if [[ -n "$LLM_CLI_TOOL" ]]; then
  status_line "check_command $LLM_CLI_TOOL" "$LLM_CLI_TOOL CLI" ""
fi

# LLM SDKs
if [[ "$L1_PROV" == "anthropic" || "$L2_PROV" == "anthropic" ]]; then
  status_line "$PYTHON_CMD -c 'import anthropic' 2>/dev/null" "Anthropic SDK" ""
fi
if [[ "$L1_PROV" == "openai" || "$L2_PROV" == "openai" ]]; then
  status_line "$PYTHON_CMD -c 'import openai' 2>/dev/null" "OpenAI SDK" ""
fi
if [[ "$L1_PROV" == "google" || "$L2_PROV" == "google" ]]; then
  status_line "$PYTHON_CMD -c 'import google.generativeai' 2>/dev/null" "Google AI SDK" ""
fi
if [[ "$L1_PROV" == "ollama" || "$L2_PROV" == "ollama" ]]; then
  status_line "check_command ollama" "Ollama" ""
fi

echo ""
echo -e "${BOLD}╠──────────────────────────────────────────────────────────────╣${NC}"
echo -e "${BOLD}║  CONFIGURATION                                              ║${NC}"
echo -e "${BOLD}╠──────────────────────────────────────────────────────────────╣${NC}"

# Check .env keys
env_check() {
  local key=$1 label=$2
  if [[ -f "$ENV_FILE" ]] && grep -q "^${key}=.\+" "$ENV_FILE" 2>/dev/null; then
    printf "  ${GREEN}[SET]${NC}     %-22s\n" "$label"
  else
    printf "  ${YELLOW}[NOT SET]${NC} %-22s ${YELLOW}<-- action needed${NC}\n" "$label"
  fi
}

status_line "test -f $ENV_FILE" ".env file" "$ENV_FILE"
env_check "NEXT_PUBLIC_SUPABASE_URL" "Supabase URL          (required)"
env_check "NEXT_PUBLIC_SUPABASE_ANON_KEY" "Supabase Anon Key     (required)"
env_check "SUPABASE_SERVICE_ROLE_KEY" "Supabase Service Key  (not needed)"
env_check "ENCRYPTION_KEY" "Encryption Key        (required)"
env_check "WORKER_ID" "Worker ID             (required)"
env_check "TELEGRAM_BOT_TOKEN" "Telegram Bot Token    (optional)"
env_check "STRIPE_SECRET_KEY" "Stripe Secret Key     (optional)"
env_check "GOOGLE_CLIENT_ID" "Google OAuth Client   (optional)"

echo ""
echo -e "  ${BOLD}LLM Config:${NC}"
env_check "LLM_PROVIDER" "LLM Provider L1       (required)"
env_check "LLM_MODEL" "LLM Model L1          (required)"
env_check "LLM_BACKEND_PROVIDER" "LLM Provider L2       (required)"
env_check "LLM_BACKEND_MODEL" "LLM Model L2          (required)"
env_check "ANTHROPIC_API_KEY" "Anthropic API Key     (if Claude)"
env_check "OPENAI_API_KEY" "OpenAI API Key        (if GPT)"

echo ""
echo -e "${BOLD}╠──────────────────────────────────────────────────────────────╣${NC}"
echo -e "${BOLD}║  SERVICES & CONNECTIONS                                     ║${NC}"
echo -e "${BOLD}╠──────────────────────────────────────────────────────────────╣${NC}"

# Test Supabase connection
if [[ -f "$ENV_FILE" ]]; then
  SB_URL=$(grep "^NEXT_PUBLIC_SUPABASE_URL=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
  if [[ -n "$SB_URL" ]] && curl -sf "${SB_URL}/rest/v1/" -o /dev/null 2>/dev/null; then
    printf "  ${GREEN}[ONLINE]${NC}  %-22s\n" "Supabase API"
  else
    printf "  ${RED}[OFFLINE]${NC} %-22s ${YELLOW}<-- check URL/keys${NC}\n" "Supabase API"
  fi
else
  printf "  ${RED}[OFFLINE]${NC} %-22s ${YELLOW}<-- no .env file${NC}\n" "Supabase API"
fi

# Check if worker directory and files exist
if [[ -f "$INSTALL_DIR/packages/worker/worker.py" ]]; then
  printf "  ${GREEN}[READY]${NC}   %-22s\n" "Worker code"
else
  printf "  ${YELLOW}[MISSING]${NC} %-22s ${YELLOW}<-- repo not cloned?${NC}\n" "Worker code"
fi

# Check OpenClaw Pro (license)
if check_command openclaw; then
  OC_STATUS=$(openclaw status 2>&1 || echo "")
  if echo "$OC_STATUS" | grep -qi "pro\|active\|licensed"; then
    printf "  ${GREEN}[ACTIVE]${NC}  %-22s\n" "OpenClaw Pro License"
  else
    printf "  ${YELLOW}[FREE]${NC}    %-22s ${YELLOW}<-- Pro needed (\$20/mo)${NC}\n" "OpenClaw Pro License"
  fi
fi

status_line "test -d /tmp/autoapply/resumes" "Worker directories" ""

echo ""
echo -e "${BOLD}╠──────────────────────────────────────────────────────────────╣${NC}"
echo -e "${BOLD}║  STILL TODO                                                 ║${NC}"
echo -e "${BOLD}╠──────────────────────────────────────────────────────────────╣${NC}"

TODO_COUNT=0

print_todo() {
  ((TODO_COUNT++))
  printf "  ${YELLOW}$TODO_COUNT.${NC} %s\n" "$1"
}

# Check what's still needed
if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^NEXT_PUBLIC_SUPABASE_URL=.\+" "$ENV_FILE" 2>/dev/null; then
  print_todo "(required) Add Supabase credentials to .env"
fi

if ! check_command openclaw; then
  print_todo "(required) Install OpenClaw CLI: npm install -g openclaw"
elif ! (openclaw status 2>&1 | grep -qi "pro\|active\|licensed" 2>/dev/null); then
  print_todo "(required) Activate OpenClaw Pro: https://openclaw.com/pricing"
fi

if ! [[ -f "$INSTALL_DIR/packages/worker/worker.py" ]]; then
  print_todo "(required) Clone the ApplyLoop repo (private — ask admin for access)"
fi

if [[ "$LLM_PROVIDER" == "none" && "$LLM_BACKEND_PROVIDER" == "none" ]]; then
  print_todo "(required) Configure LLM provider — re-run setup or edit .env"
elif [[ -f "$ENV_FILE" ]]; then
  if [[ "$LLM_PROVIDER" == "anthropic" || "$LLM_BACKEND_PROVIDER" == "anthropic" ]] && ! grep -q "^ANTHROPIC_API_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
    print_todo "(required) Add Anthropic API key to .env (console.anthropic.com)"
  fi
  if [[ "$LLM_PROVIDER" == "openai" || "$LLM_BACKEND_PROVIDER" == "openai" ]] && ! grep -q "^OPENAI_API_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
    print_todo "(optional) OpenAI API key not needed if using Codex subscription"
  fi
fi

print_todo "(required) Log in at https://applyloop.vercel.app and complete onboarding"
print_todo "(not needed) Database migration handled by admin — skip this"
print_todo "(required) Start the worker: cd packages/worker && $PYTHON_CMD worker.py"

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^STRIPE_SECRET_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
  print_todo "(optional) Set up Stripe billing keys in .env"
fi

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^GOOGLE_CLIENT_ID=.\+" "$ENV_FILE" 2>/dev/null; then
  print_todo "(optional) Set up Google OAuth for Gmail connect"
fi

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^TELEGRAM_BOT_TOKEN=.\+" "$ENV_FILE" 2>/dev/null; then
  print_todo "(optional) Configure Telegram bot for notifications (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)"
fi

if [[ $TODO_COUNT -eq 0 ]]; then
  echo -e "  ${GREEN}Nothing! You're all set.${NC}"
fi

echo ""
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Run this status check anytime: ${CYAN}bash ~/autoapply/status.sh${NC}"
echo ""

# ── Copy SOUL.md to install directory ──────────────────────────────────────
SOUL_SOURCE="$INSTALL_DIR/packages/worker/SOUL.md"
if [[ ! -f "$SOUL_SOURCE" ]]; then
  SOUL_SOURCE="$INSTALL_DIR/repo/packages/worker/SOUL.md"
fi
if [[ -f "$SOUL_SOURCE" ]]; then
  cp "$SOUL_SOURCE" "$INSTALL_DIR/SOUL.md"
  log_ok "SOUL.md copied to $INSTALL_DIR"
else
  curl -s "https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/packages/worker/SOUL.md" -o "$INSTALL_DIR/SOUL.md" 2>/dev/null
  [[ -f "$INSTALL_DIR/SOUL.md" ]] && log_ok "SOUL.md downloaded" || log_warn "Could not get SOUL.md"
fi

# ── Step 10: Launch LLM CLI (or fall back to manual) ──────────────────────
log_step 10 "Launching setup assistant..."

# Build the context prompt — just point to SOUL.md
USER_NAME="$(whoami)"
CLI_PROMPT="Read SOUL.md in this directory. It contains your complete instructions.
You are ApplyLoop for $USER_NAME. Follow SOUL.md exactly.
Start by greeting the user, then begin the scout→filter→apply loop.
Do NOT run worker.py — YOU are the worker. Call openclaw browser commands directly.
Profile is in profile.json. Learnings are in packages/worker/knowledge/learnings.md.

## INTRODUCE YOURSELF FIRST
When the user opens this chat, immediately say:

\"Hi $USER_NAME! I'm your ApplyLoop assistant. Here's what I can do for you:

**Job Scouting** — I search 6 job boards every 30 minutes:
- Ashby (51 companies: Perplexity, Cohere, Notion, Cursor, Ramp...)
- Greenhouse (68 companies: Coinbase, Figma, Datadog, Waymo, DoorDash...)
- Indeed (massive volume across all companies)
- Himalayas (remote-focused roles)
- LinkedIn (public search)

**Smart Filtering** — I only show you relevant roles:
- AI/ML/Data roles matching your preferences
- US locations, posted in last 24 hours
- Skip senior roles at big tech, skip management/VP/intern
- Max 5 applications per company per month

**Auto-Apply** — I fill out applications for you:
- Open each job form, read every field
- Fill in your full profile (work history, education, skills)
- Upload your resume automatically
- Submit and take a screenshot as proof
- Send you a Telegram notification for each submission

**Commands you can use:**
- **start** — begin scouting and auto-applying
- **scout** — scan job boards right now
- **status** — show your profile and what's configured
- **apply to [URL]** — apply to a specific job
- **stop** — pause the worker
- **update** — pull latest improvements

Would you like me to start scouting for jobs now?\"

## SETUP CHECK (do this silently before introducing yourself)
1. Check if packages/worker/worker.py exists. If not:
   git clone https://github.com/snehitvaddi/AutoApply.git $INSTALL_DIR/repo
   cp -r $INSTALL_DIR/repo/* $INSTALL_DIR/
2. Check .env has WORKER_TOKEN set
3. Check profile.json has user data (if empty, fetch via: curl -s -H \"X-Worker-Token: TOKEN\" https://applyloop.vercel.app/api/settings/cli-config)
4. Fix any issues silently, then greet the user

## WHEN USER SAYS \"start\" or \"scout\"
Run: cd $INSTALL_DIR/packages/worker && $PYTHON_CMD worker.py

## WHEN USER SAYS \"status\"
Read profile.json and .env, show:
- Name, email, target roles
- How many resumes uploaded
- Telegram connected? (check TELEGRAM_CHAT_ID in .env)
- Worker token set?
- Last scout results if available

## WHEN USER SAYS \"apply to [URL]\"
Run the applier directly on that URL using the worker's apply logic.

## APPLYING RULES (critical)
- ONE job at a time — fill every field, verify success before next
- Fill ALL work experiences and ALL education — never truncate
- Short answers for basic fields (sponsorship, salary, location)
- Long 3-4 sentence answers ONLY for \"Why interested?\" type questions
- Upload resume via JS/CLI, never file explorer
- Screenshot after submission → Telegram notification

## REMAINING SETUP (guide user if needed)
- **Telegram**: message @ApplyLoopBot on Telegram → send /start → copy Chat ID → paste in Settings > Telegram on applyloop.vercel.app
- **Gmail (optional)**: go to applyloop.vercel.app → Settings → Email → Connect Gmail (for reading verification codes)
- **Himalaya (optional)**: for power users — go to myaccount.google.com/apppasswords → create app password → configure himalaya
- **AgentMail (optional)**: sign up at agentmail.to → get API key → add AGENTMAIL_API_KEY to .env

## TECHNICAL DETAILS (don't show to user unless asked)
- .env: $ENV_FILE
- Install dir: $INSTALL_DIR
- Python: $PYTHON_CMD
- Profile: $INSTALL_DIR/profile.json
- Worker uses API proxy via WORKER_TOKEN (no Supabase service key needed)
- Codex subscription covers LLM (no OpenAI API key needed)
- Database migrations handled by admin (not user)

## AUTO-START BEHAVIOR
When you launch, do this IMMEDIATELY without waiting for user input:
1. Silently check if packages/worker/worker.py exists — if not, clone the repo
2. Silently check .env has WORKER_TOKEN — if not, ask for it once
3. Greet the user with your capabilities (the intro message above)
4. Then say: \"Starting the scout→apply loop now...\"
5. Run: cd $INSTALL_DIR/packages/worker && $PYTHON_CMD worker.py
6. The worker runs an INFINITE LOOP: scout every 30 min → filter → apply → telegram notify → repeat
7. While the worker runs, relay its output to the user in plain language:
   - \"Scanning 51 Ashby boards...\"
   - \"Found 12 matching jobs\"
   - \"Applying to [Company] - [Role]...\"
   - \"✅ Applied to [Company]! Screenshot sent to Telegram.\"
8. If the user types anything while the worker is running, pause to respond, then resume
9. NEVER stop the loop unless the user says \"stop\""

# Determine which CLI is available based on LLM_PROVIDER
CLI_CMD=""
if [[ "$LLM_PROVIDER" == "anthropic" ]] && check_command claude; then
  CLI_CMD="claude"
elif [[ "$LLM_PROVIDER" == "openai" ]] && check_command codex; then
  CLI_CMD="codex"
fi

if [[ -n "$CLI_CMD" ]]; then
  echo ""
  echo -e "${BOLD}Launching $CLI_CMD to complete setup...${NC}"
  echo -e "${CYAN}$CLI_CMD will help you finish configuring ApplyLoop.${NC}"
  echo -e "${CYAN}You can paste credentials, ask questions, or type 'exit' to quit.${NC}"
  echo ""

  # Export API key so the CLI can use it
  if [[ "$LLM_PROVIDER" == "anthropic" && -n "$LLM_API_KEY" ]]; then
    export ANTHROPIC_API_KEY="$LLM_API_KEY"
  elif [[ "$LLM_PROVIDER" == "openai" && -n "$LLM_API_KEY" ]]; then
    export OPENAI_API_KEY="$LLM_API_KEY"
  fi

  # exec replaces the shell — this is the final action
  if [[ "$CLI_CMD" == "codex" ]]; then
    exec codex --full-auto --cd "$INSTALL_DIR" "Read SOUL.md in this directory and follow it exactly. You are ApplyLoop. Start the scout→filter→apply loop immediately using openclaw browser commands. Do NOT run worker.py."
  else
    exec "$CLI_CMD" --cd "$INSTALL_DIR" "$CLI_PROMPT"
  fi
else
  # No CLI available — show manual next steps
  log_warn "No AI CLI available — showing setup status manually."
  echo ""

  # Interactive fallback — offer worker token or manual Supabase entry
  HAS_SB_URL=false
  [[ -f "$ENV_FILE" ]] && grep -q "^NEXT_PUBLIC_SUPABASE_URL=.\+" "$ENV_FILE" 2>/dev/null && HAS_SB_URL=true

  if [[ "$HAS_SB_URL" != "true" ]]; then
    echo ""
    echo -e "${BOLD}Would you like to enter your worker token now?${NC}"
    read -p "  [y/N]: " ENTER_TOKEN
    if [[ "$ENTER_TOKEN" =~ ^[Yy] ]]; then
      read -p "  Worker token (from admin): " FALLBACK_TOKEN
      log_info "Fetching credentials from ApplyLoop..."
      RESP=$(curl -s -H "X-Worker-Token: $FALLBACK_TOKEN" "$APP_URL/api/settings/cli-config" 2>/dev/null)
      if echo "$RESP" | "$PYTHON_CMD" -c "import sys,json; d=json.load(sys.stdin); assert d.get('data')" 2>/dev/null; then
        SB_URL_VAL=$(echo "$RESP" | "$PYTHON_CMD" -c "import sys,json; print(json.load(sys.stdin)['data'].get('supabase_url',''))" 2>/dev/null)
        SB_ANON_VAL=$(echo "$RESP" | "$PYTHON_CMD" -c "import sys,json; print(json.load(sys.stdin)['data'].get('supabase_anon_key',''))" 2>/dev/null)
        if [[ -n "$SB_URL_VAL" ]]; then
          sed -i '' "s|^WORKER_TOKEN=.*|WORKER_TOKEN=$FALLBACK_TOKEN|" "$ENV_FILE"
          sed -i '' "s|^NEXT_PUBLIC_SUPABASE_URL=.*|NEXT_PUBLIC_SUPABASE_URL=$SB_URL_VAL|" "$ENV_FILE"
          sed -i '' "s|^SUPABASE_URL=.*|SUPABASE_URL=$SB_URL_VAL|" "$ENV_FILE"
        fi
        if [[ -n "$SB_ANON_VAL" ]]; then
          sed -i '' "s|^NEXT_PUBLIC_SUPABASE_ANON_KEY=.*|NEXT_PUBLIC_SUPABASE_ANON_KEY=$SB_ANON_VAL|" "$ENV_FILE"
        fi
        log_ok "Credentials fetched and saved to .env"
      else
        log_warn "Could not fetch — entering manually"
        read -p "  Supabase URL: " MANUAL_SB_URL
        read -p "  Supabase Anon Key: " MANUAL_SB_ANON
        if [[ -n "$MANUAL_SB_URL" ]]; then
          sed -i '' "s|^NEXT_PUBLIC_SUPABASE_URL=.*|NEXT_PUBLIC_SUPABASE_URL=$MANUAL_SB_URL|" "$ENV_FILE"
          sed -i '' "s|^SUPABASE_URL=.*|SUPABASE_URL=$MANUAL_SB_URL|" "$ENV_FILE"
        fi
        if [[ -n "$MANUAL_SB_ANON" ]]; then
          sed -i '' "s|^NEXT_PUBLIC_SUPABASE_ANON_KEY=.*|NEXT_PUBLIC_SUPABASE_ANON_KEY=$MANUAL_SB_ANON|" "$ENV_FILE"
        fi
        log_ok "Credentials saved to .env"
      fi
    fi
  fi

  echo ""
  echo -e "${BOLD}Next steps:${NC}"
  echo ""
  echo "  1. Edit .env with remaining credentials:"
  echo -e "     ${CYAN}\${EDITOR:-nano} $ENV_FILE${NC}"
  echo ""
  echo "  2. Start the worker:"
  echo -e "     ${CYAN}cd $INSTALL_DIR/packages/worker${NC}"
  echo -e "     ${CYAN}source ../../.env && $PYTHON_CMD worker.py${NC}"
  echo ""
  echo "  3. Start the web app (development):"
  echo -e "     ${CYAN}cd $INSTALL_DIR/packages/web${NC}"
  echo -e "     ${CYAN}npm run dev${NC}"
  echo ""
  echo -e "  ${YELLOW}Full context saved to: $AGENTS_FILE${NC}"
  echo -e "  ${CYAN}Run this status check anytime: bash ~/autoapply/status.sh${NC}"
  echo -e "  ${YELLOW}Need help? See docs/CLIENT-ONBOARDING.md${NC}"
  echo ""
fi
