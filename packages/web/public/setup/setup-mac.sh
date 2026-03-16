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

TOTAL_STEPS=10

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
echo "  9. Configure LLM providers (Claude / OpenAI / Local)"
echo "  10. Verify the setup"
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

# ── Step 9: LLM Configuration ──────────────────────────────────────────────
log_step 9 "Configuring LLM providers..."

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              LLM CONFIGURATION                              ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║  AutoApply uses LLMs at two levels:                         ║${NC}"
echo -e "${BOLD}║                                                             ║${NC}"
echo -e "${CYAN}║  Level 1: USER-FACING (Chat & AI Profile Import)            ║${NC}"
echo -e "${CYAN}║    → Powers the chat thread where users interact            ║${NC}"
echo -e "${CYAN}║    → Extracts profile data from conversations               ║${NC}"
echo -e "${CYAN}║    → Visible to the end user                                ║${NC}"
echo -e "${BOLD}║                                                             ║${NC}"
echo -e "${CYAN}║  Level 2: BACKEND (Server-side Automation)                  ║${NC}"
echo -e "${CYAN}║    → Powers smart form filling & resume tailoring           ║${NC}"
echo -e "${CYAN}║    → Runs behind OpenClaw browser automation                ║${NC}"
echo -e "${CYAN}║    → Not visible to the end user                            ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# --- Level 1: User-Facing LLM ---
echo -e "${BOLD}━━━ Level 1: User-Facing LLM ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Which LLM provider for the USER-FACING chat?"
echo ""
echo "    1. Claude (Anthropic)        — Best for reasoning & safety"
echo "    2. GPT (OpenAI)              — Most popular, broad support"
echo "    3. Gemini (Google)           — Good multimodal support"
echo "    4. Local/Ollama              — Free, private, runs locally"
echo "    5. None (keep manual copy-paste)"
echo ""
read -p "  Enter choice [1-5] (default: 1): " LLM_L1_CHOICE
LLM_L1_CHOICE="${LLM_L1_CHOICE:-1}"

LLM_PROVIDER=""
LLM_MODEL=""
LLM_API_KEY_NAME=""
LLM_API_KEY=""

case "$LLM_L1_CHOICE" in
  1)
    LLM_PROVIDER="anthropic"
    echo ""
    echo "  Select Claude model:"
    echo "    1. claude-sonnet-4-6         — Fast, cost-effective (recommended)"
    echo "    2. claude-opus-4-6           — Most capable, higher cost"
    echo "    3. claude-haiku-4-5          — Fastest, lowest cost"
    echo ""
    read -p "  Enter choice [1-3] (default: 1): " CLAUDE_MODEL
    CLAUDE_MODEL="${CLAUDE_MODEL:-1}"
    case "$CLAUDE_MODEL" in
      2) LLM_MODEL="claude-opus-4-6" ;;
      3) LLM_MODEL="claude-haiku-4-5-20251001" ;;
      *) LLM_MODEL="claude-sonnet-4-6" ;;
    esac
    LLM_API_KEY_NAME="ANTHROPIC_API_KEY"
    echo ""
    read -p "  Anthropic API Key (get one at console.anthropic.com): " LLM_API_KEY
    if [[ -n "$LLM_API_KEY" ]]; then
      log_ok "Anthropic API key saved — $LLM_MODEL"
    else
      log_warn "No API key entered — you can add it to .env later"
    fi
    ;;
  2)
    LLM_PROVIDER="openai"
    echo ""
    echo "  Select OpenAI model:"
    echo "    1. gpt-4.1                  — Latest, best quality (recommended)"
    echo "    2. gpt-4.1-mini             — Fast, cost-effective"
    echo "    3. gpt-4.1-nano             — Fastest, lowest cost"
    echo "    4. o3                       — Best reasoning"
    echo ""
    read -p "  Enter choice [1-4] (default: 1): " OAI_MODEL
    OAI_MODEL="${OAI_MODEL:-1}"
    case "$OAI_MODEL" in
      2) LLM_MODEL="gpt-4.1-mini" ;;
      3) LLM_MODEL="gpt-4.1-nano" ;;
      4) LLM_MODEL="o3" ;;
      *) LLM_MODEL="gpt-4.1" ;;
    esac
    LLM_API_KEY_NAME="OPENAI_API_KEY"
    echo ""
    read -p "  OpenAI API Key (get one at platform.openai.com): " LLM_API_KEY
    if [[ -n "$LLM_API_KEY" ]]; then
      log_ok "OpenAI API key saved — $LLM_MODEL"
    else
      log_warn "No API key entered — you can add it to .env later"
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
    LLM_API_KEY_NAME=""
    LLM_API_KEY=""
    ;;
  5)
    LLM_PROVIDER="none"
    LLM_MODEL=""
    log_ok "No user-facing LLM — keeping manual copy-paste mode"
    ;;
esac

# --- Level 2: Backend LLM ---
echo ""
echo -e "${BOLD}━━━ Level 2: Backend LLM (Server Automation) ━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Which LLM provider for BACKEND automation?"
echo -e "  ${CYAN}(Used for smart form filling, resume tailoring, cover letters)${NC}"
echo ""
echo "    1. Claude (Anthropic)        — Best for structured output"
echo "    2. GPT (OpenAI)              — Strong function calling"
echo "    3. Gemini (Google)           — Cost-effective for high volume"
echo "    4. Local/Ollama              — Free, private, no API costs"

if [[ "$LLM_PROVIDER" != "none" ]]; then
  SAME_LABEL="Same as Level 1 ($LLM_PROVIDER — $LLM_MODEL)"
  echo "    5. $SAME_LABEL"
fi

echo "    6. None (basic automation only — no LLM)"
echo ""
read -p "  Enter choice [1-6] (default: 5): " LLM_L2_CHOICE
LLM_L2_CHOICE="${LLM_L2_CHOICE:-5}"

LLM_BACKEND_PROVIDER=""
LLM_BACKEND_MODEL=""
LLM_BACKEND_API_KEY_NAME=""
LLM_BACKEND_API_KEY=""

case "$LLM_L2_CHOICE" in
  1)
    LLM_BACKEND_PROVIDER="anthropic"
    LLM_BACKEND_MODEL="claude-sonnet-4-6"
    LLM_BACKEND_API_KEY_NAME="ANTHROPIC_API_KEY"
    if [[ "$LLM_PROVIDER" == "anthropic" && -n "$LLM_API_KEY" ]]; then
      LLM_BACKEND_API_KEY="$LLM_API_KEY"
      log_ok "Reusing Anthropic API key from Level 1"
    else
      read -p "  Anthropic API Key: " LLM_BACKEND_API_KEY
    fi
    ;;
  2)
    LLM_BACKEND_PROVIDER="openai"
    LLM_BACKEND_MODEL="gpt-4.1-mini"
    LLM_BACKEND_API_KEY_NAME="OPENAI_API_KEY"
    if [[ "$LLM_PROVIDER" == "openai" && -n "$LLM_API_KEY" ]]; then
      LLM_BACKEND_API_KEY="$LLM_API_KEY"
      log_ok "Reusing OpenAI API key from Level 1"
    else
      read -p "  OpenAI API Key: " LLM_BACKEND_API_KEY
    fi
    ;;
  3)
    LLM_BACKEND_PROVIDER="google"
    LLM_BACKEND_MODEL="gemini-2.5-flash"
    LLM_BACKEND_API_KEY_NAME="GOOGLE_AI_API_KEY"
    if [[ "$LLM_PROVIDER" == "google" && -n "$LLM_API_KEY" ]]; then
      LLM_BACKEND_API_KEY="$LLM_API_KEY"
      log_ok "Reusing Google AI API key from Level 1"
    else
      read -p "  Google AI API Key: " LLM_BACKEND_API_KEY
    fi
    ;;
  4)
    LLM_BACKEND_PROVIDER="ollama"
    LLM_BACKEND_MODEL="llama3.1:8b"
    if ! check_command ollama; then
      log_info "Installing Ollama..."
      curl -fsSL https://ollama.com/install.sh | sh
    fi
    ollama pull "$LLM_BACKEND_MODEL" 2>/dev/null || true
    ;;
  5)
    LLM_BACKEND_PROVIDER="$LLM_PROVIDER"
    LLM_BACKEND_MODEL="$LLM_MODEL"
    LLM_BACKEND_API_KEY_NAME="$LLM_API_KEY_NAME"
    LLM_BACKEND_API_KEY="$LLM_API_KEY"
    log_ok "Reusing Level 1 config for backend ($LLM_PROVIDER — $LLM_MODEL)"
    ;;
  6)
    LLM_BACKEND_PROVIDER="none"
    LLM_BACKEND_MODEL=""
    log_ok "No backend LLM — basic automation only"
    ;;
esac

# --- LLM Features ---
echo ""
echo -e "${BOLD}━━━ LLM Features ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

LLM_RESUME_TAILORING="false"
LLM_COVER_LETTERS="false"
LLM_SMART_ANSWERS="false"
LLM_MONTHLY_LIMIT="0"

if [[ "$LLM_BACKEND_PROVIDER" != "none" ]]; then
  read -p "  Enable resume tailoring per job? (LLM customizes resume) [Y/n]: " FEAT_RESUME
  FEAT_RESUME="${FEAT_RESUME:-Y}"
  [[ "$FEAT_RESUME" =~ ^[Yy] ]] && LLM_RESUME_TAILORING="true"

  read -p "  Enable auto cover letter generation? [Y/n]: " FEAT_COVER
  FEAT_COVER="${FEAT_COVER:-Y}"
  [[ "$FEAT_COVER" =~ ^[Yy] ]] && LLM_COVER_LETTERS="true"

  read -p "  Enable smart form-field answering? (\"Why do you want to work here?\" etc.) [Y/n]: " FEAT_SMART
  FEAT_SMART="${FEAT_SMART:-Y}"
  [[ "$FEAT_SMART" =~ ^[Yy] ]] && LLM_SMART_ANSWERS="true"

  echo ""
  read -p "  Set monthly LLM spending limit \$/month [0 = unlimited] (default: 50): " LLM_MONTHLY_LIMIT
  LLM_MONTHLY_LIMIT="${LLM_MONTHLY_LIMIT:-50}"
  echo -e "  ${GREEN}→ Monthly limit set: \$${LLM_MONTHLY_LIMIT}${NC}"
else
  log_info "Skipping LLM features (no backend LLM selected)"
fi

# --- Install LLM SDKs ---
echo ""
if [[ "$LLM_PROVIDER" == "anthropic" || "$LLM_BACKEND_PROVIDER" == "anthropic" ]]; then
  log_info "Installing Anthropic SDK..."
  "$PYTHON_CMD" -m pip install --quiet anthropic 2>/dev/null
  log_ok "Anthropic Python SDK installed"
fi

if [[ "$LLM_PROVIDER" == "openai" || "$LLM_BACKEND_PROVIDER" == "openai" ]]; then
  log_info "Installing OpenAI SDK..."
  "$PYTHON_CMD" -m pip install --quiet openai 2>/dev/null
  log_ok "OpenAI Python SDK installed"
fi

if [[ "$LLM_PROVIDER" == "google" || "$LLM_BACKEND_PROVIDER" == "google" ]]; then
  log_info "Installing Google AI SDK..."
  "$PYTHON_CMD" -m pip install --quiet google-generativeai 2>/dev/null
  log_ok "Google AI Python SDK installed"
fi

# --- Write LLM config to .env ---
if [[ -f "$ENV_FILE" ]]; then
  # Append LLM config to existing .env
  cat >> "$ENV_FILE" <<LLMEOF

# ── LLM Configuration ─────────────────────────────────────
# Level 1: User-Facing (Chat & AI Import)
LLM_PROVIDER=$LLM_PROVIDER
LLM_MODEL=$LLM_MODEL

# Level 2: Backend (Server Automation)
LLM_BACKEND_PROVIDER=$LLM_BACKEND_PROVIDER
LLM_BACKEND_MODEL=$LLM_BACKEND_MODEL

# API Keys
$([ -n "$LLM_API_KEY_NAME" ] && [ -n "$LLM_API_KEY" ] && echo "${LLM_API_KEY_NAME}=${LLM_API_KEY}" || echo "# No Level 1 API key set")
$([ -n "$LLM_BACKEND_API_KEY_NAME" ] && [ -n "$LLM_BACKEND_API_KEY" ] && [ "$LLM_BACKEND_API_KEY_NAME" != "$LLM_API_KEY_NAME" ] && echo "${LLM_BACKEND_API_KEY_NAME}=${LLM_BACKEND_API_KEY}" || echo "# Backend uses same key as Level 1")
$([ "$LLM_BACKEND_PROVIDER" == "ollama" ] && echo "OLLAMA_BASE_URL=http://localhost:11434" || echo "# OLLAMA_BASE_URL=http://localhost:11434")

# LLM Features
LLM_RESUME_TAILORING=$LLM_RESUME_TAILORING
LLM_COVER_LETTERS=$LLM_COVER_LETTERS
LLM_SMART_ANSWERS=$LLM_SMART_ANSWERS
LLM_MONTHLY_LIMIT=$LLM_MONTHLY_LIMIT
LLMEOF
  log_ok "LLM configuration added to .env"
fi

# --- LLM Summary ---
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  LLM CONFIGURATION SUMMARY                      ║${NC}"
echo -e "${BOLD}╠──────────────────────────────────────────────────╣${NC}"
printf "${BOLD}║${NC}  Level 1 (User-facing):  ${CYAN}%-24s${NC}${BOLD}║${NC}\n" "$LLM_PROVIDER / $LLM_MODEL"
printf "${BOLD}║${NC}  Level 2 (Backend):      ${CYAN}%-24s${NC}${BOLD}║${NC}\n" "$LLM_BACKEND_PROVIDER / $LLM_BACKEND_MODEL"
printf "${BOLD}║${NC}  Resume tailoring:       %-24s${BOLD}║${NC}\n" "$LLM_RESUME_TAILORING"
printf "${BOLD}║${NC}  Cover letters:          %-24s${BOLD}║${NC}\n" "$LLM_COVER_LETTERS"
printf "${BOLD}║${NC}  Smart form answers:     %-24s${BOLD}║${NC}\n" "$LLM_SMART_ANSWERS"
printf "${BOLD}║${NC}  Monthly spend limit:    %-24s${BOLD}║${NC}\n" "\$${LLM_MONTHLY_LIMIT}"
echo -e "${BOLD}╠──────────────────────────────────────────────────╣${NC}"
echo -e "${BOLD}║${NC}  ${GREEN}API Keys saved to .env${NC}                          ${BOLD}║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 10: Verify ─────────────────────────────────────────────────────────
log_step 10 "Verifying setup..."

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

# ── Post-Setup Status Dashboard ──────────────────────────────────────────────
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

# LLM SDKs
if [[ -f "$ENV_FILE" ]]; then
  L1_PROV=$(grep "^LLM_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
  L2_PROV=$(grep "^LLM_BACKEND_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
fi
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
env_check "SUPABASE_SERVICE_ROLE_KEY" "Supabase Service Key  (required)"
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
  print_todo "(required) Clone the AutoApply repo (private — ask admin for access)"
fi

if [[ "$LLM_PROVIDER" == "none" && "$LLM_BACKEND_PROVIDER" == "none" ]]; then
  print_todo "(required) Configure LLM provider — re-run setup or edit .env"
elif [[ -f "$ENV_FILE" ]]; then
  if [[ "$LLM_PROVIDER" == "anthropic" || "$LLM_BACKEND_PROVIDER" == "anthropic" ]] && ! grep -q "^ANTHROPIC_API_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
    print_todo "(required) Add Anthropic API key to .env (console.anthropic.com)"
  fi
  if [[ "$LLM_PROVIDER" == "openai" || "$LLM_BACKEND_PROVIDER" == "openai" ]] && ! grep -q "^OPENAI_API_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
    print_todo "(required) Add OpenAI API key to .env (platform.openai.com)"
  fi
fi

print_todo "(required) Log in at https://autoapply-web.vercel.app and complete onboarding"
print_todo "(required) Start the worker: cd packages/worker && $PYTHON_CMD worker.py"

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^STRIPE_SECRET_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
  print_todo "(optional) Set up Stripe billing keys in .env"
fi

if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^GOOGLE_CLIENT_ID=.\+" "$ENV_FILE" 2>/dev/null; then
  print_todo "(optional) Set up Google OAuth for Gmail connect"
fi

if [[ $TODO_COUNT -eq 0 ]]; then
  echo -e "  ${GREEN}Nothing! You're all set.${NC}"
fi

echo ""
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Run this status check anytime: ${CYAN}bash ~/autoapply/status.sh${NC}"
echo ""
