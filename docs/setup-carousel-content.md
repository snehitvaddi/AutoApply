# AutoApply Setup Carousel — Slide Content

Design in Canva/Figma. Dark tech aesthetic (charcoal/navy bg, white text, blue/orange accents).
Monospace font for code. Number steps sequentially across ALL slides (Step 1 through 50+).

---

## Slide 1: Title

**AutoApply**
*Full Setup Guide: From Zero to Automated Job Applications*

50+ steps. 5 ATS platforms. 370+ company boards.

Built with OpenClaw + Python + Supabase + Next.js

by @snehitvaddi

---

## Slide 2: Architecture

**How It All Fits Together**

```
[Vercel]                    [Supabase]                   [Your Machine]
Next.js Web App    <--->    PostgreSQL (12 tables)  <--->  Python Worker
Dashboard                   Auth + Storage                 Job Scanner
Settings                    Row-Level Security             OpenClaw Agent
Onboarding                  24 API Routes                  Telegram Bot
Stripe Billing              Gmail Token Vault              Browser Automation
```

- Step 1: Provision Supabase project
- Step 2: Deploy Next.js to Vercel
- Step 3: Configure worker on local machine or VPS

---

## Slide 3: Prerequisites

**Before You Start (Step 4-11)**

- Step 4: Install Python 3.11+
- Step 5: Install Node.js 18+
- Step 6: Install Git
- Step 7: Create Supabase account (free tier)
- Step 8: Create Vercel account (free tier)
- Step 9: Create Google Cloud Console project
- Step 10: Install OpenClaw CLI ($20/mo Pro required)
- Step 11: Provision Hetzner VPS CX21 ($18/mo) — or run locally

**Environment Variables Needed (12):**
```
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
ENCRYPTION_KEY (openssl rand -hex 32)
WORKER_ID
POLL_INTERVAL
APPLY_COOLDOWN
TELEGRAM_BOT_TOKEN
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
STRIPE_SECRET_KEY
OPENAI_API_KEY (or ANTHROPIC_API_KEY)
```

---

## Slide 4: Database Setup

**12 Tables, RLS Policies, Queue Functions (Step 12-19)**

- Step 12: Run migration 001_schema.sql (12 tables)
  - users, user_profiles, user_resumes, user_job_preferences
  - discovered_jobs, user_job_matches, application_queue, applications
  - gmail_tokens, invite_codes, knowledge_base, system_config
- Step 13: Run migration 002_oauth_approval.sql
  - approval_status, admin functions, RLS updates
- Step 14: Run migration 003_worker_config_and_logs.sql
  - worker_config (per-user LLM settings), worker_logs (error tracking)
- Step 15: Create storage buckets
  - `resumes` (private), `screenshots` (public)
- Step 16: Configure Row-Level Security policies (18 policies)
- Step 17: Create PostgreSQL functions
  - claim_next_job(), recover_stale_locks(), approve_user(), reject_user()
- Step 18: Create database indexes (7 composite indexes)
- Step 19: Set yourself as admin
  ```sql
  UPDATE users SET approval_status = 'approved', is_admin = true
  WHERE email = 'your@email.com';
  ```

---

## Slide 5: Google OAuth Configuration

**The Most Painful Part (Step 20-27)**

- Step 20: Go to Google Cloud Console > APIs & Services
- Step 21: Create OAuth consent screen
  - App name, support email, authorized domains
  - Scopes: email, profile, openid
- Step 22: Create OAuth 2.0 Client ID
  - Application type: Web application
  - Authorized redirect URIs:
    ```
    https://your-project.supabase.co/auth/v1/callback
    http://localhost:3000/auth/callback
    ```
- Step 23: Copy Client ID + Client Secret
- Step 24: In Supabase Dashboard > Auth > Providers > Google
  - Enable Google provider
  - Paste Client ID + Secret
  - Set redirect URL
- Step 25: Configure Gmail API access (for OTP reading)
  - Enable Gmail API in Google Cloud
  - Add gmail.readonly scope
- Step 26: Deploy to Vercel
  - Set root directory: `packages/web`
  - Add all 12 environment variables
- Step 27: Verify OAuth login works end-to-end

---

## Slide 6: Worker + Scanner Setup

**Your Autonomous Application Engine (Step 28-35)**

- Step 28: SSH into VPS (or open local terminal)
- Step 29: Clone the repo
  ```bash
  git clone https://github.com/snehitvaddi/AutoApply.git
  ```
- Step 30: Install Python dependencies
  ```bash
  pip install supabase httpx playwright cryptography
  python -m playwright install chromium
  ```
- Step 31: Configure .env with all 12 variables
- Step 32: Start the worker
  ```bash
  python worker.py
  ```
- Step 33: Set up the job scanner (370+ company boards)
  ```bash
  python -m scanner.run --ats greenhouse  # 271 companies
  python -m scanner.run --ats ashby       # 102 companies
  python -m scanner.run --ats lever       # 7 companies
  ```
- Step 34: Configure cron for 6-hourly scanning
  ```bash
  0 */6 * * * cd ~/autoapply && python -m scanner.run
  ```
- Step 35: Set up systemd service for worker auto-restart

---

## Slide 7: OpenClaw Configuration

**The Brain Behind the Browser (Step 36-41)**

- Step 36: Install OpenClaw CLI
  ```bash
  npm install -g openclaw
  ```
- Step 37: Start the browser gateway
  ```bash
  openclaw gateway start --port 18789
  ```
- Step 38: Create browser profile
- Step 39: Configure AI provider (Claude or GPT)
  ```bash
  openclaw config set ai.provider anthropic
  openclaw config set ai.model claude-sonnet-4-6
  ```
- Step 40: Create the agent with SOUL.md instructions
  - 10-step apply workflow
  - 864 lines of ATS-specific learnings
  - Field matching patterns
  - Error recovery procedures
- Step 41: Test with a dry run
  ```bash
  openclaw apply --dry-run --url "https://boards.greenhouse.io/..."
  ```

---

## Slide 8: Gmail OTP Integration

**The Feature No Other Bot Has (Step 42-45)**

When you apply on Greenhouse, some companies (Stripe, Datadog, Plaid) send a security code to your email.

Most bots fail here. AutoApply doesn't.

- Step 42: Set up Gmail OAuth (gmail.readonly scope)
- Step 43: Configure encrypted token storage
  ```
  AES-256-CBC encryption with scrypt key derivation
  Format: salt_hex:iv_hex:ciphertext_hex
  ```
- Step 44: Wire up the verification flow
  ```
  1. Bot detects "Enter security code" on page
  2. Polls Gmail API every 5 seconds
  3. Regex extracts 8-character code from email body
  4. Fills individual character boxes
  5. Continues application
  ```
- Step 45: Test with a Greenhouse company that requires verification

**This alone took 2 weeks to get right.**

---

## Slide 9: What It Handles

**864 Lines of Battle-Tested Learnings (Step 46-49)**

**Greenhouse (271 companies):**
- Phone country dropdown BEFORE phone field (order matters)
- Embed URL bypass for direct form rendering
- 8-character security code flow
- reCAPTCHA detection and handling
- Multi-page EEO sections with consent checkboxes
- Location autocomplete combobox

**Ashby (102 companies):**
- 45-second wait after resume upload (transient lock)
- Enter key to commit location autocomplete
- type() not fill() for React SPA compatibility
- DOM ref instability after combobox interactions

**Lever:**
- Single "Full Name" field (not first/last)
- Radio buttons, not dropdowns
- No EEO section

**SmartRecruiters:**
- "Confirm your email" field (filled twice)
- Multi-page flow with different submit buttons per page

**Workday:**
- Account creation per company (multi-tenant)
- 7-step wizard with CSRF tokens

---

## Slide 10: Results + CTA

**3 Weeks. 900+ Applications. Zero Manual Effort.**

- 50 applications/day on autopilot
- 5 ATS platforms fully automated
- 370+ company job boards scanned every 6 hours
- Gmail OTP verification handled automatically
- Screenshot proof sent via Telegram for every application
- Real-time dashboard tracking every submission

All running locally. Your data never leaves your machine.

**The full guide is 50+ steps.**

Want this running by tonight instead?

**DM me.**

@snehitvaddi
