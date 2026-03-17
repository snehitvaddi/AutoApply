# ApplyLoop — Complete DIY Setup Guide

> Build your own autonomous job application bot from scratch.
> Estimated time: 4-8 hours (technical users) | 1-2 weekends (everyone else)

---

## Prerequisites

Before you begin, you'll need accounts and tools on **8 different platforms**:

- [ ] Python 3.11+ installed
- [ ] Node.js 18+ installed
- [ ] Git installed
- [ ] A Google Cloud Console account (for OAuth + Gmail API)
- [ ] A Supabase account (free tier works)
- [ ] A Vercel account (free tier works)
- [ ] A Hetzner account (CX21 VPS, $18/mo) — or run on your own machine
- [ ] OpenClaw Pro subscription ($20/mo)

---

## Phase 1: Database Setup (12 tables, 18 RLS policies)

### Step 1: Create Supabase project
Go to supabase.com → New Project → Choose region → Wait for provisioning (2-3 min)

### Step 2: Run migration 001 — Core schema
Open SQL Editor → Paste 200+ lines of SQL that creates:
- `users` table (extends Supabase auth)
- `user_profiles` (name, phone, LinkedIn, education, work auth, EEO demographics)
- `user_resumes` (multiple resumes per user with target keywords)
- `user_job_preferences` (target titles, excluded companies, salary, remote-only)
- `discovered_jobs` (normalized jobs from all ATS APIs)
- `user_job_matches` (per-user job relevance scoring)
- `application_queue` (PostgreSQL-based job queue with claim/lock mechanics)
- `applications` (permanent log with screenshot URLs)
- `gmail_tokens` (AES-256-CBC encrypted OAuth tokens)
- `invite_codes` (legacy invite system)
- `knowledge_base` (shared answer templates)
- `system_config` (global key-value configuration)

### Step 3: Run migration 002 — OAuth approval system
Adds `approval_status` column, admin functions (`approve_user()`, `reject_user()`), updated RLS policies so admins can see all users.

### Step 4: Run migration 003 — Worker config + logging
Creates `worker_config` (per-user LLM settings, poll intervals, feature flags) and `worker_logs` (error tracking visible to admin) tables.

### Step 5: Create storage buckets
- `resumes` bucket → **private** (RLS-protected)
- `screenshots` bucket → **public** (signed URLs for Telegram)

### Step 6: Configure Row-Level Security
18 individual RLS policies across all tables:
- Users can only read/write their own data
- Service role bypasses for worker access
- Admin policies for cross-user visibility
- Public read for discovered_jobs and knowledge_base

### Step 7: Create PostgreSQL functions
- `claim_next_job(worker_id)` — atomic job claim with row locking
- `recover_stale_locks()` — reclaims jobs stuck for >10 minutes
- `approve_user(user_id)` — admin approval with timestamp
- `reject_user(user_id)` — admin rejection
- `create_default_worker_config()` — trigger on user creation
- `update_modified_column()` — automatic `updated_at` timestamps

### Step 8: Create indexes
7 composite indexes for query performance:
- `idx_queue_status_priority` on application_queue
- `idx_apps_user_date` on applications
- `idx_jobs_ats_company` on discovered_jobs
- `idx_matches_user_status` on user_job_matches
- `idx_worker_logs_level` on worker_logs
- `idx_worker_logs_unresolved` on worker_logs (partial)
- `idx_worker_logs_user` on worker_logs

### Step 9: Set yourself as admin
```sql
UPDATE users SET approval_status = 'approved', is_admin = true
WHERE email = 'your@email.com';
```

---

## Phase 2: Google OAuth Configuration (5 sub-steps)

### Step 10: Create Google Cloud project
Go to console.cloud.google.com → New Project → Name it "ApplyLoop"

### Step 11: Configure OAuth consent screen
- User type: External
- App name, support email, developer contact
- Scopes: `email`, `profile`, `openid`
- Add test users (your email)

### Step 12: Create OAuth 2.0 Client ID
- Application type: Web application
- Authorized JavaScript origins:
  ```
  https://applyloop.vercel.app
  http://localhost:3000
  ```
- Authorized redirect URIs:
  ```
  https://YOUR-PROJECT.supabase.co/auth/v1/callback
  http://localhost:3000/auth/callback
  ```

### Step 13: Enable Gmail API
- Go to APIs & Services → Library → Search "Gmail API" → Enable
- This is required for reading security codes and OTP emails

### Step 14: Configure Supabase Auth
- Supabase Dashboard → Auth → Providers → Google → Enable
- Paste Client ID and Client Secret from Step 12
- Set Site URL to `https://applyloop.vercel.app`
- Add redirect URLs for both production and localhost

---

## Phase 3: Deploy Web App to Vercel

### Step 15: Fork/clone the repository
```bash
git clone https://github.com/snehitvaddi/AutoApply.git
cd AutoApply
```

### Step 16: Connect to Vercel
- vercel.com → New Project → Import from GitHub
- **Critical:** Set root directory to `packages/web` (not repo root)

### Step 17: Configure 12 environment variables
```
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbG...
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...
NEXT_PUBLIC_APP_URL=https://applyloop.vercel.app
ENCRYPTION_KEY=<openssl rand -hex 32>
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxx
TELEGRAM_BOT_TOKEN=<from @BotFather>
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_STARTER_PRICE_ID=price_xxx
STRIPE_PRO_PRICE_ID=price_xxx
```

### Step 18: Deploy and verify
- Trigger deploy → Wait for build → Test OAuth login
- Verify callback redirects work
- Check that onboarding flow loads

---

## Phase 4: Worker Setup (Python)

### Step 19: Provision your machine
Option A: Hetzner VPS CX21 ($18/mo) — Ubuntu 22.04
Option B: Your local machine (Mac/Windows/Linux)

### Step 20: Install system dependencies
```bash
sudo apt update && sudo apt install -y python3.11 python3-pip nodejs npm git
```

### Step 21: Clone and install Python packages
```bash
cd ~/autoapply
pip install supabase httpx playwright cryptography \
  google-auth google-auth-oauthlib google-api-python-client
python -m playwright install chromium
```

### Step 22: Configure worker .env
Same 12 variables as Vercel, plus:
```
WORKER_ID=worker-1
POLL_INTERVAL=10
APPLY_COOLDOWN=30
RESUME_DIR=/tmp/autoapply/resumes
SCREENSHOT_DIR=/tmp/autoapply/screenshots
```

### Step 23: Test the worker
```bash
cd packages/worker
python worker.py
```
Expected output: "Worker worker-1 started. Polling for jobs..."

---

## Phase 5: Job Scanner Setup

### Step 24: Configure the scanner
The scanner hits 370+ company boards:
- Greenhouse API: 271 companies (Stripe, Airbnb, Anthropic, Coinbase, OpenAI, Waymo, Figma, Notion...)
- Ashby API: 102 companies (Notion, Ramp, Character AI, Harvey, Vercel, Supabase, Cursor, Linear...)
- Lever: 7 companies (Voleon, Nominal, LevelAI...)

### Step 25: Run initial scan
```bash
python -m scanner.run --ats greenhouse
python -m scanner.run --ats ashby
python -m scanner.run --ats lever
```

### Step 26: Set up cron job for 6-hourly scanning
```bash
crontab -e
# Add:
0 */6 * * * cd ~/autoapply/packages/worker && python -m scanner.run >> /tmp/scanner.log 2>&1
```

---

## Phase 6: OpenClaw Browser Automation

### Step 27: Install OpenClaw CLI
```bash
npm install -g openclaw
```

### Step 28: Start the browser gateway
```bash
openclaw gateway start --port 18789
```

### Step 29: Create browser profile
Set up a Chrome profile that OpenClaw controls for form filling.

### Step 30: Configure AI provider
```bash
openclaw config set ai.provider anthropic  # or openai
openclaw config set ai.model claude-sonnet-4-6
openclaw config set ai.apiKey sk-ant-xxx
```

### Step 31: Load the 864 lines of ATS-specific learnings
The agent needs to know every quirk:
- Greenhouse: set country code dropdown BEFORE phone field
- Greenhouse: convert board URLs to embed URLs for direct form access
- Greenhouse: handle 8-character email security codes (poll Gmail, extract code, fill individual boxes)
- Ashby: wait 45 seconds after resume upload (transient lock workaround)
- Ashby: use type() not fill() for React SPA compatibility
- Ashby: press Enter to commit location autocomplete selections
- Ashby: re-snapshot DOM after every combobox interaction (refs go stale)
- Lever: full name field (not first/last split)
- Lever: radio buttons instead of dropdowns
- SmartRecruiters: "Confirm your email" field must be filled twice
- SmartRecruiters: different submit button per page (Next → Submit)
- All platforms: consent/privacy checkboxes auto-agree
- All platforms: location autocomplete requires search + wait + Enter
- All platforms: EEO dropdowns with standardized values

### Step 32: Test with a dry run
```bash
openclaw apply --dry-run --url "https://boards.greenhouse.io/stripe/jobs/12345"
```

---

## Phase 7: Gmail OTP Integration

### Step 33: Set up Gmail OAuth for your app
- In Google Cloud Console → Credentials → Create OAuth Client (Desktop app type)
- Download `credentials.json`

### Step 34: Configure encrypted token storage
Tokens are encrypted at rest using AES-256-CBC with scrypt key derivation.
Format: `salt_hex:iv_hex:ciphertext_hex`

### Step 35: Wire up the verification flow
When the bot encounters "Enter your security code" on a Greenhouse form:
1. Polls Gmail API every 5 seconds
2. Filters by sender (greenhouse-mail.io) and subject
3. Regex extracts code: patterns include "code:", "pin:", "otp:", "verification:"
4. Supports 4-8 digit codes and alphanumeric codes
5. Fills individual character input boxes (8 separate fields)
6. Clicks verify → continues application

### Step 36: Test with a real Greenhouse application that requires email verification
Companies that require it: Stripe, Datadog, Plaid, and others.

---

## Phase 8: Telegram Bot Setup

### Step 37: Create a Telegram bot
Message @BotFather on Telegram → `/newbot` → Save the token

### Step 38: Get your chat ID
Message your bot → Check `https://api.telegram.org/bot<TOKEN>/getUpdates` → Find `chat.id`

### Step 39: Connect in the web dashboard
Settings → Telegram → Paste chat ID → Save

### Step 40: Test notifications
Trigger a test application → Verify Telegram receives:
- Company name, role, ATS platform
- Full-page screenshot attachment
- Application status

---

## Phase 9: Production Hardening

### Step 41: Set up systemd service
```bash
sudo nano /etc/systemd/system/autoapply-worker.service
# Configure ExecStart, Restart=always, Environment vars
sudo systemctl enable autoapply-worker
sudo systemctl start autoapply-worker
```

### Step 42: Configure daily auto-updates
The update script pulls latest code, updates dependencies, and restarts the worker. Runs on login + daily at 3 AM.

### Step 43: Set up error monitoring
Worker logs push to Supabase `worker_logs` table. Admin dashboard shows unresolved errors with one-click resolve.

### Step 44: Configure rate limiting
- Per-ATS cooldowns: Greenhouse 30s, Lever 20s, Ashby 15s, SmartRecruiters 20s
- System-wide: max 60 applications/hour
- Per-user daily limits based on subscription tier
- Exponential idle backoff: 10s → 20s → 40s → 80s → 160s → 300s cap

### Step 45: Set up blocked domains and company pauses
```python
BLOCKED_DOMAINS = ["jobright.ai", "wiraa.com", "indeed.com", ...]
BLOCKED_COMPANIES = ["anduril", "palantir", "lockheed martin", ...]
COMPANY_PAUSES = {"stripe": date(2026, 3, 25), ...}
```

### Step 46: Configure resume routing
Upload multiple resumes with target keywords:
- Resume A: keywords ["AI", "Machine Learning", "NLP"] → AI/ML roles
- Resume B: keywords ["Data", "Analytics", "SQL"] → Data roles
- Resume C: default → everything else

### Step 47: Build your answer key
Create a JSON answer key for common form fields:
```json
{
  "text_fields": {
    "years of experience": "5",
    "linkedin url": "https://linkedin.com/in/...",
    "salary expectations": "150000"
  },
  "dropdown_fields": {
    "work authorization": "H-1B",
    "education level": "Master's"
  }
}
```

### Step 48: Test end-to-end
Apply to 5 real jobs across different ATS platforms:
- 1 Greenhouse job (with security code)
- 1 Ashby job (with location autocomplete)
- 1 Lever job (with radio buttons)
- 1 SmartRecruiters job (multi-page)
- Verify all screenshots received via Telegram

### Step 49: Monitor and iterate
Check the worker logs daily for the first week. Common issues:
- reCAPTCHA blocks (some Greenhouse companies)
- Resume upload failures (retry logic handles most)
- Stale DOM refs on Ashby (re-snapshot fixes this)
- Gateway timeouts (auto-restart after 3 consecutive failures)

### Step 50: Scale
Once stable, increase daily limits and add more company boards to the scanner.

---

## Total Count

- **8** platform accounts required
- **12** environment variables to configure
- **3** database migrations to run
- **12** tables, **18** RLS policies, **7** indexes
- **5** Google OAuth configuration steps
- **864** lines of ATS-specific learnings to load
- **370+** company boards to scan
- **50** setup steps across 9 phases

**Estimated total time: 4-8 hours** (if nothing goes wrong)

---

> **Overwhelmed?** That's normal. This guide exists so you CAN do it yourself.
>
> But if you'd rather have it running in 10 minutes instead of 10 hours —
> **DM me on LinkedIn.** I'll set the whole thing up with you on a quick call.
>
> [@snehitvaddi](https://linkedin.com/in/snehitvaddi)
