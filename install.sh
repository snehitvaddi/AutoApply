#!/usr/bin/env bash
# ApplyLoop installer — curl-able, local-build, no Gatekeeper pain.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh | bash
#
# Env vars (all optional):
#   APPLYLOOP_HOME    install dir (default $HOME/.applyloop)
#   APPLYLOOP_REPO    git URL or local path (default https://github.com/snehitvaddi/AutoApply.git)
#   APPLYLOOP_BRANCH  branch to clone/update (default main)
#   APPLYLOOP_APP     .app bundle path (default /Applications/ApplyLoop.app — passed through to build_local_app.sh)

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
    APPLYLOOP_REEXEC=1 exec bash "$REEXEC_TMP" </dev/null
  fi
  echo "WARNING: could not re-fetch install.sh for safe re-exec. If the install dies after 'Installing python@3.11', re-run as: curl -fsSL $REEXEC_URL -o /tmp/applyloop-install.sh && bash /tmp/applyloop-install.sh" >&2
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
export NPM_CONFIG_CACHE="$APPLYLOOP_HOME/.npm-cache"
mkdir -p "$NPM_CONFIG_CACHE"

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
    "$NPM" install -g openclaw --cache "$NPM_CONFIG_CACHE" --no-fund --no-audit \
      || warn "npm install -g openclaw failed — wizard will retry later"
  fi

  # OpenClaw is open source — no Pro tier, no subscription. The "gateway"
  # is just a local WebSocket daemon registered as a user-scope launchd
  # service. Install + start it now so the wizard's gateway preflight
  # check passes immediately on first launch instead of showing a
  # confusing red row.
  if command -v openclaw >/dev/null 2>&1; then
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
