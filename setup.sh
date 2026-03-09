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

echo "[1/7] Authenticating with AutoApply..."
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

echo "[2/7] Checking OpenClaw..."
if command -v openclaw >/dev/null 2>&1; then
  echo "  OpenClaw already installed: $(openclaw --version 2>/dev/null | head -1)"
else
  echo "  Installing OpenClaw CLI..."
  npm install -g openclaw
  echo "  OpenClaw installed: $(openclaw --version 2>/dev/null | head -1)"
fi

# ─── Step 3: Start OpenClaw Gateway + Browser ────────────────────────────────

echo "[3/7] Starting OpenClaw..."
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

echo "[4/7] Downloading your profile..."
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

echo "[5/7] Generating answer key..."

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

echo "[6/7] Setting up knowledge base..."
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

echo "[7/7] Finalizing agent setup..."

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

echo ""
echo "================================================"
echo "  Setup complete!"
echo ""
echo "  Profile: $WORKSPACE/PROFILE.md"
echo "  Answer Key: $WORKSPACE/answer-key.json"
echo "  Resume: /tmp/openclaw/uploads/resume.pdf"
echo ""
echo "  Dashboard: ${AUTOAPPLY_API}/dashboard"
echo "  The bot will start applying to jobs automatically."
echo "================================================"
