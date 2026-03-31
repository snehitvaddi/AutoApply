# ApplyLoop

Automated job applications for AI/ML engineers. Invite-only SaaS — supports Greenhouse, Ashby, Lever, SmartRecruiters, and Workday.

## Documentation

- **[Client Onboarding Guide](docs/CLIENT-ONBOARDING.md)** — Visual step-by-step for new users (10 min setup)
- **[Subscription & Tools Guide](docs/SUBSCRIPTION-GUIDE.md)** — What users and operators need (and don't need)

## Architecture

ApplyLoop uses a hybrid LLM approach: the web app handles onboarding and profile management, while the Python worker uses OpenClaw's browser automation with LLM-assisted field mapping for intelligent form filling.

```
Vercel              Supabase               Hetzner VPS
┌──────────┐       ┌──────────────┐       ┌─────────────────┐
│ Next.js  │──────>│ PostgreSQL   │<──────│ Python Workers  │
│ Web App  │       │ Auth (OAuth) │       │ Job Scanner     │
│ API      │       │ Storage      │       │ Form Filler     │
└──────────┘       └──────────────┘       │ Gmail Reader    │
                                          │ Telegram Bot    │
                                          └─────────────────┘
```

## Quick Setup (New Deployment)

### Prerequisites
- Node.js 18+
- Python 3.11+
- Supabase account (free tier)
- Vercel account (free tier)
- Google Cloud Console access (for OAuth)
- GitHub account

### Step 1: Clone & Install

```bash
git clone https://github.com/snehitvaddi/AutoApply.git
cd AutoApply/packages/web
npm install
```

### Step 2: Create Supabase Project

1. Go to [supabase.com](https://supabase.com) → New Project
2. Save these values:
   - Project URL: `https://xxxxx.supabase.co`
   - Anon Key: `eyJ...`
   - Service Role Key: `eyJ...`
   - Database Password

### Step 3: Run Database Migrations

Connect to your Supabase database and run:

```bash
psql "postgresql://postgres:{password}@db.{ref}.supabase.co:5432/postgres" \
  -f supabase/migrations/001_schema.sql

psql "postgresql://postgres:{password}@db.{ref}.supabase.co:5432/postgres" \
  -f supabase/migrations/002_oauth_approval.sql

psql "postgresql://postgres:{password}@db.{ref}.supabase.co:5432/postgres" \
  -f supabase/migrations/003_worker_config_and_logs.sql

psql "postgresql://postgres:{password}@db.{ref}.supabase.co:5432/postgres" \
  -f supabase/migrations/004_ai_cli_mode.sql
```

This creates 12+ tables, RLS policies, queue functions, worker config, application logs, and indexes.

### Step 4: Create Storage Buckets

In Supabase Dashboard → Storage:
1. Create bucket `resumes` (private)
2. Create bucket `screenshots` (public)

### Step 5: Set Up Google OAuth

**Google Cloud Console:**
1. Create project → APIs & Services → OAuth consent screen → External
2. Add authorized domains: `supabase.co`, `your-app.vercel.app`
3. Scopes: `email`, `profile`
4. Create OAuth Client ID (Web application):
   - Authorized JS origins: `https://your-app.vercel.app`, `http://localhost:3000`
   - Authorized redirect URI: `https://xxxxx.supabase.co/auth/v1/callback`
5. Save Client ID and Client Secret

**Supabase Dashboard:**
1. Authentication → Providers → Google → Enable
2. Paste Client ID and Client Secret
3. Save

**Supabase Dashboard → Authentication → URL Configuration:**
1. Site URL: `https://your-app.vercel.app`
2. Redirect URLs: `https://your-app.vercel.app/auth/callback`, `http://localhost:3000/auth/callback`

### Step 6: Deploy to Vercel

```bash
cd packages/web
vercel --prod
```

Set environment variables (via `vercel env add` or Vercel Dashboard):

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xxxxx.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Your anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Your service role key |
| `NEXT_PUBLIC_APP_URL` | `https://your-app.vercel.app` |
| `ENCRYPTION_KEY` | Run `openssl rand -hex 32` |
| `GOOGLE_CLIENT_ID` | From Step 5 |
| `GOOGLE_CLIENT_SECRET` | From Step 5 |
| `STRIPE_SECRET_KEY` | From Stripe (optional) |
| `STRIPE_WEBHOOK_SECRET` | From Stripe (optional) |
| `STRIPE_STARTER_PRICE_ID` | From Stripe (optional) |
| `STRIPE_PRO_PRICE_ID` | From Stripe (optional) |
| `TELEGRAM_BOT_TOKEN` | From BotFather (optional) |

Redeploy after setting env vars:
```bash
vercel --prod
```

### Step 7: Make Yourself Admin

After signing in for the first time, run:

```sql
UPDATE users SET approval_status = 'approved', is_admin = true
WHERE email = 'your@email.com';
```

### Step 8: Complete Onboarding

1. Go to your deployed app URL
2. Sign in with Google
3. Complete the 5-step onboarding:
   - **AI Import** — paste ChatGPT/Claude response to auto-fill profile
   - **Personal Info** — name, phone, LinkedIn, GitHub
   - **Work & Education** — company, title, experience, authorization
   - **Job Preferences** — select target roles, excluded companies, salary
   - **Resume** — upload PDF (tag with target roles for smart routing)

### Step 9: Set Up Worker (Optional — for auto-applying)

On a VPS (Hetzner CX21 recommended, $18/mo):

```bash
cd packages/worker
pip install -r requirements.txt

# Set environment variables
export SUPABASE_URL="https://xxxxx.supabase.co"
export SUPABASE_SERVICE_KEY="eyJ..."
export WORKER_ID="worker-1"

# Run worker
python worker.py
```

For production, use systemd:
```bash
sudo cp systemd/applyloop-worker@.service /etc/systemd/system/
sudo systemctl enable applyloop-worker@1
sudo systemctl start applyloop-worker@1
```

### Step 10: Set Up Job Scanner (Optional)

The scanner discovers jobs from public ATS APIs every 6 hours:

```bash
cd packages/worker
python -m scanner.run  # or set up as cron
```

Add to crontab:
```
0 */6 * * * cd /path/to/AutoApply/packages/worker && python -m scanner.run
```

## Updating

Run `applyloop-update` (or the `/update` command) to pull the latest worker code, ATS patterns, and dependencies without re-running full setup. See [Client Onboarding Guide](docs/CLIENT-ONBOARDING.md#keeping-applyloop-updated) for details.

## User Flow

```
Sign in with Google
        ↓
  Pending Approval ← Admin approves from /admin
        ↓
    Onboarding (5 steps)
        ↓
     Dashboard
    ┌────┴────┐
    │         │
  Jobs    Applications
(matches)  (history)
    │
    ↓
Auto-apply (worker fills forms, sends Telegram notifications)
```

## Settings

After onboarding, users can update everything from `/dashboard/settings`:

| Tab | What it does |
|-----|--------------|
| AI Import | Paste ChatGPT/Claude JSON to auto-fill all fields |
| Personal Info | Name, phone, LinkedIn, GitHub, portfolio |
| Work & Education | Company, title, experience, education, authorization, EEO |
| Job Preferences | Target roles (chip selector), excluded companies, salary, auto-apply toggle |
| Resumes | Upload multiple resumes tagged by role type (AI Engineer, Data Scientist, etc.) |
| Telegram | Connect for real-time application notifications |
| Billing | View/change subscription tier |

## Supported ATS Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Greenhouse | Full support | Embed URL bypass, email security codes, reCAPTCHA detection |
| Ashby | Full support | 45s upload wait, Enter for location, type (not fill) |
| Lever | Full support | Single-page, full name field, radio buttons |
| SmartRecruiters | Full support | Confirm email, multi-page flow |
| Workday | Partial | Account creation required, 7-step wizard |

## Job Discovery Sources

| Source | Auth Required | Coverage |
|--------|--------------|----------|
| Greenhouse API | No | 271+ company boards |
| Ashby API | No | 102+ company boards |
| Lever API | No | ~7 active companies |
| LinkedIn Voyager API | Yes (session) | 1200+ jobs per scrape |

## Project Structure

```
ApplyLoop/
├── packages/
│   ├── web/                    # Next.js 14 (Vercel)
│   │   ├── src/app/
│   │   │   ├── auth/           # Login, callback, pending, rejected
│   │   │   ├── onboarding/     # 5-step wizard
│   │   │   ├── dashboard/      # Overview, jobs, applications, settings
│   │   │   ├── admin/          # User management
│   │   │   └── api/            # API routes (admin, auth, health, jobs, onboarding, settings, stripe)
│   │   └── src/lib/            # Auth, Supabase, Stripe, rate limiting
│   │
│   └── worker/                 # Python (VPS)
│       ├── worker.py           # Queue consumer with idle backoff
│       ├── applier/            # Greenhouse, Ashby, Lever, SmartRecruiters
│       ├── scanner/            # ATS API job discovery
│       ├── db.py               # Supabase client + resume routing
│       ├── notifier.py         # Telegram notifications
│       ├── gmail_reader.py     # Verification code reading
│       └── config.py           # Rate limits, blocked domains, pauses
│
├── knowledge/                  # Shared knowledge base
│   ├── learnings.md            # 800+ lines of ATS patterns
│   ├── linkedin-voyager-api.md # Voyager API guide
│   ├── email-services.md       # AgentMail, Gmail, OAuth
│   └── answer-key-template.json
│
└── supabase/
    └── migrations/             # Database schema (001-004: schema, oauth, worker config, AI/CLI mode)
```

## Pricing Tiers

| Tier | Daily Limit |
|------|-------------|
| Free | 5 applications/day |
| Starter | 25 applications/day |
| Pro | 50 applications/day |

> DM for current pricing — flexible plans available.

## Troubleshooting

**OAuth redirect goes to wrong site:** Check Supabase → Auth → URL Configuration → Site URL matches your Vercel URL.

**"Unable to exchange external code":** Client Secret in Supabase doesn't match Google Cloud Console. Re-copy it.

**User stuck on "Pending Approval":** Run SQL: `UPDATE users SET approval_status = 'approved' WHERE email = '...'`

**Worker not picking up jobs:** Check `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` env vars. Verify `application_queue` has pending rows.

**Resume upload fails:** Verify `resumes` storage bucket exists in Supabase and is set to private.
