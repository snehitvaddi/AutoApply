<div align="center">

<img src="https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/packages/desktop/icon.svg" alt="ApplyLoop" width="80" height="80" />

# ApplyLoop

### Your AI job-application assistant that never sleeps.

**You build the profile once. ApplyLoop applies to matching jobs every 30 minutes — automatically, on your Mac — while you live your life.**

<br/>

[![Status](https://img.shields.io/badge/status-private%20beta-blueviolet?style=for-the-badge)](https://applyloop.vercel.app)
[![Platform](https://img.shields.io/badge/platform-macOS-black?style=for-the-badge&logo=apple)](https://applyloop.vercel.app)
[![AI Powered](https://img.shields.io/badge/AI-Claude%20Code-orange?style=for-the-badge)](https://claude.ai/claude-code)
[![License](https://img.shields.io/badge/license-private-red?style=for-the-badge)](#)

<br/>

[**→ Request Access**](https://applyloop.vercel.app) &nbsp;·&nbsp; [**View Demo**](#-how-it-works) &nbsp;·&nbsp; [**Quick Install**](#-install-in-60-seconds)

<br/>

---

</div>

## What is ApplyLoop?

> **Think of it like autopilot for your job search.**

You fill in your resume and preferences **once**. ApplyLoop reads thousands of job listings every day, picks the ones that actually match you, and submits real applications — filling out every field, answering every question — in a real browser, just like you would.

You get a **Telegram photo** of every submitted application. You watch a live dashboard on your Mac. You type questions like *"what did you apply to today?"* and it answers.

**No more copy-pasting resumes. No more filling the same form for the 40th time.**

---

## It's as simple as 3 steps

```
1. Sign up → build your profile → upload your resume
          ↓
2. Get your activation code → paste one command in Terminal
          ↓
3. Double-click ApplyLoop.app → press Start
```

That's it. From here your Mac applies to jobs in the background, every 30 minutes, 24/7.

---

## What you'll see

<div align="center">

### Sign in with Google — takes 30 seconds

<img src="https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/docs/images/01-login-page.png" alt="ApplyLoop login screen" width="480" />

<br/><br/>

### Your live dashboard — track every application in real time

| Stat Card | What it shows |
|---|---|
| **Applied Today** | Applications submitted in the last 24 hours |
| **Total Applied** | All-time applications |
| **In Queue** | Jobs discovered, waiting to be applied to |
| **Success Rate** | % that went through without errors |

The **Pipeline** view shows a Kanban board: `Queued → Applying → Submitted → Failed`.
Every card is a real job. Click any card to see the company, role, and ATS platform.

<br/>

### Chat with it — from your Mac or your phone

Type in the desktop window **or** send a Telegram message:

> *"What companies did you apply to today?"*
> *"Skip anything with 'manager' in the title for the next week."*
> *"Apply only to remote roles for now."*

Same brain, two keyboards.

</div>

---

## Key features

| Feature | What it means for you |
|---|---|
| **Scouts 1,200+ jobs / scan** | Greenhouse, Ashby, Lever, LinkedIn, Workday, SmartRecruiters |
| **Fills every form field** | AI maps your profile to any unfamiliar question format |
| **Telegram screenshots** | Get a photo of every submitted application to your phone |
| **Live Kanban dashboard** | Watch jobs move from queued → submitted in real time |
| **Chat control** | Ask questions or give instructions in plain English |
| **Auto-dedup** | Never applies to the same job twice |
| **ATS support** | Greenhouse · Ashby · Lever · SmartRecruiters · Workday |
| **Auto-updates** | Pulls latest version every night at 3 AM — no manual updates |
| **Your data stays local** | Applications stored on your Mac in SQLite, not in the cloud |

---

## Install in 60 seconds

**Step 1** — Go to [applyloop.vercel.app](https://applyloop.vercel.app), sign in, fill your profile, and wait for approval. You'll receive an activation code that looks like `AL-XXXX-XXXX`.

**Step 2** — Open **Terminal** on your Mac and run:

```bash
curl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh \
  | bash -s -- AL-XXXX-XXXX
```

*(The [setup page](https://applyloop.vercel.app/setup-complete) generates this command with your code already filled in — just copy and paste.)*

**Step 3** — When the install finishes, double-click **ApplyLoop** in `/Applications` and press **Start ApplyLoop**.

> The first scouting run starts within 30 seconds. You'll see jobs flowing into the Queued column almost immediately.

---

## Requirements

- **macOS** (Intel or Apple Silicon) — Windows coming soon
- **Claude Code CLI** — [get it here](https://claude.ai/claude-code), free to install
- **Telegram account** — optional but strongly recommended for notifications

---

## Supported job platforms

### Where it finds jobs

| Platform | Jobs available |
|---|---|
| Greenhouse API | 271+ company boards |
| Ashby API | 102+ company boards |
| LinkedIn | 1,200+ jobs per scan |
| Lever | ~7 active companies |
| Himalayas / Indeed / ZipRecruiter | Supplemental feed |

### Where it submits applications

| Platform | Status |
|---|---|
| Greenhouse | Full support |
| Ashby | Full support |
| Lever | Full support |
| SmartRecruiters | Full support |
| Workday | Partial (account creation required) |

---

## Daily use

Just leave the app running in the background. It will:

- Scout matching jobs every 30 minutes
- Submit applications one at a time with a short cooldown between each
- Send a Telegram photo of every submitted form
- Flag anything unusual (CAPTCHAs, login prompts, stuck jobs) as a card on the dashboard

**You control it by chatting.** Examples:

```
"What companies did you apply to today?"
"Pause applying for 2 hours"
"Scout now"
"Don't apply to any companies with fewer than 100 employees"
"Show me what's in the queue"
```

---

## Roadmap

- [x] Greenhouse, Ashby, Lever, SmartRecruiters appliers
- [x] LinkedIn scouting (Voyager API)
- [x] Telegram integration (notifications + chat control)
- [x] Live Kanban dashboard
- [x] CLIENT.md personal overrides (survive updates)
- [ ] Windows installer
- [ ] Apple code signing (no right-click needed)
- [ ] Stripe auto-activation on payment
- [ ] Mobile-friendly web dashboard

---

<details>
<summary><strong>🏗️ How it's built (for developers)</strong></summary>

<br/>

Three processes, one cloud store, one local cache:

```
                   ┌─────────────────────────────────┐
                   │      applyloop.vercel.app        │
                   │      (Next.js 14, SSR)           │
                   │  Signup · Onboarding · Admin     │
                   └────────┬───────────┬─────────────┘
                            │           │
                    Google  │           │ service-role
                    OAuth   │           │
                            ▼           ▼
                   ┌─────────────────────────────────┐
                   │           Supabase              │
                   │  Postgres · Auth · Storage      │
                   └────────────────┬────────────────┘
                                    │
                                    │ /api/worker/proxy
                                    │ (X-Worker-Token)
       ┌────────────────────────────┴────────────────────────┐
       │                                                     │
┌──────▼──────────────────────────────┐   ┌─────────────────▼───────────────┐
│   ApplyLoop.app (FastAPI + pywebview│   │   Worker (subprocess)           │
│   localhost:18790)                  │   │                                 │
│                                     │   │   scanner/ (8 sources)          │
│   Dashboard · Pipeline · Chat       │   │   applier/ (5 ATS platforms)    │
│   Terminal · Settings               │   │   db.py (SQLite dual-write)     │
└────────────────┬────────────────────┘   └────────────────┬────────────────┘
                 │                                         │
                 └──────────────┬──────────────────────────┘
                                ▼
                   ~/.autoapply/workspace/applications.db
                   (SQLite WAL — local source of truth)
```

### Repo layout

```
AutoApply/
├── packages/
│   ├── web/        Next.js 14 → Vercel (landing, onboarding, admin)
│   ├── desktop/    FastAPI + Next static + pywebview (.app bundle)
│   │   ├── server/ FastAPI routes, PTY manager, chat bridge, WebSockets
│   │   └── ui/     Next.js dashboard (pipeline, jobs, chat, terminal)
│   └── worker/     Python applier + scanner (runs as subprocess)
├── supabase/
│   └── migrations/ 001–009 schema files
├── knowledge/      ATS patterns, Voyager guide, email-services notes
└── install.sh      One-liner installer (validates code, installs deps, builds .app)
```

### Dev setup

```bash
git clone https://github.com/snehitvaddi/AutoApply.git
cd AutoApply

# Web
cd packages/web && npm install
cp .env.example .env.local   # fill in Supabase + Google OAuth keys
npm run dev                  # → http://localhost:3000

# Desktop
cd packages/desktop && pip install -r requirements.txt
APPLYLOOP_WORKSPACE=/tmp/dev python3 launch.py
# → http://localhost:18790

# Worker (optional)
cd packages/worker && pip install -r requirements.txt
WORKER_TOKEN=al_xxx_yyy python3 worker.py
```

### Environment variables

<details>
<summary>Vercel (packages/web)</summary>

| Var | Purpose |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role (server-only) |
| `ENCRYPTION_KEY` | `openssl rand -hex 32` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth credentials |
| `TELEGRAM_BOT_TOKEN` | Admin activation-code DMs |
| `NEXT_PUBLIC_APP_URL` | `https://applyloop.vercel.app` |

</details>

<details>
<summary>Desktop / Worker</summary>

| Var | Purpose |
|---|---|
| `APPLYLOOP_WORKSPACE` | Per-user state dir (default `~/.autoapply/workspace`) |
| `APPLYLOOP_PORT` | FastAPI port (default 18790) |
| `WORKER_TOKEN` | API token (written by setup wizard) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Opt-in Telegram gateway |
| `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` | OTP reading via Himalaya CLI |

</details>

### Security model

- Users **never hold Supabase keys** — only a worker token hashed server-side
- Activation codes are **time-limited (7 days) and use-limited (5 uses)**
- Desktop app **creates no quarantine bits** (built locally by the install script, not downloaded as a binary)
- All job details **stay on your Mac** in SQLite — cloud only gets aggregate counts

</details>

<details>
<summary><strong>🔧 Update, uninstall, and advanced install</strong></summary>

<br/>

### Updating

```bash
applyloop update
```

Pulls latest from `main`, rebuilds the UI, and regenerates the `.app`. Also runs nightly at 3 AM automatically.

### Uninstalling

```bash
applyloop uninstall
```

Removes `~/.applyloop`, `/Applications/ApplyLoop.app`, the launchd plist, and the CLI shim. Your workspace at `~/.autoapply` is preserved — delete it manually for a complete wipe.

### Non-interactive install (CI / scripted)

```bash
APPLYLOOP_CODE=AL-X1Y2-Z3W4 \
APPLYLOOP_TELEGRAM_CHAT_ID=123456789 \
APPLYLOOP_SKIP_PROMPTS=1 \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh)"
```

### CLIENT.md — your personal overrides

After install, edit `~/.applyloop/CLIENT.md` to add instructions that apply only to you and survive all updates:

```markdown
# My personal rules
Never apply to: Acme Corp, Boring Inc
Skip any role with "Manager" in the title — IC roles only.
Remote-only. Reject anything requiring relocation.
If a form asks for expected salary, enter 130000.
```

</details>

<details>
<summary><strong>👤 For admins</strong></summary>

<br/>

Log in at [applyloop.vercel.app](https://applyloop.vercel.app) and navigate to `/admin`. You need `users.is_admin = true` set in Supabase (set it once via SQL).

From `/admin` you can:
- Approve pending signups
- Generate activation codes (`AL-XXXX-XXXX`) — auto-DMs the user on Telegram
- View live worker heartbeats and per-user stats
- Revoke worker tokens instantly

### Migrations

```bash
export SUPABASE_DB_URL="postgresql://postgres.PROJECT_REF:PASSWORD@..."
cd packages/web && node scripts/migrate.mjs
```

</details>

---

<div align="center">

**Built with [Claude Code](https://claude.ai/claude-code)**

[Request Access](https://applyloop.vercel.app) &nbsp;·&nbsp; [Report a Bug](https://github.com/snehitvaddi/AutoApply/issues) &nbsp;·&nbsp; Private beta — invite only

</div>
