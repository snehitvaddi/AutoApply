#!/bin/bash
# AutoApply — One-command setup script
# Usage: curl -sSL https://autoapply.app/setup.sh | bash
# Or run via Claude Code: claude --dangerously-skip-permissions "$(cat setup-prompt.md)"

set -e

AUTOAPPLY_API="${AUTOAPPLY_API:-https://autoapply.app}"

echo "================================================"
echo "  AutoApply — Automated Job Application Setup"
echo "================================================"
echo ""

# ─── Prerequisites ───────────────────────────────────────────────────────────

command -v node >/dev/null 2>&1 || { echo "Node.js is required. Install: https://nodejs.org"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required."; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "jq is required. Install: brew install jq"; exit 1; }

# ─── Step 1: Authenticate ────────────────────────────────────────────────────

echo "[1/9] Authenticating with AutoApply..."
echo ""
echo "  Get your API token from: ${AUTOAPPLY_API}/dashboard/settings"
echo ""
read -p "  Paste your API token: " -s AUTOAPPLY_TOKEN
echo ""

# Verify token
PROFILE_JSON=$(curl -sf -H "Authorization: Bearer ${AUTOAPPLY_TOKEN}" \
  "${AUTOAPPLY_API}/api/settings/profile" 2>/dev/null) || {
  echo "  ERROR: Invalid token or server unreachable."
  exit 1
}

FIRST_NAME=$(echo "$PROFILE_JSON" | jq -r '.data.profile.first_name // empty')
if [ -z "$FIRST_NAME" ]; then
  echo "  ERROR: Could not read profile. Check your token."
  exit 1
fi
LAST_NAME=$(echo "$PROFILE_JSON" | jq -r '.data.profile.last_name // empty')
echo "  Authenticated as: ${FIRST_NAME} ${LAST_NAME}"

# ─── Step 2: Install OpenClaw ────────────────────────────────────────────────

echo "[2/9] Checking OpenClaw..."
if command -v openclaw >/dev/null 2>&1; then
  echo "  OpenClaw already installed: $(openclaw --version 2>/dev/null | head -1)"
else
  echo "  Installing OpenClaw CLI..."
  npm install -g openclaw
  echo "  OpenClaw installed: $(openclaw --version 2>/dev/null | head -1)"
fi

# ─── Step 3: Start OpenClaw Gateway + Browser ────────────────────────────────

echo "[3/9] Starting OpenClaw..."
if openclaw gateway status 2>/dev/null | grep -q "running"; then
  echo "  Gateway already running."
else
  openclaw gateway --port 18789 &
  sleep 3
fi

if openclaw browser status 2>/dev/null | grep -q "running"; then
  echo "  Browser already running."
else
  openclaw browser create-profile autoapply 2>/dev/null || true
  openclaw browser start --browser-profile autoapply 2>/dev/null &
  sleep 2
fi

# Create agent
if ! openclaw agents list 2>/dev/null | grep -q "autoapply"; then
  openclaw agents add autoapply \
    --workspace "$HOME/.autoapply/workspace" \
    --non-interactive 2>/dev/null || true
fi

# ─── Step 4: Download profile from backend ────────────────────────────────────

echo "[4/9] Downloading your profile..."
WORKSPACE="$HOME/.autoapply/workspace"
mkdir -p "$WORKSPACE"
mkdir -p /tmp/openclaw/uploads

# Save profile JSON
echo "$PROFILE_JSON" | jq '.data.profile' > "$WORKSPACE/profile.json"

# Download preferences
curl -sf -H "Authorization: Bearer ${AUTOAPPLY_TOKEN}" \
  "${AUTOAPPLY_API}/api/settings/preferences" | jq '.data' > "$WORKSPACE/preferences.json" 2>/dev/null || true

# Download resume
curl -sf -H "Authorization: Bearer ${AUTOAPPLY_TOKEN}" \
  "${AUTOAPPLY_API}/api/onboarding/resume/download" -o /tmp/openclaw/uploads/resume.pdf 2>/dev/null || true

echo "  Profile saved to $WORKSPACE/profile.json"

# ─── Step 5: Generate answer key + PROFILE.md ────────────────────────────────

echo "[5/9] Generating answer key..."

python3 << 'PYEOF'
import json, os

ws = os.path.expanduser("~/.autoapply/workspace")
p = json.load(open(f"{ws}/profile.json"))

# Generate PROFILE.md
md = f"""# User Profile

## Personal
- **Name:** {p.get('first_name','')} {p.get('last_name','')}
- **Email:** {p.get('email','')}
- **Phone:** {p.get('phone','')}
- **LinkedIn:** {p.get('linkedin_url','')}
- **GitHub:** {p.get('github_url','')}

## Work
- **Current Company:** {p.get('current_company','')}
- **Current Title:** {p.get('current_title','')}
- **Years of Experience:** {p.get('years_experience','')}

## Education
- **School:** {p.get('school_name','')}
- **Degree:** {p.get('degree','')}
- **Graduation Year:** {p.get('graduation_year','')}

## Authorization
- **Work Authorization:** {p.get('work_authorization','')}
- **Requires Sponsorship:** {p.get('requires_sponsorship','')}
"""
open(f"{ws}/PROFILE.md", "w").write(md)

# Use answer_key_json if available, otherwise build from profile
ak = p.get("answer_key_json", {})
if ak:
    json.dump(ak, open(f"{ws}/answer-key.json", "w"), indent=2)
else:
    # Minimal answer key from profile fields
    ak = {
        "first name": p.get("first_name", ""),
        "last name": p.get("last_name", ""),
        "full name": f"{p.get('first_name', '')} {p.get('last_name', '')}",
        "email": p.get("email", ""),
        "phone": p.get("phone", ""),
        "linkedin": p.get("linkedin_url", ""),
        "github": p.get("github_url", ""),
        "company": p.get("current_company", ""),
        "title": p.get("current_title", ""),
        "school": p.get("school_name", ""),
        "degree": p.get("degree", ""),
    }
    json.dump(ak, open(f"{ws}/answer-key.json", "w"), indent=2)

print("  Generated PROFILE.md and answer-key.json")
PYEOF

# ─── Step 6: Copy knowledge base ─────────────────────────────────────────────

echo "[6/9] Setting up knowledge base..."
AUTOAPPLY_DIR="${AUTOAPPLY_DIR:-$HOME/autoapply}"
if [ -d "$AUTOAPPLY_DIR/knowledge" ]; then
  cp "$AUTOAPPLY_DIR/knowledge/learnings.md" "$WORKSPACE/" 2>/dev/null || true
  cp -r "$AUTOAPPLY_DIR/knowledge/ats-guides" "$WORKSPACE/" 2>/dev/null || true
  echo "  Knowledge base copied."
else
  echo "  No local knowledge base found (will use defaults)."
fi

# Save API token for worker use
echo "$AUTOAPPLY_TOKEN" > "$WORKSPACE/.api-token"
chmod 600 "$WORKSPACE/.api-token"

# ─── Step 7: Generate SOUL.md ─────────────────────────────────────────────────

echo "[7/9] Finalizing agent setup..."

cat > "$WORKSPACE/SOUL.md" << SOULEOF
# SOUL.md - AutoApply Agent

You are **AutoApply Agent** -- an autonomous job application bot for **${FIRST_NAME} ${LAST_NAME}**.

## BEFORE EVERY SESSION
1. Read answer-key.json -- pre-computed answers for ALL form fields
2. Read PROFILE.md -- user's complete data
3. Read learnings.md -- solutions to known ATS quirks
4. Stage resume: ensure /tmp/openclaw/uploads/resume.pdf exists

## HOW TO APPLY
1. browser open "{apply_url}"
2. browser wait --load networkidle
3. browser snapshot --efficient --interactive -> parse fields
4. Set phone country code FIRST
5. browser fill --fields '[{json}]' -> batch fill ALL text fields
6. browser upload /tmp/openclaw/uploads/resume.pdf --ref {ref}
7. Handle dropdowns: click -> snapshot -> click option
8. Handle checkboxes: click consent/privacy/terms
9. Find submit button -> browser click {ref}
10. browser screenshot --full-page -> capture proof
11. Report result to backend

## RATE LIMITS
- 30 seconds between applications (same ATS)
- Max 50 applications per day
- Max 60 per hour system-wide
SOULEOF

# ─── Step 8: Install & Configure AI CLI (Codex) ─────────────────────────────

echo "[8/9] Setting up Codex CLI..."

# Install Codex if not present
if command -v codex >/dev/null 2>&1; then
  echo "  Codex already installed: $(codex --version 2>/dev/null | head -1)"
else
  echo "  Installing Codex CLI..."
  npm install -g @openai/codex
  echo "  Codex installed: $(codex --version 2>/dev/null | head -1)"
fi

# Fetch CLI config from backend (determines auth mode)
CLI_CONFIG=$(curl -sf -H "Authorization: Bearer ${AUTOAPPLY_TOKEN}" \
  "${AUTOAPPLY_API}/api/settings/cli-config" 2>/dev/null) || true

CLI_MODE=$(echo "$CLI_CONFIG" | jq -r '.data.ai_cli_mode // "own_account"')
CLI_API_KEY=$(echo "$CLI_CONFIG" | jq -r '.data.api_key // empty')

if [ "$CLI_MODE" = "provided_key" ] && [ -n "$CLI_API_KEY" ]; then
  echo "  Configuring Codex with provided API key..."
  echo "$CLI_API_KEY" | codex login --with-api-key
  echo "  Codex authenticated (managed key)."
else
  echo ""
  echo "  You need to log in with your own OpenAI account."
  echo "  A browser window will open — sign in and come back here."
  echo ""
  codex login
  echo "  Codex authenticated."
fi

# ─── Step 9: Generate AGENTS.md & Launch ─────────────────────────────────────

echo "[9/9] Preparing AI context..."

cat > "$WORKSPACE/AGENTS.md" << AGENTSEOF
# AutoApply Agent — Codex Context

## What This Is
AutoApply is an automated job application system for **${FIRST_NAME} ${LAST_NAME}**.
It discovers jobs from 370+ company boards every 6 hours and auto-fills applications
using browser automation (OpenClaw).

## Workspace Layout
- **PROFILE.md** — User's personal info, work history, education
- **answer-key.json** — Pre-computed answers for ALL form fields
- **SOUL.md** — Agent behavior instructions (how to fill forms)
- **learnings.md** — 700+ ATS patterns from 900+ real applications
- **ats-guides/** — Platform-specific guides (Greenhouse, Lever, Ashby, SmartRecruiters)
- **resume.pdf** — At /tmp/openclaw/uploads/resume.pdf

## OpenClaw (Browser Automation)
OpenClaw is running on this machine. Use it to automate browser actions:
\`\`\`
openclaw browser open <url>          # Navigate to URL
openclaw browser snapshot            # Get page state
openclaw browser fill --fields '[…]' # Fill form fields
openclaw browser click <ref>         # Click element
openclaw browser upload <file>       # Upload resume
openclaw browser screenshot          # Capture proof
\`\`\`

## How to Apply to a Job
1. Read answer-key.json for pre-filled answers
2. \`openclaw browser open "{apply_url}"\`
3. \`openclaw browser snapshot --efficient --interactive\` to see fields
4. Set phone country code first
5. \`openclaw browser fill\` to batch-fill text fields
6. \`openclaw browser upload /tmp/openclaw/uploads/resume.pdf\`
7. Handle dropdowns: click → snapshot → click option
8. Handle checkboxes: click consent/privacy/terms
9. Find and click submit
10. \`openclaw browser screenshot --full-page\` for proof

## Backend API
- Dashboard: ${AUTOAPPLY_API}/dashboard
- Token is stored at: $WORKSPACE/.api-token
- Report results: POST ${AUTOAPPLY_API}/api/applications

## Telegram Notifications
If the user provides a Telegram Chat ID (from @BotFather or @userinfobot), save it:
\`\`\`bash
curl -X PUT -H "Authorization: Bearer \$(cat $WORKSPACE/.api-token)" \\
  -H "Content-Type: application/json" \\
  -d '{"telegram_chat_id": "CHAT_ID_HERE"}' \\
  ${AUTOAPPLY_API}/api/settings/telegram
\`\`\`
Once set, the user gets real-time notifications for every application submitted.

## OpenClaw Config
OpenClaw gateway runs on port 18789. Browser profile: "autoapply".
Agent workspace: $WORKSPACE
If OpenClaw is not running, start it:
\`\`\`bash
openclaw gateway --port 18789 &
openclaw browser start --browser-profile autoapply &
\`\`\`

## Settings API (for updating user config)
\`\`\`
GET  ${AUTOAPPLY_API}/api/settings/profile       # Read profile
PUT  ${AUTOAPPLY_API}/api/settings/profile       # Update profile fields
GET  ${AUTOAPPLY_API}/api/settings/preferences   # Read job preferences
PUT  ${AUTOAPPLY_API}/api/settings/preferences   # Update preferences
PUT  ${AUTOAPPLY_API}/api/settings/telegram      # Save Telegram chat ID
\`\`\`
All requests need: \`Authorization: Bearer \$(cat $WORKSPACE/.api-token)\`

## Rate Limits
- 30 seconds between applications (same ATS)
- Max 50 applications per day
- Max 60 per hour system-wide
AGENTSEOF

echo "  Generated AGENTS.md"

echo ""
echo "================================================"
echo "  Setup complete!"
echo ""
echo "  Workspace:   $WORKSPACE"
echo "  Profile:     $WORKSPACE/PROFILE.md"
echo "  Answer Key:  $WORKSPACE/answer-key.json"
echo "  Agent Docs:  $WORKSPACE/AGENTS.md"
echo "  Resume:      /tmp/openclaw/uploads/resume.pdf"
echo ""
echo "  Dashboard:   ${AUTOAPPLY_API}/dashboard"
echo "================================================"
echo ""
echo "  Launching Codex with full context..."
echo ""

# Launch Codex in the workspace with a context-rich initial prompt
exec codex --cd "$WORKSPACE" "$(cat << PROMPTEOF
I am the AutoApply agent for ${FIRST_NAME} ${LAST_NAME}.

I have read the workspace files:
- AGENTS.md — my instructions and OpenClaw commands
- PROFILE.md — user's personal data
- answer-key.json — pre-computed form field answers
- SOUL.md — detailed application workflow
- learnings.md — ATS patterns from 900+ applications

OpenClaw browser automation is running on this machine.
The user's resume is at /tmp/openclaw/uploads/resume.pdf.
Backend API is at ${AUTOAPPLY_API}.

I'm ready to help with automated job applications. What would you like to do?
PROMPTEOF
)"
