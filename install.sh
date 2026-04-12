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

# ── Validation helper ───────────────────────────────────────────────
#
# Prompts the user on /dev/tty, validates against a regex, and retries
# until the input is valid OR the user presses Enter with no value
# (which skips the field cleanly). Max 5 attempts before auto-skip so
# we can't get stuck in an infinite loop on a bad paste.
#
# Usage:
#   VAL="$(prompt_validated "Gmail: " '^[^@]+@[^@]+\.[^@]+$' "not a valid email")"
#
# The prompt text goes directly to /dev/tty (not stderr) so it's visible
# across bash 3.2 (macOS default) and bash 5.x regardless of `read -p`
# behavior. stdout carries ONLY the validated value so callers can
# capture it via $(...).
prompt_validated() {
  local prompt_text="$1" regex="$2" errmsg="$3"
  local max_attempts=5
  local attempt=0
  local val=""
  while [[ "$attempt" -lt "$max_attempts" ]]; do
    printf "%s" "$prompt_text" > /dev/tty
    if ! IFS= read -r val < /dev/tty; then
      echo ""
      return 0
    fi
    if [[ -z "$val" ]]; then
      echo ""
      return 0
    fi
    if [[ "$val" =~ $regex ]]; then
      echo "$val"
      return 0
    fi
    printf "  ${C_YELLOW}Invalid:${C_RESET} %s. Try again or press Enter to skip.\n" "$errmsg" > /dev/tty
    attempt=$((attempt + 1))
  done
  printf "  ${C_YELLOW}Max attempts reached - skipping.${C_RESET}\n" > /dev/tty
  echo ""
}

# ── .env reuse helpers ─────────────────────────────────────────────
#
# On a fresh install, Phase D prompts for all optional integrations.
# On a RE-install (same $APPLYLOOP_HOME), we should detect the existing
# ~/.applyloop/.env and offer [Enter to keep / 's' to unset / type new]
# per field. Pujith hit this pain — every rerun re-asked Telegram Chat
# ID, AgentMail, Finetune, Gmail email + password from scratch.

# Read a single KEY=value line from the existing ~/.applyloop/.env. Trim
# wrapping quotes and surrounding whitespace. Empty if file missing or
# key not set.
read_env_value() {
  local key="$1"
  local env_file="$APPLYLOOP_HOME/.env"
  [[ -f "$env_file" ]] || { echo ""; return 0; }
  grep -E "^${key}=" "$env_file" 2>/dev/null | head -1 \
    | sed -E "s/^${key}=//" \
    | sed -E 's/^"//; s/"$//; s/^'\''//; s/'\''$//'
}

# Three-way prompt: keep existing / unset / type new. If no existing
# value, falls through to prompt_validated.
#
# Usage:
#   TELEGRAM_CHAT_ID="$(reuse_or_prompt \
#       TELEGRAM_CHAT_ID \
#       'Telegram Chat ID' \
#       '^-?[0-9]+$' \
#       'digits only (may start with - for group chats)')"
reuse_or_prompt() {
  local key="$1" label="$2" regex="$3" errmsg="$4"
  local existing val display
  existing="$(read_env_value "$key")"
  if [[ -z "$existing" ]]; then
    # No prior value — use the standard prompt
    prompt_validated "  $label: " "$regex" "$errmsg"
    return 0
  fi

  # Mask secrets for the display. Anything ending in _KEY / _TOKEN /
  # _PASSWORD shows only the last 4 chars.
  display="$existing"
  case "$key" in
    *KEY|*TOKEN|*PASSWORD)
      if [[ ${#existing} -gt 4 ]]; then
        display="****${existing: -4}"
      else
        display="****"
      fi
      ;;
  esac

  printf "  %s: ${C_BLUE}%s${C_RESET}  [Enter to keep / 's' to unset / type new]: " \
    "$label" "$display" > /dev/tty
  if ! IFS= read -r val < /dev/tty; then
    echo "$existing"
    return 0
  fi

  if [[ -z "$val" ]]; then
    # Enter pressed — keep the existing value
    echo "$existing"
    return 0
  fi

  if [[ "$val" == "s" || "$val" == "S" ]]; then
    # Explicit unset
    printf "  ${C_YELLOW}Unset.${C_RESET}\n" > /dev/tty
    echo ""
    return 0
  fi

  # Validate the new value
  if [[ "$val" =~ $regex ]]; then
    echo "$val"
    return 0
  fi

  printf "  ${C_YELLOW}Invalid:${C_RESET} %s - keeping old value.\n" "$errmsg" > /dev/tty
  echo "$existing"
}

# ------------------------------------------------------------------ guards

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "Only macOS is supported right now. Linux + Windows support is tracked at https://github.com/snehitvaddi/AutoApply/issues - open or comment on an issue to request it."
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
# Ensure the parent directory exists — covers the case where the user
# passes APPLYLOOP_HOME=/deeply/nested/path/that/does/not/exist. git
# clone --depth 1 would fail if the parent doesn't exist; mkdir -p
# handles both "parent missing" and "parent exists" gracefully.
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

# Integration credentials pulled from cloud (from /api/settings/integrations
# in Phase C below). If the user already saved these on a prior install or
# via the web dashboard, they'll come back as plaintext here and get used
# as defaults in the interactive prompts (reuse_or_prompt respects non-empty
# defaults from both ~/.applyloop/.env AND these shell vars).
INTEGRATIONS_TELEGRAM_BOT=""
INTEGRATIONS_TELEGRAM_CHAT=""
INTEGRATIONS_GMAIL_EMAIL=""
INTEGRATIONS_GMAIL_PW=""
INTEGRATIONS_AGENTMAIL=""
INTEGRATIONS_FINETUNE=""

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

  # Also pull the encrypted integrations blob via /api/settings/integrations?raw=1.
  # This returns plaintext values for any integration the user already saved
  # (via web dashboard, desktop app, or a prior install). If the migration
  # 010_user_integrations.sql hasn't been applied yet on the user's Supabase
  # project, this endpoint returns 500 with a helpful message — we log it
  # and move on (prompts fall back to interactive).
  log "Fetching saved integrations (if any)..."
  INT_TMP="$(mktemp -t applyloop-integrations.XXXXXX)"
  INT_HTTP="$(curl -sS -o "$INT_TMP" -w "%{http_code}" \
    -H "X-Worker-Token: $WORKER_TOKEN" \
    "$APP_URL/api/settings/integrations?raw=1" 2>/dev/null || echo "000")"
  if [[ "$INT_HTTP" == "200" ]]; then
    INT_VARS="$(python3 -c "
import sys, json
try:
    d = json.loads(open('$INT_TMP').read()).get('data', {}).get('integrations', {}) or {}
    print(f'TB={d.get(\"telegram_bot_token\") or \"\"}')
    print(f'TC={d.get(\"telegram_chat_id\") or \"\"}')
    print(f'GE={d.get(\"gmail_email\") or \"\"}')
    print(f'GP={d.get(\"gmail_app_password\") or \"\"}')
    print(f'AM={d.get(\"agentmail_api_key\") or \"\"}')
    print(f'FT={d.get(\"finetune_resume_api_key\") or \"\"}')
except Exception as e:
    print(f'ERR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)"
    while IFS='=' read -r key val; do
      case "$key" in
        TB) INTEGRATIONS_TELEGRAM_BOT="$val" ;;
        TC) INTEGRATIONS_TELEGRAM_CHAT="$val" ;;
        GE) INTEGRATIONS_GMAIL_EMAIL="$val" ;;
        GP) INTEGRATIONS_GMAIL_PW="$val" ;;
        AM) INTEGRATIONS_AGENTMAIL="$val" ;;
        FT) INTEGRATIONS_FINETUNE="$val" ;;
      esac
    done <<< "$INT_VARS"
    # If cloud has real values, use them as the authoritative defaults so
    # reuse_or_prompt will show them as "current" rather than asking blank.
    if [[ -n "$INTEGRATIONS_TELEGRAM_BOT" ]]; then
      TELEGRAM_BOT_TOKEN_VAL="$INTEGRATIONS_TELEGRAM_BOT"
    fi
    if [[ -n "$INTEGRATIONS_TELEGRAM_CHAT" && -z "$ACTIVATION_TELEGRAM_CHAT_ID" ]]; then
      ACTIVATION_TELEGRAM_CHAT_ID="$INTEGRATIONS_TELEGRAM_CHAT"
    fi
    _filled=0
    for v in "$INTEGRATIONS_TELEGRAM_BOT" "$INTEGRATIONS_TELEGRAM_CHAT" \
             "$INTEGRATIONS_GMAIL_EMAIL" "$INTEGRATIONS_GMAIL_PW" \
             "$INTEGRATIONS_AGENTMAIL" "$INTEGRATIONS_FINETUNE"; do
      [[ -n "$v" ]] && _filled=$((_filled + 1))
    done
    if [[ $_filled -gt 0 ]]; then
      log "  Loaded $_filled integration(s) from cloud"
    fi
  elif [[ "$INT_HTTP" == "500" ]]; then
    warn "Integrations endpoint returned 500 — run supabase/migrations/010_user_integrations.sql on your Supabase project"
  else
    log "  No saved integrations on cloud yet (HTTP $INT_HTTP)"
  fi
  rm -f "$INT_TMP"
fi

# Transform the activation + cli-config responses into the nested profile.json
# shape that Claude Code / the worker expects.
#
# Why both responses?
#
# /api/activate returns the raw user_profiles row, which means work_experience
# is whatever Supabase has — usually [] because the onboarding form never
# posts the parsed array (that's a separate bug being fixed server-side).
#
# /api/settings/cli-config returns the SAME profile but runs a synthesis
# fallback: if work_experience is empty but current_company is set, it
# builds a single-entry array from the flat fields. That means cli-config
# always has the richer shape when the flat fields are populated.
#
# We prefer cli-config for profile/preferences and fall back to activate
# for identity fields (user_id / email / full_name / tier) which cli-config
# doesn't always include.
if [[ -n "$ACTIVATION_PROFILE_JSON" ]]; then
  log "Writing $APPLYLOOP_HOME/profile.json"
  ACT_TMP="$(mktemp -t applyloop-activate.XXXXXX)"
  CFG_TMP2="$(mktemp -t applyloop-cfg.XXXXXX)"
  printf '%s' "$ACTIVATION_PROFILE_JSON" > "$ACT_TMP"
  printf '%s' "$CLI_CONFIG_JSON" > "$CFG_TMP2"

  APPLYLOOP_HOME="$APPLYLOOP_HOME" \
  ACTIVATE_PATH="$ACT_TMP" \
  CLI_CONFIG_PATH="$CFG_TMP2" \
  python3 <<'PY' || warn "profile.json transform failed"
import json, os

def load(path):
    try:
        with open(path) as f:
            return json.loads(f.read()).get("data", {}) or {}
    except Exception:
        return {}

act = load(os.environ["ACTIVATE_PATH"])
cfg = load(os.environ["CLI_CONFIG_PATH"]) if os.environ.get("CLI_CONFIG_PATH") else {}

# cli-config shape: data.profile, data.preferences, data.user
# activate shape:   data.profile, data.preferences, data.user_id/email/full_name/tier
cfg_profile = cfg.get("profile") or {}
act_profile = act.get("profile") or {}
cfg_prefs = cfg.get("preferences") or {}
act_prefs = act.get("preferences") or {}

# Prefer cli-config for profile fields since it runs the work_experience
# synthesis fallback. Fall back to activate.profile for anything missing.
def pick(key, default=None):
    v = cfg_profile.get(key)
    if v not in (None, "", [], {}):
        return v
    return act_profile.get(key) if act_profile.get(key) not in (None, "") else default

# User identity: activate is authoritative (cli-config may not include tier)
user_id = act.get("user_id") or (cfg.get("user", {}) or {}).get("id") or ""
email = act.get("email") or (cfg.get("user", {}) or {}).get("email") or ""
full_name = act.get("full_name") or (cfg.get("user", {}) or {}).get("full_name") or ""
tier = act.get("tier") or cfg.get("tier") or ""

profile = {
  "user": {
    "id": user_id,
    "email": email or "",
    "full_name": full_name or "",
    "tier": tier or "",
  },
  "personal": {
    "first_name": pick("first_name", "") or "",
    "last_name": pick("last_name", "") or "",
    "email": email or "",
    "phone": pick("phone", "") or "",
    "linkedin_url": pick("linkedin_url", "") or "",
    "github_url": pick("github_url", "") or "",
    "portfolio_url": pick("portfolio_url", "") or "",
  },
  "work": {
    "current_company": pick("current_company", "") or "",
    "current_title": pick("current_title", "") or "",
    "years_experience": pick("years_experience", "") or "",
  },
  "legal": {
    "work_authorization": pick("work_authorization", "") or "",
    "requires_sponsorship": pick("requires_sponsorship", False) or False,
  },
  "eeo": {
    "gender": pick("gender", "") or "",
    "race_ethnicity": pick("race_ethnicity", "") or "",
    "veteran_status": pick("veteran_status", "") or "",
    "disability_status": pick("disability_status", "") or "",
  },
  "experience": pick("work_experience", []) or [],
  "education": pick("education", "") or "",
  "education_summary": {
    "education_level": pick("education_level", "") or "",
    "school_name": pick("school_name", "") or "",
    "degree": pick("degree", "") or "",
    "graduation_year": pick("graduation_year", "") or "",
  },
  "skills": pick("skills", []) or [],
  "standard_answers": pick("answer_key_json", {}) or {},
  "cover_letter_template": pick("cover_letter_template", "") or "",
  "preferences": cfg_prefs or act_prefs or {},
  "resumes": [act.get("default_resume")] if act.get("default_resume") else [],
}

home = os.environ["APPLYLOOP_HOME"]
os.makedirs(home, exist_ok=True)
with open(f"{home}/profile.json", "w") as f:
    json.dump(profile, f, indent=2)

print(f"  wrote {len(profile['experience'])} experience, {len(profile['skills'])} skills, targets={len(profile['preferences'].get('target_titles',[]) or [])}")
source = "cli-config" if cfg_profile else "activate"
print(f"  primary source: {source}")
PY
  rm -f "$ACT_TMP" "$CFG_TMP2"
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

  # 1a) Telegram bot token. The cloud's cli-config returns an admin-global
  # bot token in TELEGRAM_BOT_TOKEN_VAL, but when that admin slot is empty
  # or stubbed with a placeholder the user needs their own bot. Real tokens
  # are shaped "<bot_id>:<secret>" and are at least ~45 chars. Anything
  # shorter (e.g. "placeholder") we treat as absent and re-prompt.
  _tg_bot_valid="no"
  if [[ -n "$TELEGRAM_BOT_TOKEN_VAL" ]]; then
    if [[ ${#TELEGRAM_BOT_TOKEN_VAL} -ge 30 && "$TELEGRAM_BOT_TOKEN_VAL" == *:* ]]; then
      _tg_bot_valid="yes"
    fi
  fi
  if [[ "$_tg_bot_valid" == "no" ]]; then
    echo "${C_BOLD}  Telegram bot token${C_RESET} - required if you want ApplyLoop to message you"
    echo "    (if you already have a bot, paste its token; otherwise skip)"
    echo ""
    echo "    How to get a bot token in 45 seconds:"
    echo "      1. Open Telegram → search for @BotFather → /start"
    echo "      2. Send /newbot, pick a name (anything), pick a username ending in 'bot'"
    echo "      3. BotFather replies with a line like: 1234567890:ABCdefGHIjklMNOpqrsTUV..."
    echo "      4. Paste that full line below. Press Enter to skip."
    TELEGRAM_BOT_TOKEN_VAL="$(reuse_or_prompt \
      TELEGRAM_BOT_TOKEN \
      'Telegram Bot Token' \
      '^[0-9]{6,}:[A-Za-z0-9_-]{25,}$' \
      'format is <bot_id>:<secret>, e.g. 1234567890:ABCdef...')"
    echo ""
  fi

  # 1b) Telegram chat ID. Chat IDs are integers; group chats can be
  # negative (e.g. -1001234567890). Precedence:
  #   1. env var APPLYLOOP_TELEGRAM_CHAT_ID (non-interactive override)
  #   2. value already in the activation response (cli-config)
  #   3. existing ~/.applyloop/.env (reuse with confirmation)
  #   4. interactive prompt
  if [[ -n "${APPLYLOOP_TELEGRAM_CHAT_ID:-}" ]]; then
    ACTIVATION_TELEGRAM_CHAT_ID="$APPLYLOOP_TELEGRAM_CHAT_ID"
  elif [[ -z "$ACTIVATION_TELEGRAM_CHAT_ID" ]]; then
    if [[ -n "$TELEGRAM_BOT_TOKEN_VAL" ]]; then
      echo "${C_BOLD}  Telegram chat ID${C_RESET}"
      echo "    1. Open Telegram, start a chat with YOUR bot (the one you just made)"
      echo "    2. Send it any message (e.g. 'hello')"
      echo "    3. Visit: https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN_VAL:0:12}.../getUpdates"
      echo "       and look for 'chat':{'id': NUMBER — that's your chat ID"
      echo "    4. Paste the number below (or Enter to skip)"
    else
      echo "${C_BOLD}  Telegram chat ID${C_RESET} - skipping (no bot token provided)"
    fi
    if [[ -n "$TELEGRAM_BOT_TOKEN_VAL" ]]; then
      ACTIVATION_TELEGRAM_CHAT_ID="$(reuse_or_prompt \
        TELEGRAM_CHAT_ID \
        'Telegram Chat ID' \
        '^-?[0-9]+$' \
        'digits only (may start with - for group chats)')"
    fi
    echo ""
  fi

  # 2) AgentMail (disposable inboxes)
  if [[ -z "$AGENTMAIL_KEY_VAL" ]]; then
    echo "${C_BOLD}  AgentMail${C_RESET} - disposable email inboxes for job verification"
    echo "    Sign up at https://agentmail.to/dashboard and copy your API key."
    AGENTMAIL_KEY_VAL="$(reuse_or_prompt \
      AGENTMAIL_API_KEY \
      'AgentMail API key' \
      '^.{8,}$' \
      'API key looks too short (expected at least 8 chars)')"
    if [[ -n "$AGENTMAIL_KEY_VAL" ]] && [[ "$AGENTMAIL_KEY_VAL" != "$(read_env_value AGENTMAIL_API_KEY)" ]]; then
      # Only curl-verify if the user entered a NEW value — no point
      # re-hitting the API for a key we already had.
      log "  Verifying AgentMail key..."
      AM_HTTP="$(curl -sS -o /dev/null -w "%{http_code}" \
        "https://api.agentmail.to/v0/inboxes" \
        -H "Authorization: Bearer $AGENTMAIL_KEY_VAL" 2>/dev/null || echo "000")"
      if [[ "$AM_HTTP" == "200" ]]; then
        log "  ${C_GREEN}AgentMail key verified${C_RESET}"
      else
        warn "  AgentMail key returned HTTP $AM_HTTP - saving anyway, fix in ~/.applyloop/.env later"
      fi
    fi
    echo ""
  fi

  # 3) Finetune Resume (per-job tailored resume generation)
  if [[ -z "$FINETUNE_KEY_VAL" ]]; then
    echo "${C_BOLD}  Finetune Resume${C_RESET} - per-job tailored resume generation"
    echo "    The service already has your base resume from signup; it returns a"
    echo "    tailored PDF when you send a job description + API key."
    FINETUNE_KEY_VAL="$(reuse_or_prompt \
      FINETUNE_RESUME_API_KEY \
      'Finetune Resume API key' \
      '^.{8,}$' \
      'API key looks too short (expected at least 8 chars)')"
    echo ""
  fi

  # 4) Gmail + Himalaya (email verification codes).
  # Reuse existing .env values if present, matching the pattern of the
  # three prompts above.
  if [[ -z "$GMAIL_EMAIL_VAL" && -z "$GMAIL_APP_PW_VAL" ]]; then
    echo "${C_BOLD}  Gmail email verification (optional - skip with Enter)${C_RESET}"
    echo "    Used to read 6-digit confirmation codes from job applications."
    echo "    Requires: 2FA enabled + App Password from"
    echo "    https://myaccount.google.com/apppasswords"

    # Email: reuse-or-prompt with basic email regex.
    GMAIL_EMAIL_VAL="$(reuse_or_prompt \
      GMAIL_EMAIL \
      'Gmail address' \
      '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' \
      'not a valid email (expected name@domain.tld)')"

    if [[ -n "$GMAIL_EMAIL_VAL" ]]; then
      # If there's an existing password in .env and the user kept the
      # existing email, offer to keep the existing password too without
      # re-running the length validator (the existing password is
      # already known-valid).
      EXISTING_GMAIL_PW="$(read_env_value GMAIL_APP_PASSWORD)"
      if [[ -n "$EXISTING_GMAIL_PW" && ${#EXISTING_GMAIL_PW} -eq 16 ]]; then
        printf "  Gmail app password: ${C_BLUE}****%s${C_RESET}  [Enter to keep / 's' to unset / type new]: " "${EXISTING_GMAIL_PW: -4}" > /dev/tty
        IFS= read -r GMAIL_PW_INPUT < /dev/tty || GMAIL_PW_INPUT=""
        if [[ -z "$GMAIL_PW_INPUT" ]]; then
          GMAIL_APP_PW_VAL="$EXISTING_GMAIL_PW"
          echo ""
        elif [[ "$GMAIL_PW_INPUT" == "s" || "$GMAIL_PW_INPUT" == "S" ]]; then
          GMAIL_APP_PW_VAL=""
          GMAIL_EMAIL_VAL=""
          printf "  ${C_YELLOW}Gmail unset.${C_RESET}\n" > /dev/tty
        else
          # User typed a new value — run it through the full length
          # validator below (by setting GMAIL_APP_PW_VAL and falling
          # into the existing loop path).
          GMAIL_APP_PW_VAL="$(echo "$GMAIL_PW_INPUT" | tr -d '[:space:]')"
          if [[ ${#GMAIL_APP_PW_VAL} -ne 16 ]]; then
            printf "  ${C_YELLOW}Invalid:${C_RESET} expected 16 characters after stripping spaces, got %d. Keeping old value.\n" "${#GMAIL_APP_PW_VAL}" > /dev/tty
            GMAIL_APP_PW_VAL="$EXISTING_GMAIL_PW"
          fi
        fi
      else
      # App passwords are displayed by Google as "abcd efgh ijkl mnop" —
      # four groups of four, space-separated. We strip ALL whitespace
      # before validating length. Google app passwords are exactly 16
      # characters after stripping.
      GMAIL_PW_ATTEMPTS=0
      while [[ "$GMAIL_PW_ATTEMPTS" -lt 5 ]]; do
        printf "  Gmail app password (16 chars, paste with spaces is fine, Enter to skip): " > /dev/tty
        if ! IFS= read -r GMAIL_APP_PW_VAL < /dev/tty; then
          GMAIL_APP_PW_VAL=""
          break
        fi
        GMAIL_APP_PW_VAL="$(echo "$GMAIL_APP_PW_VAL" | tr -d '[:space:]')"
        if [[ -z "$GMAIL_APP_PW_VAL" ]]; then
          # Empty Enter = skip. Clear the email too so we don't end up
          # with a half-configured Gmail block in .env.
          GMAIL_EMAIL_VAL=""
          break
        fi
        if [[ ${#GMAIL_APP_PW_VAL} -eq 16 ]]; then
          break
        fi
        printf "  ${C_YELLOW}Invalid:${C_RESET} expected 16 characters after stripping spaces, got %d. Try again or press Enter to skip.\n" "${#GMAIL_APP_PW_VAL}" > /dev/tty
        GMAIL_APP_PW_VAL=""
        GMAIL_PW_ATTEMPTS=$((GMAIL_PW_ATTEMPTS + 1))
      done
      if [[ -z "$GMAIL_APP_PW_VAL" && -n "$GMAIL_EMAIL_VAL" ]]; then
        printf "  ${C_YELLOW}Skipping Gmail - no valid app password provided.${C_RESET}\n" > /dev/tty
        GMAIL_EMAIL_VAL=""
      fi
      fi  # closes: if [[ -n "$EXISTING_GMAIL_PW" ... ]]
    fi    # closes: if [[ -n "$GMAIL_EMAIL_VAL" ]]
    echo ""
  fi      # closes: if [[ -z "$GMAIL_EMAIL_VAL" && -z "$GMAIL_APP_PW_VAL" ]]
fi        # closes: the outer interactive-prompts guard

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

# Tenant identity — worker.py main() reads this and loads TenantConfig
# from /api/worker/proxy?action=get_tenant_config. Without it, the worker
# falls back to reading ~/.applyloop/profile.json for user_id, but setting
# it here is cleaner and makes multi-tenant debugging obvious.
APPLYLOOP_USER_ID=${ACTIVATION_USER_ID}

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

# Cache the user's default resume locally so the Claude Code PTY can read
# it with its built-in Read tool. This is the file the session-start
# stub-detection path passes into the initial prompt when profile.json
# looks thin: Claude parses the PDF, extracts multi-entry work_experience
# / skills / education, and PUTs them straight back to /api/settings/
# profile. Keeps resume parsing off the server (no OpenAI key required).
if [[ -n "$WORKER_TOKEN" ]]; then
  log "Downloading resume PDF for local Claude parsing"
  RESUME_TARGET="$HOME/.autoapply/workspace/resumes/default.pdf"
  RESUME_HTTP="$(curl -sS -o "$RESUME_TARGET" -w "%{http_code}" \
    -H "X-Worker-Token: $WORKER_TOKEN" \
    "$APP_URL/api/onboarding/resume/download" 2>/dev/null || echo "000")"
  if [[ "$RESUME_HTTP" == "200" ]] && [[ -s "$RESUME_TARGET" ]]; then
    # Magic-byte sniff: real PDFs start with "%PDF".
    _head="$(head -c 4 "$RESUME_TARGET" 2>/dev/null)"
    if [[ "$_head" == "%PDF" ]]; then
      log "  ${C_GREEN}Resume cached${C_RESET} — $(wc -c < "$RESUME_TARGET" | tr -d ' ') bytes"
    else
      warn "Downloaded resume isn't a valid PDF (got '${_head}...'), deleting"
      rm -f "$RESUME_TARGET"
    fi
  else
    warn "Resume download returned HTTP $RESUME_HTTP — Claude will ask for fields interactively on first launch"
    rm -f "$RESUME_TARGET"
  fi
fi

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
