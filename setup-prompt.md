# AutoApply — Setup Prompt (runs on user's machine)

Run this with: `claude --dangerously-skip-permissions "$(cat setup-prompt.md)"`

You are setting up AutoApply for a user who has already completed onboarding on the web dashboard (autoapply.app). Their profile, preferences, and resume are stored in Supabase. Follow every step exactly.

**CRITICAL: Before doing anything, read these files first:**
1. `~/autoapply/knowledge/HANDOVER.md` — Complete knowledge transfer with battle-tested code, field maps, platform quirks
2. `~/autoapply/knowledge/learnings.md` — 700+ lines of ATS-specific patterns learned from 900+ applications
3. `~/autoapply/knowledge/answer-key-template.json` — Template for auto-filling ALL form fields

These contain hard-won knowledge from 900+ real applications across 4 ATS platforms. Do NOT skip them.

---

## Phase 1: Authenticate with AutoApply Backend

The user should already be logged in on the web dashboard. We need their API token.

```bash
# Ask the user for their AutoApply API token
# They can get it from: autoapply.app/dashboard/settings → API Token section
echo "Enter your AutoApply API token:"
read -s AUTOAPPLY_TOKEN

# Verify token and download profile
curl -s -H "Authorization: Bearer $AUTOAPPLY_TOKEN" \
  https://autoapply.app/api/settings/profile > /tmp/autoapply-profile.json

# Check if token worked
if jq -e '.data.first_name' /tmp/autoapply-profile.json > /dev/null 2>&1; then
  echo "Authenticated as: $(jq -r '.data.first_name + " " + .data.last_name' /tmp/autoapply-profile.json)"
else
  echo "ERROR: Invalid token. Get your token from autoapply.app/dashboard/settings"
  exit 1
fi
```

## Phase 2: Install OpenClaw

OpenClaw is the browser automation engine that fills forms and clicks buttons.

```bash
# macOS / Linux
npm install -g openclaw
```

Verify: `openclaw --version` should return `2026.x.x`.

If already installed, skip to Phase 3.

## Phase 3: Configure OpenClaw

### 3a. Start the Gateway (browser automation server)

```bash
openclaw gateway --port 18789 &
openclaw gateway status
```

If it says "running", continue. If not, run `openclaw gateway --force --port 18789`.

### 3b. Start the Browser

```bash
openclaw browser create-profile autoapply
openclaw browser start --browser-profile autoapply
```

Verify: `openclaw browser status` should show the browser running.

### 3c. Create an OpenClaw Agent

```bash
openclaw agents add autoapply \
  --workspace ~/.autoapply/workspace \
  --model openai/gpt-4o \
  --non-interactive
```

## Phase 4: Download User Profile from Backend

```bash
mkdir -p ~/.autoapply/workspace

# Download and save profile
curl -s -H "Authorization: Bearer $AUTOAPPLY_TOKEN" \
  https://autoapply.app/api/settings/profile | jq '.data' > ~/.autoapply/workspace/profile.json

# Download and save preferences
curl -s -H "Authorization: Bearer $AUTOAPPLY_TOKEN" \
  https://autoapply.app/api/settings/preferences | jq '.data' > ~/.autoapply/workspace/preferences.json

# Download resume
curl -s -H "Authorization: Bearer $AUTOAPPLY_TOKEN" \
  https://autoapply.app/api/onboarding/resume/download -o /tmp/openclaw/uploads/resume.pdf
mkdir -p /tmp/openclaw/uploads
```

## Phase 5: Generate PROFILE.md and Answer Key

Using the downloaded profile data, generate the local files:

```bash
# Generate PROFILE.md from profile.json
python3 -c "
import json
p = json.load(open('$HOME/.autoapply/workspace/profile.json'))
md = f'''# User Profile

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

## Authorization
- **Work Authorization:** {p.get('work_authorization','')}
- **Requires Sponsorship:** {p.get('requires_sponsorship','')}
'''
open('$HOME/.autoapply/workspace/PROFILE.md', 'w').write(md)
print('PROFILE.md generated')
"
```

Then generate the answer key from the template:

```bash
# If answer_key_json is already in profile, use it directly
python3 -c "
import json
p = json.load(open('$HOME/.autoapply/workspace/profile.json'))
ak = p.get('answer_key_json', {})
if ak:
    json.dump(ak, open('$HOME/.autoapply/workspace/answer-key.json', 'w'), indent=2)
    print('answer-key.json loaded from backend')
else:
    # Fall back to template
    tmpl = json.load(open('$HOME/autoapply/knowledge/answer-key-template.json'))
    # Replace placeholders
    replacements = {
        '{first_name}': p.get('first_name',''),
        '{last_name}': p.get('last_name',''),
        '{email}': p.get('email',''),
        '{phone}': p.get('phone',''),
        '{linkedin_url}': p.get('linkedin_url',''),
        '{github_url}': p.get('github_url',''),
    }
    s = json.dumps(tmpl)
    for k, v in replacements.items():
        s = s.replace(k, str(v))
    json.dump(json.loads(s), open('$HOME/.autoapply/workspace/answer-key.json', 'w'), indent=2)
    print('answer-key.json generated from template')
"
```

## Phase 6: Copy Knowledge Base

```bash
cp ~/autoapply/knowledge/learnings.md ~/.autoapply/workspace/learnings.md
cp -r ~/autoapply/knowledge/ats-guides ~/.autoapply/workspace/ats-guides 2>/dev/null || true
```

## Phase 7: Create SOUL.md (Agent Instructions)

Write `~/.autoapply/workspace/SOUL.md` using the profile data:

```bash
FIRST_NAME=$(jq -r '.first_name' ~/.autoapply/workspace/profile.json)
LAST_NAME=$(jq -r '.last_name' ~/.autoapply/workspace/profile.json)

cat > ~/.autoapply/workspace/SOUL.md << SOULEOF
# SOUL.md - AutoApply Agent

You are **AutoApply Agent** -- an autonomous job application bot for **$FIRST_NAME $LAST_NAME**.

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
```

## Phase 8: Test Run

```bash
# Verify browser automation works
openclaw browser open "https://boards.greenhouse.io/embed/job_app?for=example&token=test"
sleep 3
openclaw browser snapshot --efficient --interactive
# If snapshot returns form fields, the setup is working
```

## Phase 9: Done!

Tell the user:

"AutoApply is set up on your machine! Here's what you have:

1. **OpenClaw** is installed and running (browser automation engine)
2. **Your profile** was downloaded from the dashboard
3. **Answer key** is generated at ~/.autoapply/workspace/answer-key.json
4. **Resume** is staged at /tmp/openclaw/uploads/resume.pdf
5. **Knowledge base** with 700+ lines of ATS patterns is ready

The bot will now start discovering and applying to jobs matching your preferences.

To check status: Visit autoapply.app/dashboard
To talk to the bot: Use Codex or Claude Code in this terminal"
