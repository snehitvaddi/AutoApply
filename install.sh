#!/usr/bin/env bash
# ApplyLoop installer — curl-able, local-build, no Gatekeeper pain.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh | bash
#
# Env vars (all optional):
#   APPLYLOOP_CODE    activation code AL-XXXX-XXXX (REQUIRED — gate, can also be
#                     passed as positional arg: `bash -s -- AL-XXXX-XXXX`, or
#                     prompted interactively from /dev/tty if neither)
#   APPLYLOOP_HOME    install dir (default $HOME/.applyloop)
#   APPLYLOOP_REPO    git URL or local path (default https://github.com/snehitvaddi/AutoApply.git)
#   APPLYLOOP_BRANCH  branch to clone/update (default main)
#   APPLYLOOP_APP     .app bundle path (default /Applications/ApplyLoop.app — passed through to build_local_app.sh)
#   APPLYLOOP_APP_URL cloud API URL (default https://applyloop.vercel.app)
#
# Optional integration keys (all skippable with empty Enter):
#   APPLYLOOP_TELEGRAM_CHAT_ID
#   APPLYLOOP_AGENTMAIL_KEY
#   APPLYLOOP_FINETUNE_RESUME_KEY
#   APPLYLOOP_GMAIL_EMAIL + APPLYLOOP_GMAIL_APP_PASSWORD
#   APPLYLOOP_SKIP_PROMPTS=1   skips ALL optional prompts (for non-interactive installs)

# ------------------------------------------------------------------ self-reexec
#
# When invoked via `curl | bash`, child processes can consume the rest of
# our script from stdin and corrupt the install. The known offender:
# `brew install python@3.11` runs `python3.11 -Im pip install -v -` as
# part of bottle setup, where the trailing `-` means pip reads from
# stdin. Pip inherits stdin from bash, which is the curl pipe — so pip
# eats the remainder of install.sh trying to parse it as a requirements
# file. After that bash has nothing left to execute and the install dies
# halfway through.
#
# Fix: detect we're being piped (stdin is not a tty) and re-fetch the
# script to a tmpfile, then re-exec with stdin=/dev/null. The APPLYLOOP_REEXEC
# env var breaks the loop on the second pass. Pujith hit this on his
# Mac during v1.0.8.
if [[ -z "${APPLYLOOP_REEXEC:-}" ]] && [[ ! -t 0 ]]; then
  REEXEC_URL="${APPLYLOOP_INSTALL_URL:-https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh}"
  REEXEC_TMP="$(mktemp -t applyloop-install.XXXXXX)" || REEXEC_TMP="/tmp/applyloop-install.$$.sh"
  if curl -fsSL "$REEXEC_URL" -o "$REEXEC_TMP" 2>/dev/null && [[ -s "$REEXEC_TMP" ]]; then
    chmod +x "$REEXEC_TMP"
    # CRITICAL: pass "$@" through. When the user invokes us via
    # `curl | bash -s -- AL-X1Y2-Z3W4`, the activation code is in $1
    # of the ORIGINAL bash process. Without "$@" on the exec line, the
    # re-exec'd tmpfile starts with no positional args and falls through
    # to the interactive prompt, re-asking for a code the user already
    # provided. Env vars (APPLYLOOP_CODE) are inherited automatically
    # across exec — this fix is specifically for the positional-arg path.
    APPLYLOOP_REEXEC=1 exec bash "$REEXEC_TMP" "$@" </dev/null
  fi
  echo "WARNING: could not re-fetch install.sh for safe re-exec. If the install dies after 'Installing python@3.11', re-run as: curl -fsSL $REEXEC_URL -o /tmp/applyloop-install.sh && bash /tmp/applyloop-install.sh -- $*" >&2
fi

set -euo pipefail

APPLYLOOP_HOME="${APPLYLOOP_HOME:-$HOME/.applyloop}"
REPO_URL="${APPLYLOOP_REPO:-https://github.com/snehitvaddi/AutoApply.git}"
BRANCH="${APPLYLOOP_BRANCH:-main}"

# Pin npm's download cache to a directory inside $APPLYLOOP_HOME so we
# don't inherit a global /tmp/npm-cache or ~/.npm that may have
# root-owned files from a prior sudo install. Same isolation principle
# as the Python venv: nothing in the install touches state we don't own.
# Pujith hit `EACCES /tmp/npm-cache` on v1.0.8 — this is the fix.
#
# NOTE: the actual `export NPM_CONFIG_CACHE=...` is deferred until AFTER
# the git clone, because ANY npm-invoking subprocess inheriting this env
# var (brew's openclaw install, `openclaw gateway start`) will lazily
# create the directory before git clone has had a chance to run — and
# `git clone --depth 1` refuses to write into a non-empty directory.
# We just declare the path here; the export lands further down.
NPM_CONFIG_CACHE_PATH="$APPLYLOOP_HOME/.npm-cache"

# Colors for the summary (fall back to no-op on dumb terminals)
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_GREEN=$'\033[32m'
  C_BLUE=$'\033[34m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
  C_RESET=""; C_BOLD=""; C_GREEN=""; C_BLUE=""; C_YELLOW=""; C_RED=""
fi

log()  { echo "${C_BLUE}[install]${C_RESET} $*"; }
warn() { echo "${C_YELLOW}[install]${C_RESET} $*"; }
die()  { echo "${C_RED}[install] ERROR:${C_RESET} $*" >&2; exit 1; }

# ------------------------------------------------------------------ guards

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "Only macOS is supported right now. Linux/Windows: ping vsneh."
fi

ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
  BREW_PREFIX_DEFAULT="/opt/homebrew"
else
  BREW_PREFIX_DEFAULT="/usr/local"
fi

APP_URL="${APPLYLOOP_APP_URL:-https://applyloop.vercel.app}"

# ------------------------------------------------------------------ Phase A: activation gate
#
# Before touching the machine, require a valid activation code and redeem
# it via POST /api/activate. We get back the worker_token + full profile +
# preferences + resumes + telegram_chat_id in one round trip. Without a
# valid code, we refuse to install anything — protecting the system from
# unauthorized installs (same pattern as the old ApplyLoop-Setup-Mac.sh).
#
# Code sources, in order of preference:
#   1. $APPLYLOOP_CODE env var
#   2. Positional arg ($1)
#   3. Interactive /dev/tty prompt
#
# Skippable with $APPLYLOOP_SKIP_ACTIVATION=1 — only for CI / dev-loop.
# Normal users must pass a valid code.

WORKER_TOKEN=""
ACTIVATION_USER_ID=""
ACTIVATION_EMAIL=""
ACTIVATION_NAME=""
ACTIVATION_PROFILE_JSON=""  # full JSON blob for later profile.json write
ACTIVATION_TELEGRAM_CHAT_ID=""

if [[ -n "${APPLYLOOP_SKIP_ACTIVATION:-}" ]]; then
  warn "APPLYLOOP_SKIP_ACTIVATION set — running install WITHOUT a code gate (dev mode)"
else
  CODE="${APPLYLOOP_CODE:-${1:-}}"

  if [[ -z "$CODE" ]]; then
    if [[ ! -t 0 ]] && [[ ! -r /dev/tty ]]; then
      die "Activation code required. Set APPLYLOOP_CODE or pass as arg: bash -s -- AL-XXXX-XXXX"
    fi
    echo ""
    echo "${C_BOLD}Before we begin, paste your activation code.${C_RESET}"
    echo "${C_BLUE}  (Get this from applyloop.vercel.app after admin approval.)${C_RESET}"
    echo ""
    read -r -p "  Activation code (AL-XXXX-XXXX): " CODE < /dev/tty || true
    echo ""
  fi

  # Normalize: uppercase, strip whitespace.
  CODE="$(echo "$CODE" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')"

  if [[ -z "$CODE" ]]; then
    die "No activation code entered. Setup cannot continue without a valid code."
  fi

  if [[ ! "$CODE" =~ ^AL-[A-Z0-9]{4}-[A-Z0-9]{4}$ ]]; then
    die "Invalid code format: '$CODE'. Expected AL-XXXX-XXXX."
  fi

  log "Validating activation code against $APP_URL..."

  # POST /api/activate with the code. Response shape (apiSuccess wraps data):
  #   { data: { worker_token, user_id, email, full_name, tier,
  #             telegram_chat_id, profile, preferences, default_resume, ... },
  #     success: true }
  # On failure: { success: false, error: { name, message, details: { code } } }
  ACTIVATION_TMP="$(mktemp -t applyloop-activation.XXXXXX)"
  HTTP_CODE="$(curl -sS -o "$ACTIVATION_TMP" -w "%{http_code}" \
    -X POST "$APP_URL/api/activate" \
    -H "Content-Type: application/json" \
    --data-raw "{\"code\":\"$CODE\",\"install_id\":\"$(uname -n)\",\"app_version\":\"install.sh\"}" \
    2>/dev/null || echo "000")"

  if [[ "$HTTP_CODE" != "200" ]]; then
    ERR_MSG="$(cat "$ACTIVATION_TMP" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    err = d.get('error', {})
    details = err.get('details', {}) or {}
    print(f\"{err.get('message', 'unknown error')} [{details.get('code', 'unknown')}]\")
except Exception:
    print('could not parse error response')
" 2>/dev/null || echo 'unknown error')"
    rm -f "$ACTIVATION_TMP"
    die "Activation failed (HTTP $HTTP_CODE): $ERR_MSG
    Possible causes:
      1. Code was mistyped — check for extra spaces or wrong characters
      2. Code was revoked or expired
      3. Code was already used up (uses_remaining = 0)
      4. Your account is not yet approved — contact the admin"
  fi

  # Parse the response with python (always available — /usr/bin/python3 is fine
  # at this point, we haven't installed brew's python@3.11 yet). We extract the
  # worker_token + profile fields we need for later phases.
  ACTIVATION_VARS="$(python3 -c "
import sys, json
try:
    raw = open('$ACTIVATION_TMP').read()
    d = json.loads(raw).get('data', {}) or {}
    tok = d.get('worker_token', '')
    uid = d.get('user_id', '')
    em  = d.get('email', '') or ''
    nm  = d.get('full_name', '') or ''
    tg  = d.get('telegram_chat_id', '') or ''
    if not tok:
        print('NO_TOKEN', file=sys.stderr)
        sys.exit(1)
    # Print KEY=VALUE lines for bash eval. Use tab as separator to avoid
    # embedded-newline nightmares.
    print(f'TOK={tok}')
    print(f'UID={uid}')
    print(f'EMAIL={em}')
    print(f'NAME={nm}')
    print(f'TG_CHAT_ID={tg}')
except Exception as e:
    print(f'PARSE_ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)"

  if [[ "$?" -ne 0 ]]; then
    rm -f "$ACTIVATION_TMP"
    die "Activation succeeded but response parse failed: $ACTIVATION_VARS"
  fi

  # Eval the KEY=VALUE lines into bash vars. Prefixed with ACT_ to namespace.
  while IFS='=' read -r key val; do
    case "$key" in
      TOK)        WORKER_TOKEN="$val" ;;
      UID)        ACTIVATION_USER_ID="$val" ;;
      EMAIL)      ACTIVATION_EMAIL="$val" ;;
      NAME)       ACTIVATION_NAME="$val" ;;
      TG_CHAT_ID) ACTIVATION_TELEGRAM_CHAT_ID="$val" ;;
    esac
  done <<< "$ACTIVATION_VARS"

  # Keep the full JSON blob around for Phase C (profile.json transform)
  ACTIVATION_PROFILE_JSON="$(cat "$ACTIVATION_TMP")"
  rm -f "$ACTIVATION_TMP"

  if [[ -z "$WORKER_TOKEN" ]]; then
    die "Activation succeeded but no worker_token in response — contact admin"
  fi

  log "${C_GREEN}Code verified${C_RESET} for ${C_BOLD}${ACTIVATION_NAME:-$ACTIVATION_EMAIL}${C_RESET} (user $ACTIVATION_USER_ID)"
fi

# ------------------------------------------------------------------ brew bootstrap

ensure_brew() {
  if command -v brew >/dev/null 2>&1; then
    log "brew already installed ($(brew --prefix))"
  else
    log "Installing Homebrew (Apple's official installer — may prompt for sudo)"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  # Source brew's shellenv so subsequent `brew` calls in this script work
  # even when brew was JUST installed and isn't on PATH yet.
  if [[ -x "$BREW_PREFIX_DEFAULT/bin/brew" ]]; then
    eval "$("$BREW_PREFIX_DEFAULT/bin/brew" shellenv)"
  elif command -v brew >/dev/null 2>&1; then
    eval "$(brew shellenv)"
  else
    die "brew install completed but 'brew' not found on PATH — check the output above."
  fi
}

ensure_python_311() {
  if brew list --versions python@3.11 >/dev/null 2>&1; then
    log "python@3.11 already installed"
  else
    log "Installing python@3.11"
    # </dev/null protects against the pip-stdin bug — see self-reexec block
    brew install python@3.11 </dev/null
  fi
}

ensure_node() {
  if brew list --versions node >/dev/null 2>&1; then
    log "node already installed"
  else
    log "Installing node"
    brew install node </dev/null
  fi
}

ensure_git() {
  if brew list --versions git >/dev/null 2>&1; then
    log "git already installed (brew)"
  elif command -v git >/dev/null 2>&1; then
    log "git already available on PATH — skipping brew install"
  else
    log "Installing git"
    brew install git </dev/null
  fi
}

ensure_claude() {
  if command -v claude >/dev/null 2>&1; then
    log "claude already installed"
  elif brew list --versions claude >/dev/null 2>&1; then
    log "claude already installed (brew)"
  else
    log "Installing claude"
    brew install claude </dev/null || warn "brew install claude failed — the in-app wizard will retry later"
  fi
}

ensure_openclaw() {
  local NPM
  NPM="$(brew --prefix node)/bin/npm"
  if [[ ! -x "$NPM" ]]; then
    NPM="$(command -v npm || true)"
  fi
  if [[ -z "$NPM" ]]; then
    warn "npm not found — skipping openclaw (in-app wizard will retry later)"
    return 0
  fi
  if "$NPM" ls -g --depth=0 openclaw >/dev/null 2>&1; then
    log "openclaw already installed (npm global)"
  else
    log "Installing openclaw via $NPM"
    # NOTE: we deliberately DO NOT pass --cache here. $NPM_CONFIG_CACHE
    # isn't exported yet at this point (it's deferred until after git
    # clone to avoid the non-empty-clone-destination bug). We let npm
    # use its default global cache for this one-time install; the UI
    # `npm install` later WILL use the isolated cache.
    "$NPM" install -g openclaw --no-fund --no-audit \
      || warn "npm install -g openclaw failed — wizard will retry later"
  fi

  # OpenClaw is open source — no Pro tier, no subscription. The "gateway"
  # is just a local WebSocket daemon registered as a user-scope launchd
  # service. We also write ~/.openclaw/openclaw.json directly via heredoc
  # (the old `openclaw config` interactive wizard hangs — commit 53432b7).
  # Minimal config: gateway + browser profile only. NO auth profile, NO
  # model providers — the worker calls `openclaw browser ...` for DOM
  # actions and sends snapshots to Claude Code (Layer 1) for the LLM calls.
  # OpenClaw never talks to an LLM directly.
  if command -v openclaw >/dev/null 2>&1; then
    OC_DIR="$HOME/.openclaw"
    OC_CONFIG="$OC_DIR/openclaw.json"

    mkdir -p "$OC_DIR/workspace" "$OC_DIR/agents/main/sessions"

    if [[ ! -f "$OC_CONFIG" ]]; then
      log "Writing $OC_CONFIG (minimal — gateway + browser profile only)"
      GW_TOKEN="$(openssl rand -hex 24)"
      NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      cat > "$OC_CONFIG" <<OCEOF
{
  "meta": {
    "lastTouchedVersion": "2026.4.11",
    "lastTouchedAt": "${NOW_ISO}"
  },
  "wizard": {
    "lastRunAt": "${NOW_ISO}",
    "lastRunMode": "local",
    "lastRunCommand": "applyloop-install"
  },
  "browser": {
    "defaultProfile": "openclaw",
    "profiles": {
      "openclaw": {
        "cdpPort": 18800,
        "color": "#0066CC"
      }
    }
  },
  "gateway": {
    "port": 18789,
    "mode": "local",
    "bind": "loopback",
    "auth": {
      "mode": "token",
      "token": "${GW_TOKEN}"
    }
  },
  "commands": {
    "native": "auto",
    "nativeSkills": "auto"
  }
}
OCEOF
    else
      log "~/.openclaw/openclaw.json already exists — leaving it alone"
    fi

    log "Registering openclaw gateway launchd service"
    openclaw gateway install >/dev/null 2>&1 || warn "openclaw gateway install failed — worker will spawn one on demand"
    openclaw gateway start   >/dev/null 2>&1 || true
  fi
}

# ------------------------------------------------------------------ run bootstrap

ensure_brew
ensure_python_311
ensure_node
ensure_git
ensure_claude
ensure_openclaw

# ------------------------------------------------------------------ clone / update

mkdir -p "$(dirname "$APPLYLOOP_HOME")"

if [[ -d "$APPLYLOOP_HOME/.git" ]]; then
  log "Existing install found at $APPLYLOOP_HOME — fetching latest from $BRANCH"
  git -C "$APPLYLOOP_HOME" fetch origin "$BRANCH"
  git -C "$APPLYLOOP_HOME" reset --hard "origin/$BRANCH"
else
  log "Cloning $REPO_URL (branch=$BRANCH) → $APPLYLOOP_HOME"
  # git clone of a local path or a remote URL both work with --depth 1
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APPLYLOOP_HOME"
fi

# ------------------------------------------------------------------ python venv + deps

PY="$(brew --prefix python@3.11)/bin/python3.11"
if [[ ! -x "$PY" ]]; then
  die "python3.11 not found at $PY — brew install python@3.11 may have failed."
fi

if [[ ! -x "$APPLYLOOP_HOME/venv/bin/python3" ]]; then
  log "Creating venv at $APPLYLOOP_HOME/venv with $PY"
  "$PY" -m venv "$APPLYLOOP_HOME/venv"
else
  log "Reusing existing venv at $APPLYLOOP_HOME/venv"
fi

log "Upgrading pip"
"$APPLYLOOP_HOME/venv/bin/pip" install --quiet --upgrade pip

# Single-pass install of BOTH requirements files so pip resolves the full
# graph in one shot. If desktop + worker ever conflict, pip fails loudly.
log "Installing desktop + worker python deps (single pip resolver pass)"
"$APPLYLOOP_HOME/venv/bin/pip" install \
  -r "$APPLYLOOP_HOME/packages/desktop/requirements.txt" \
  -r "$APPLYLOOP_HOME/packages/worker/requirements.txt"

# ------------------------------------------------------------------ static UI build

log "Building static Next.js UI export (npm install + npm run build)"
# Now safe to export + create the npm cache dir — git clone has finished.
export NPM_CONFIG_CACHE="$NPM_CONFIG_CACHE_PATH"
mkdir -p "$NPM_CONFIG_CACHE"
(
  cd "$APPLYLOOP_HOME/packages/desktop/ui"
  # Invoke brew's npm explicitly so NVM/asdf/system node can't interfere.
  # NPM_CONFIG_CACHE is exported above so npm uses our isolated cache,
  # not whatever the user had configured globally.
  NPM_BIN="$(brew --prefix node)/bin/npm"
  if [[ ! -x "$NPM_BIN" ]]; then NPM_BIN="npm"; fi
  "$NPM_BIN" install --cache "$NPM_CONFIG_CACHE" --no-fund --no-audit
  "$NPM_BIN" run build
)

# ------------------------------------------------------------------ Phase C: cloud config fetch + profile.json
#
# Call GET /api/settings/cli-config with the worker_token from Phase A.
# We already have profile/preferences/resumes from /api/activate, but
# cli-config also returns telegram_bot_token (admin's global bot) and
# supabase_url/anon_key which /api/activate doesn't. Two calls, one .env.

TELEGRAM_BOT_TOKEN_VAL=""
SUPABASE_URL_VAL=""
SUPABASE_ANON_KEY_VAL=""
CLI_CONFIG_JSON=""

if [[ -n "$WORKER_TOKEN" ]]; then
  log "Fetching cli-config (telegram bot token + supabase creds)..."
  CFG_TMP="$(mktemp -t applyloop-cliconfig.XXXXXX)"
  CFG_HTTP="$(curl -sS -o "$CFG_TMP" -w "%{http_code}" \
    -H "X-Worker-Token: $WORKER_TOKEN" \
    "$APP_URL/api/settings/cli-config" 2>/dev/null || echo "000")"
  if [[ "$CFG_HTTP" == "200" ]]; then
    CLI_CONFIG_JSON="$(cat "$CFG_TMP")"
    CFG_VARS="$(python3 -c "
import sys, json
try:
    d = json.loads(open('$CFG_TMP').read()).get('data', {}) or {}
    print(f'TG_BOT={d.get(\"telegram_bot_token\") or \"\"}')
    print(f'SB_URL={d.get(\"supabase_url\") or \"\"}')
    print(f'SB_ANON={d.get(\"supabase_anon_key\") or \"\"}')
    # If cli-config has a chat_id and Phase A didn't, use it
    print(f'TG_CHAT={d.get(\"telegram_chat_id\") or \"\"}')
except Exception as e:
    print(f'ERR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)"
    while IFS='=' read -r key val; do
      case "$key" in
        TG_BOT)  TELEGRAM_BOT_TOKEN_VAL="$val" ;;
        SB_URL)  SUPABASE_URL_VAL="$val" ;;
        SB_ANON) SUPABASE_ANON_KEY_VAL="$val" ;;
        TG_CHAT)
          if [[ -z "$ACTIVATION_TELEGRAM_CHAT_ID" && -n "$val" ]]; then
            ACTIVATION_TELEGRAM_CHAT_ID="$val"
          fi
          ;;
      esac
    done <<< "$CFG_VARS"
  else
    warn "cli-config fetch failed (HTTP $CFG_HTTP) — Telegram + Supabase config will be empty"
  fi
  rm -f "$CFG_TMP"
fi

# Transform the /api/activate response into the nested profile.json shape
# that Claude Code / the worker expects. Same structure the old script
# used (ApplyLoop-Setup-Mac.sh:746-790).
if [[ -n "$ACTIVATION_PROFILE_JSON" ]]; then
  log "Writing $APPLYLOOP_HOME/profile.json"
  echo "$ACTIVATION_PROFILE_JSON" | python3 -c "
import sys, json, os
raw = sys.stdin.read()
d = json.loads(raw).get('data', {}) or {}
p = d.get('profile') or {}
prefs = d.get('preferences') or {}
profile = {
  'user': {
    'id': d.get('user_id', ''),
    'email': d.get('email', '') or '',
    'full_name': d.get('full_name', '') or '',
    'tier': d.get('tier', '') or '',
  },
  'personal': {
    'first_name': p.get('first_name', '') or '',
    'last_name': p.get('last_name', '') or '',
    'email': d.get('email', '') or '',
    'phone': p.get('phone', '') or '',
    'linkedin_url': p.get('linkedin_url', '') or '',
    'github_url': p.get('github_url', '') or '',
    'portfolio_url': p.get('portfolio_url', '') or '',
  },
  'work': {
    'current_company': p.get('current_company', '') or '',
    'current_title': p.get('current_title', '') or '',
    'years_experience': p.get('years_experience', '') or '',
  },
  'legal': {
    'work_authorization': p.get('work_authorization', '') or '',
    'requires_sponsorship': p.get('requires_sponsorship', False),
  },
  'eeo': {
    'gender': p.get('gender', '') or '',
    'race_ethnicity': p.get('race_ethnicity', '') or '',
    'veteran_status': p.get('veteran_status', '') or '',
    'disability_status': p.get('disability_status', '') or '',
  },
  'experience': p.get('work_experience') or [],
  'education': p.get('education') or [],
  'education_summary': {
    'education_level': p.get('education_level', '') or '',
    'school_name': p.get('school_name', '') or '',
    'degree': p.get('degree', '') or '',
    'graduation_year': p.get('graduation_year', '') or '',
  },
  'skills': p.get('skills') or [],
  'standard_answers': p.get('answer_key_json') or {},
  'cover_letter_template': p.get('cover_letter_template', '') or '',
  'preferences': prefs,
  'resumes': [d.get('default_resume')] if d.get('default_resume') else [],
}
os.makedirs('$APPLYLOOP_HOME', exist_ok=True)
with open('$APPLYLOOP_HOME/profile.json', 'w') as f:
    json.dump(profile, f, indent=2)
print(f'  wrote {len(profile[\"experience\"])} experience(s), {len(profile[\"education\"])} education(s), {len(profile[\"skills\"])} skill(s)')
" || warn "profile.json transform failed"
fi

# Persist the worker token to disk where the desktop wizard expects it.
# This makes the wizard's activation check pass immediately on first
# launch — the user doesn't need to paste the code a second time.
TOKEN_FILE="$HOME/.autoapply/workspace/.api-token"
if [[ -n "$WORKER_TOKEN" ]]; then
  mkdir -p "$HOME/.autoapply/workspace"
  echo -n "$WORKER_TOKEN" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE" 2>/dev/null || true
  log "Worker token saved to $TOKEN_FILE"
fi

# ------------------------------------------------------------------ Phase D: interactive optional prompts
#
# Prompts for optional integrations. Empty-Enter = skip. Env vars
# override the prompt entirely. Set APPLYLOOP_SKIP_PROMPTS=1 to skip
# ALL prompts (CI / unattended installs).

AGENTMAIL_KEY_VAL="${APPLYLOOP_AGENTMAIL_KEY:-}"
FINETUNE_KEY_VAL="${APPLYLOOP_FINETUNE_RESUME_KEY:-}"
GMAIL_EMAIL_VAL="${APPLYLOOP_GMAIL_EMAIL:-}"
GMAIL_APP_PW_VAL="${APPLYLOOP_GMAIL_APP_PASSWORD:-}"

if [[ -n "${APPLYLOOP_SKIP_PROMPTS:-}" ]] || [[ ! -r /dev/tty ]]; then
  log "Skipping interactive prompts (APPLYLOOP_SKIP_PROMPTS or no TTY)"
  # Still accept env overrides for telegram
  if [[ -z "$ACTIVATION_TELEGRAM_CHAT_ID" && -n "${APPLYLOOP_TELEGRAM_CHAT_ID:-}" ]]; then
    ACTIVATION_TELEGRAM_CHAT_ID="$APPLYLOOP_TELEGRAM_CHAT_ID"
  fi
else
  echo ""
  echo "${C_BOLD}Optional integrations${C_RESET} — press Enter to skip any field."
  echo ""

  # 1) Telegram chat ID (skip if already in profile)
  if [[ -z "$ACTIVATION_TELEGRAM_CHAT_ID" ]] && [[ -z "${APPLYLOOP_TELEGRAM_CHAT_ID:-}" ]]; then
    echo "${C_BOLD}  Telegram notifications${C_RESET}"
    echo "    1. Open Telegram, find @ApplyLoopBot"
    echo "    2. Send /start to the bot"
    echo "    3. Bot replies with your Chat ID"
    echo "    4. Paste the number below (or Enter to skip)"
    read -r -p "  Telegram Chat ID: " ACTIVATION_TELEGRAM_CHAT_ID < /dev/tty || true
    echo ""
  elif [[ -z "$ACTIVATION_TELEGRAM_CHAT_ID" && -n "${APPLYLOOP_TELEGRAM_CHAT_ID:-}" ]]; then
    ACTIVATION_TELEGRAM_CHAT_ID="$APPLYLOOP_TELEGRAM_CHAT_ID"
  fi

  # 2) AgentMail (disposable inboxes)
  if [[ -z "$AGENTMAIL_KEY_VAL" ]]; then
    echo "${C_BOLD}  AgentMail${C_RESET} — disposable email inboxes for job verification"
    echo "    Sign up at https://agentmail.to/dashboard and copy your API key."
    read -r -p "  AgentMail API key (Enter to skip): " AGENTMAIL_KEY_VAL < /dev/tty || true
    if [[ -n "$AGENTMAIL_KEY_VAL" ]]; then
      log "  Verifying AgentMail key..."
      AM_HTTP="$(curl -sS -o /dev/null -w "%{http_code}" \
        "https://api.agentmail.to/v0/inboxes" \
        -H "Authorization: Bearer $AGENTMAIL_KEY_VAL" 2>/dev/null || echo "000")"
      if [[ "$AM_HTTP" == "200" ]]; then
        log "  ${C_GREEN}AgentMail key verified${C_RESET}"
      else
        warn "  AgentMail key returned HTTP $AM_HTTP — saving anyway, fix in ~/.applyloop/.env later"
      fi
    fi
    echo ""
  fi

  # 3) Finetune Resume (per-job tailored resume generation)
  if [[ -z "$FINETUNE_KEY_VAL" ]]; then
    echo "${C_BOLD}  Finetune Resume${C_RESET} — per-job tailored resume generation"
    echo "    The service already has your base resume from signup; it returns a"
    echo "    tailored PDF when you send a job description + API key."
    read -r -p "  Finetune Resume API key (Enter to skip): " FINETUNE_KEY_VAL < /dev/tty || true
    echo ""
  fi

  # 4) Gmail + Himalaya (email verification codes)
  if [[ -z "$GMAIL_EMAIL_VAL" && -z "$GMAIL_APP_PW_VAL" ]]; then
    echo "${C_BOLD}  Gmail email verification (optional — skip with Enter)${C_RESET}"
    echo "    Used to read 6-digit confirmation codes from job applications."
    echo "    Requires: 2FA enabled + App Password from"
    echo "    https://myaccount.google.com/apppasswords"
    read -r -p "  Gmail address (Enter to skip): " GMAIL_EMAIL_VAL < /dev/tty || true
    if [[ -n "$GMAIL_EMAIL_VAL" ]]; then
      read -r -p "  Gmail app password (16 chars, spaces OK): " GMAIL_APP_PW_VAL < /dev/tty || true
      # Strip spaces (Google displays as "abcd efgh ijkl mnop")
      GMAIL_APP_PW_VAL="$(echo "$GMAIL_APP_PW_VAL" | tr -d ' ')"
    fi
    echo ""
  fi
fi

# ------------------------------------------------------------------ Phase D: write ~/.applyloop/.env
#
# The launcher script sources this file before exec'ing python, so
# every env var here is visible to the desktop server + worker subprocess
# + claude CLI + openclaw CLI. Worker code reads from os.environ —
# no python-side changes needed.

ENV_FILE="$APPLYLOOP_HOME/.env"
ENCRYPTION_KEY_VAL="$(openssl rand -hex 32)"
WORKER_ID_VAL="worker-$(hostname -s | tr '[:upper:]' '[:lower:]')-${RANDOM}"

log "Writing $ENV_FILE"
cat > "$ENV_FILE" <<ENVEOF
# ApplyLoop runtime config — generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Sourced by Contents/MacOS/launcher before exec'ing python.
# Edit carefully. To regenerate: rerun install.sh.

# ── Auth (REQUIRED) ────────────────────────────────────────────────
WORKER_TOKEN=${WORKER_TOKEN}

# ── App ────────────────────────────────────────────────────────────
NEXT_PUBLIC_APP_URL=${APP_URL}
APPLYLOOP_HOME=${APPLYLOOP_HOME}
ENCRYPTION_KEY=${ENCRYPTION_KEY_VAL}

# ── Supabase (shared admin instance; RLS + worker proxy enforce isolation) ─
NEXT_PUBLIC_SUPABASE_URL=${SUPABASE_URL_VAL}
NEXT_PUBLIC_SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY_VAL}
SUPABASE_URL=${SUPABASE_URL_VAL}
SUPABASE_SERVICE_KEY=${SUPABASE_ANON_KEY_VAL}

# ── Worker tuning ──────────────────────────────────────────────────
WORKER_ID=${WORKER_ID_VAL}
POLL_INTERVAL=10
APPLY_COOLDOWN=30
RESUME_DIR=${HOME}/.autoapply/workspace/resumes
SCREENSHOT_DIR=${HOME}/.autoapply/workspace/screenshots

# ── Telegram (notifications — empty = disabled) ───────────────────
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN_VAL}
TELEGRAM_CHAT_ID=${ACTIVATION_TELEGRAM_CHAT_ID}

# ── Optional integrations ──────────────────────────────────────────
AGENTMAIL_API_KEY=${AGENTMAIL_KEY_VAL}
FINETUNE_RESUME_API_KEY=${FINETUNE_KEY_VAL}
GMAIL_EMAIL=${GMAIL_EMAIL_VAL}
GMAIL_APP_PASSWORD=${GMAIL_APP_PW_VAL}
ENVEOF
chmod 600 "$ENV_FILE" 2>/dev/null || true

# Also create the worker's runtime dirs so it doesn't crash on first write
mkdir -p "$HOME/.autoapply/workspace/resumes" "$HOME/.autoapply/workspace/screenshots"

# ------------------------------------------------------------------ Phase E: ~/.applyloop/AGENTS.md
#
# Claude Code reads this on its first PTY session spawn (per the updated
# pty_terminal.py prompt). It describes the local install layout + what
# integrations are configured + critical rules.

AGENTS_FILE="$APPLYLOOP_HOME/AGENTS.md"
log "Writing $AGENTS_FILE"

_has_telegram="no"
[[ -n "$ACTIVATION_TELEGRAM_CHAT_ID" && -n "$TELEGRAM_BOT_TOKEN_VAL" ]] && _has_telegram="yes ($ACTIVATION_TELEGRAM_CHAT_ID)"
_has_agentmail="no"
[[ -n "$AGENTMAIL_KEY_VAL" ]] && _has_agentmail="yes"
_has_finetune="no"
[[ -n "$FINETUNE_KEY_VAL" ]] && _has_finetune="yes"
_has_gmail="no"
[[ -n "$GMAIL_EMAIL_VAL" ]] && _has_gmail="yes ($GMAIL_EMAIL_VAL)"

cat > "$AGENTS_FILE" <<AGENTSEOF
# ApplyLoop — Agent Context

You are the ApplyLoop job application agent. ApplyLoop is an automated
job application engine that runs locally on this Mac.

## System info

- **Install directory**: \`$APPLYLOOP_HOME\`
- **Python venv**: \`$APPLYLOOP_HOME/venv/bin/python3\`
- **Profile**: \`$APPLYLOOP_HOME/profile.json\` — read this FIRST (the user you're applying for)
- **Playbook**: \`$APPLYLOOP_HOME/packages/worker/SOUL.md\` — the full scout→apply rules
- **Worker code**: \`$APPLYLOOP_HOME/packages/worker/worker.py\`
- **Config env**: \`$APPLYLOOP_HOME/.env\` — sourced by launcher (worker inherits it)
- **Desktop log**: \`$HOME/.autoapply/desktop.log\`
- **User**: ${ACTIVATION_NAME:-$ACTIVATION_EMAIL}
- **User email**: ${ACTIVATION_EMAIL}

## Your role

1. **Read \`profile.json\` first.** That's the user you're applying for — every field (experience, education, skills, answer_key_json, preferences) is the source of truth for form-filling.
2. **Read \`SOUL.md\`** for the full playbook: scanning strategy, filters, form-filling rules, rate limits, Telegram notifications, critical do-nots.
3. **Greet the user by name** (\`$ACTIVATION_NAME\`) ONCE, explain your capabilities, then WAIT for commands. DO NOT auto-start the loop.
4. On "start" or "scout": \`cd $APPLYLOOP_HOME/packages/worker && python3 worker.py\`. Relay worker output to the user in plain English.
5. On "status": show profile summary + last scout/apply stats + configured services (below).
6. On "apply to [URL]": run the applier directly on that URL.
7. On "stop": kill the worker subprocess.

## Configured services

- **Telegram notifications**: ${_has_telegram}
- **AgentMail** (disposable inboxes): ${_has_agentmail}
- **Finetune Resume** (per-job tailored PDFs): ${_has_finetune}
- **Gmail + Himalaya** (email verification codes): ${_has_gmail}

## Critical rules

- NEVER run the worker without \`profile.json\` loaded.
- NEVER apply to a company more than 5 times per 15 days.
- NEVER skip required form fields.
- ALWAYS screenshot after submission + Telegram notify (if configured).
- If OpenClaw gateway crashes: \`openclaw gateway restart\` and continue.
- If you hit a Claude Code rate limit or auth error: **pause the loop**, surface the error to the user in chat + Telegram, wait for them to fix it. DO NOT silently retry.

## Handy commands the user might ask for

- \`applyloop start\` / \`applyloop stop\` / \`applyloop status\` / \`applyloop logs\`
- \`applyloop update\` — git pull + rebuild
- \`applyloop uninstall\` — wipe everything except \`~/.autoapply/\` workspace
AGENTSEOF

# ------------------------------------------------------------------ .app bundle

log "Generating .app bundle via build_local_app.sh"
# Pass APPLYLOOP_HOME and APPLYLOOP_APP through so the caller can override
# both (useful for smoke tests against /tmp/ApplyLoop-test.app).
export APPLYLOOP_HOME
if [[ -n "${APPLYLOOP_APP:-}" ]]; then export APPLYLOOP_APP; fi
bash "$APPLYLOOP_HOME/packages/desktop/scripts/build_local_app.sh"

# ------------------------------------------------------------------ CLI shim symlink

mkdir -p "$HOME/.local/bin"
ln -sf "$APPLYLOOP_HOME/packages/desktop/scripts/applyloop" "$HOME/.local/bin/applyloop"
chmod +x "$APPLYLOOP_HOME/packages/desktop/scripts/applyloop" 2>/dev/null || true

# ------------------------------------------------------------------ version stamp

git -C "$APPLYLOOP_HOME" rev-parse HEAD > "$APPLYLOOP_HOME/.applyloop-version"

# ------------------------------------------------------------------ Phase F: auto-update launchd plist
#
# Register a user-scope launchd job that runs `applyloop update` daily
# at 3 AM. RunAtLoad=false (runs on the schedule only — don't hammer
# git pull every login). Uninstalled by `applyloop uninstall`.

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.applyloop.update.plist"
UPDATE_LOG="$HOME/.autoapply/update.log"
UPDATE_ERR_LOG="$HOME/.autoapply/update.err.log"

mkdir -p "$PLIST_DIR" "$HOME/.autoapply"

cat > "$PLIST_FILE" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.applyloop.update</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${HOME}/.local/bin/applyloop</string>
    <string>update</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>3</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${UPDATE_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${UPDATE_ERR_LOG}</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLISTEOF

# Refresh launchd registration. `bootout` handles "already loaded" cleanly
# on macOS 11+ via the user/$UID domain; fall back to load/unload for older
# systems.
launchctl unload "$PLIST_FILE" 2>/dev/null || true
if launchctl bootstrap "gui/$(id -u)" "$PLIST_FILE" 2>/dev/null; then
  log "launchd: com.applyloop.update bootstrapped (daily 3:00 AM)"
elif launchctl load "$PLIST_FILE" 2>/dev/null; then
  log "launchd: com.applyloop.update loaded (daily 3:00 AM)"
else
  warn "launchctl could not load $PLIST_FILE — run manually: launchctl load $PLIST_FILE"
fi

# ------------------------------------------------------------------ success summary

APP_TARGET="${APPLYLOOP_APP:-/Applications/ApplyLoop.app}"
echo
echo "${C_GREEN}${C_BOLD}  ApplyLoop installed successfully${C_RESET}"
echo
echo "  ${C_BOLD}Location:${C_RESET}   $APPLYLOOP_HOME"
echo "  ${C_BOLD}Bundle:${C_RESET}     $APP_TARGET"
echo "  ${C_BOLD}CLI:${C_RESET}        $HOME/.local/bin/applyloop"
echo "  ${C_BOLD}Version:${C_RESET}    $(cat "$APPLYLOOP_HOME/.applyloop-version" | head -c 12)"
echo
echo "  ${C_BOLD}Next steps:${C_RESET}"
echo "    1. Double-click ${C_BLUE}$APP_TARGET${C_RESET} to launch the wizard"
echo "       (or run: ${C_BLUE}open \"$APP_TARGET\"${C_RESET})"
echo "    2. Or from anywhere: ${C_BLUE}applyloop start${C_RESET}"
echo "       (make sure ~/.local/bin is on PATH — most modern shells already do this)"
echo
echo "  Update later:    ${C_BLUE}applyloop update${C_RESET}"
echo "  Uninstall:       ${C_BLUE}applyloop uninstall${C_RESET}"
echo
