# ApplyLoop

Automated job applications for AI/ML engineers — a hybrid SaaS that runs locally on your Mac and syncs to the cloud. Supports Greenhouse, Ashby, Lever, SmartRecruiters, and Workday.

**Status:** private beta, invite-only. [Download v1.0.0](https://github.com/snehitvaddi/AutoApply/releases/latest).

---

## What it does

You sign in once at [applyloop.vercel.app](https://applyloop.vercel.app), build your profile, upload a resume, and wait for admin approval. When approved you get an activation code (`AL-XXXX-XXXX`) on Telegram or email. You paste that into the ApplyLoop desktop app on your Mac. The app then:

- Scouts jobs every 30 minutes from Greenhouse, Ashby, Lever, SmartRecruiters, Workday APIs + LinkedIn Voyager
- Filters against your preferences, deduplicates, queues the promising ones
- Applies to them in a real browser (Playwright) using an LLM to map your profile onto unfamiliar form fields
- Sends you a Telegram screenshot of every submitted application
- Streams everything into a local Kanban dashboard so you can watch and steer

You chat with it from either the desktop window or your phone (Telegram) — both channels pipe into the same Claude Code session, so it's one brain with two keyboards.

---

## How it's built

Three processes, one cloud store, one local cache:

```
                   ┌─────────────────────────────────┐
                   │        applyloop.vercel.app     │
                   │         (Next.js 14, SSR)       │
                   │                                 │
                   │  • Landing, signup, onboarding  │
                   │  • /admin (activation codes,    │
                   │     approvals, user management) │
                   │  • /api/activate (public)       │
                   │  • /api/worker/proxy (X-Token)  │
                   │  • /api/me/activation-code      │
                   └────────┬───────────┬────────────┘
                            │           │
                    Google  │           │ service-role
                    OAuth   │           │ (never sees user)
                            ▼           ▼
                   ┌─────────────────────────────────┐
                   │          Supabase               │
                   │  Postgres + Auth + Storage      │
                   │                                 │
                   │  users, user_profiles,          │
                   │  user_job_preferences,          │
                   │  user_resumes,                  │
                   │  activation_codes,              │
                   │  worker_tokens, applications,   │
                   │  discovered_jobs, ...           │
                   └────────────────┬────────────────┘
                                    │
                                    │  all traffic via
                                    │  /api/worker/proxy
                                    │  with X-Worker-Token
                                    │
       ┌────────────────────────────┴─────────────────────────────┐
       │                                                          │
┌──────▼─────────────────────────────────┐      ┌─────────────────▼───────────────────┐
│     User's Mac — ApplyLoop.app         │      │    User's Mac — worker (subprocess) │
│     (FastAPI + Next static + pywebview)│      │                                     │
│                                        │      │    worker.py (long-running)         │
│  localhost:18790                       │      │      ├─ scanner/ (6 sources)        │
│                                        │      │      ├─ applier/ (5 ATS platforms)  │
│  ┌─────────────────────────────────┐   │      │      ├─ db.py (dual-write)          │
│  │  Setup wizard → activate code   │   │      │      └─ notifier.py (Telegram)      │
│  │  Dashboard (stats, daily, ATS)  │   │      │                                     │
│  │  Kanban pipeline                │   │      │    pipeline.py (CLI)                │
│  │  Chat (+ Telegram mirror)       │   │      │                                     │
│  │  Terminal (Claude Code PTY)     │   │      └────────────────┬────────────────────┘
│  │  Settings                       │   │                       │
│  └─────────────────────────────────┘   │                       │
│                                        │   dual-write          │
│           ┌──────────┐                 │   via packages/       │
│           │ QA agent │────────┐        │   worker/db.py        │
│           │(Telegram)│        │        │                       │
│           └──────────┘        │        │                       │
└────────────────┬──────────────┼────────┘                       │
                 │              │                                │
                 │              ▼                                ▼
                 │      ┌──────────────────────────────────────────┐
                 │      │  ~/.autoapply/workspace/applications.db  │
                 │      │  (SQLite, WAL, per-workspace isolated)   │
                 │      └──────────────────────────────────────────┘
                 │
                 └──→ Telegram Bot API (long-poll)
```

### Key design choices

- **Users never hold Supabase keys.** The desktop app only ever has an activation-minted worker token, stored at `~/.autoapply/workspace/.api-token` (0600 perms). Every cloud operation is a POST to `/api/worker/proxy` with `X-Worker-Token`, which the Next.js API validates by SHA256 lookup against `worker_tokens.token_hash` and then executes with service-role under the derived `user_id`.
- **Local SQLite is the hot cache.** The desktop dashboard reads from `applications.db` directly — no round-trips. The worker dual-writes to both the local DB and Supabase so the cloud stays in sync for multi-device and admin visibility.
- **Multi-tenant isolation via `APPLYLOOP_WORKSPACE`.** Every file (DB, token, profile, Telegram offset, install id) is scoped to the workspace directory. Two concurrent desktop instances on one machine (tested) don't collide.
- **One brain, two keyboards.** Chat UI and Telegram both route into the same `claude --print` Q&A subprocess with a SQLite context snapshot. The apply-loop PTY is separate from the Q&A pipeline so terminal noise can't contaminate replies.

---

## For users — install and run

### Install the desktop app

1. Go to [github.com/snehitvaddi/AutoApply/releases/latest](https://github.com/snehitvaddi/AutoApply/releases/latest)
2. Download `ApplyLoop-1.0.0.dmg` (~15 MB, SHA256 sidecar published next to it)
3. Verify the hash (recommended):
   ```bash
   shasum -a 256 ~/Downloads/ApplyLoop-1.0.0.dmg
   # compare against the .sha256 file on the release page
   ```
4. Double-click the `.dmg`, drag `ApplyLoop.app` to `/Applications`
5. First launch: right-click → **Open** (one-time Gatekeeper prompt; the app is not Apple-signed yet)

### Activate

- Sign in at [applyloop.vercel.app](https://applyloop.vercel.app)
- Complete the 5-step onboarding (personal info, work, preferences, resume)
- Wait for admin approval → you'll receive an activation code (`AL-XXXX-XXXX`) on Telegram or email
- Paste that code into the ApplyLoop desktop wizard on first launch
- Dashboard loads with your profile already populated — you're done

### Daily use

Just leave the desktop app running. It will:
- Scout jobs every 30 minutes in the background
- Apply to matches one at a time with a 30-second cooldown between submissions
- Send Telegram screenshots of each submission
- Surface anything weird (Workday captchas, login prompts, stuck jobs) as cards on the dashboard

Chat with it in the app window or on Telegram — both work, both talk to the same LLM. Ask things like *"what companies did you apply to today?"*, *"pause for an hour"*, *"scout now"*.

### Requirements

- macOS (Intel or Apple Silicon). Windows installer coming.
- [Claude Code CLI](https://claude.com/product/claude-code) installed and logged in (needed for the Q&A + apply loop)
- Telegram account (optional but recommended for notifications + remote control)

---

## For admins

Log in as yourself at `applyloop.vercel.app`, then go to `/admin`. You need `users.is_admin = true` in Supabase — set it manually the first time via SQL:

```sql
UPDATE users SET is_admin = true WHERE email = 'you@yourdomain.com';
```

From `/admin` you can:
- See pending signups → click **Approve** → sets `approval_status='approved'`
- Click **Generate Activation Code** → mints an `AL-XXXX-XXXX` with a 7-day TTL and 5 uses, auto-DMs the user if they have `telegram_chat_id` set
- View live worker heartbeats, worker logs, stats per user
- Manage legacy invite codes and worker tokens (behind a "Show legacy tools" toggle)

The activation code flow is intentionally decoupled from payment — you verify payment manually (Stripe is a placeholder at `/api/webhooks/stripe`, wired up in Phase 5) and then generate a code. Each code is single-user + usage-limited, so stolen codes have a limited blast radius.

---

## For developers

### Repo layout

```
AutoApply/
├── packages/
│   ├── web/               Next.js 14 App Router → Vercel (applyloop.vercel.app)
│   │   ├── src/app/
│   │   │   ├── auth/              login, callback, pending, rejected
│   │   │   ├── onboarding/        5-step wizard (profile, work, prefs, resume)
│   │   │   ├── dashboard/         user's cloud dashboard
│   │   │   ├── setup-complete/    post-onboarding download + activation code page
│   │   │   ├── admin/             admin control plane
│   │   │   └── api/
│   │   │       ├── activate/              public — redeem AL-XXXX-XXXX
│   │   │       ├── admin/activation-code/ mint codes, auto-Telegram DM
│   │   │       ├── me/activation-code/    self-serve code lookup
│   │   │       ├── worker/proxy/          worker's only DB path
│   │   │       ├── onboarding/*/          profile, preferences, resume upload
│   │   │       ├── auth/*/                session status, callbacks
│   │   │       ├── updates/check/         desktop auto-update metadata
│   │   │       └── webhooks/stripe/       placeholder for Phase 5
│   │   ├── scripts/
│   │   │   ├── migrate.mjs                runs SQL migrations during Vercel build
│   │   │   └── compute-setup-checksums.mjs  generates src/generated/setup-checksums.ts
│   │   └── src/lib/                auth, admin, rate-limit, telegram, supabase, api-response
│   │
│   ├── desktop/           ApplyLoop.app — FastAPI + Next static + pywebview
│   │   ├── launch.py             entry point (spawns uvicorn + pywebview window)
│   │   ├── build.py              .app + .dmg packager (arch-aware)
│   │   ├── server/
│   │   │   ├── app.py                    FastAPI routes (health, stats, pipeline,
│   │   │   │                             setup, pty, worker, profile, activity)
│   │   │   ├── config.py                 APPLYLOOP_WORKSPACE, TOKEN_FILE, APP_URL
│   │   │   ├── local_data.py             SQLite reader (auto-bootstraps schema)
│   │   │   ├── stats.py                  cloud proxy (with 401 detection)
│   │   │   ├── process_manager.py        worker subprocess lifecycle
│   │   │   ├── pty_terminal.py           Claude Code PTY + session manager
│   │   │   ├── chat_bridge.py            WebSocket fanout (chat + Telegram mirror)
│   │   │   ├── qa_agent.py               fire-and-forget `claude --print` Q&A
│   │   │   ├── message_router.py         legacy /btw serializer (rollback path)
│   │   │   ├── telegram_gateway.py       long-poll Telegram, admin allowlist
│   │   │   └── terminal_stream.py        raw terminal WS
│   │   └── ui/             Next.js 14 (static export)
│   │       ├── app/        dashboard / pipeline / chat / terminal / jobs /
│   │       │               settings / setup (wizard)
│   │       ├── components/ app-shell (SetupGuard), sidebar, session-dropdown,
│   │       │               pipeline/kanban-*, dashboard/stat-card, etc.
│   │       └── lib/api.ts  typed fetch wrappers
│   │
│   └── worker/            Python applier + scanner (subprocess of desktop or standalone)
│       ├── worker.py              main loop (claim → apply → dual-write)
│       ├── pipeline.py            SQLite pipeline CLI (scout/next/start/done/...)
│       ├── db.py                  worker-proxy wrapper + local SQLite dual-write
│       ├── applier/               base + greenhouse, ashby, lever, smartrecruiters, workday
│       ├── scanner/               greenhouse, ashby, lever, himalayas, indeed, jsearch, linkedin, ziprecruiter
│       ├── notifier.py            Telegram screenshot sender
│       ├── gmail_reader.py        verification code reader
│       ├── resume_tailor.py       per-company resume rewriting (optional, LLM)
│       └── knowledge.py           ATS learnings library
│
├── supabase/
│   └── migrations/        001-009 (schema, oauth, worker config, arrays, heartbeats,
│                          tokens, expand applications, activation codes)
├── docs/                  onboarding, subscription, DIY, changelog history
├── knowledge/             shared ATS patterns, Voyager API guide, email-services notes
└── .github/workflows/     CI/CD (future)
```

### Dev setup

```bash
git clone https://github.com/snehitvaddi/AutoApply.git
cd AutoApply

# Web
cd packages/web
npm install
cp .env.example .env.local   # fill in Supabase + Google OAuth keys
npm run dev                  # → http://localhost:3000

# Desktop (in another terminal)
cd ../../packages/desktop
pip install -r requirements.txt
APPLYLOOP_WORKSPACE=/tmp/applyloop-dev python3 launch.py
# → http://localhost:18790 (or the pywebview window)

# Worker (optional — you usually run it as a subprocess of the desktop app)
cd ../worker
pip install -r requirements.txt
export WORKER_TOKEN="al_xxx_yyy"   # mint via /admin
export APPLYLOOP_WORKSPACE=/tmp/applyloop-dev
python3 worker.py
```

### Environment variables

#### Vercel (packages/web)

| Var | Purpose |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key (client) |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role (server-only) |
| `NEXT_PUBLIC_APP_URL` | `https://applyloop.vercel.app` (production) |
| `ENCRYPTION_KEY` | `openssl rand -hex 32` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth credentials |
| `TELEGRAM_BOT_TOKEN` | For admin-side activation-code DMs |
| `GITHUB_PERSONAL_TOKEN` | Optional — auto-add approved users as collaborators |
| `GITHUB_COLLABORATOR_REPO` | Optional — the `owner/repo` to add collaborators to. Leave unset to no-op. |
| `SUPABASE_DB_URL` | Optional — Postgres pooler URI for `migrate.mjs` to run migrations during build |
| `STRIPE_*` | Optional — Phase 5 |

#### Desktop / Worker

| Var | Purpose |
|---|---|
| `APPLYLOOP_WORKSPACE` | Directory for per-user state (default `~/.autoapply/workspace`). **Set this to isolate multiple instances on one Mac.** |
| `APPLYLOOP_PORT` | FastAPI port (default 18790) |
| `APPLYLOOP_HEADLESS` | `1` to skip pywebview (useful for CI / dev) |
| `APPLYLOOP_DB` | Override SQLite path (default `$APPLYLOOP_WORKSPACE/applications.db`) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Opt-in Telegram gateway (leave unset to disable) |
| `WORKER_TOKEN` | Worker's API token (written by the setup wizard, or set manually) |
| `NEXT_PUBLIC_APP_URL` | Cloud endpoint (default `https://applyloop.vercel.app`) |

### Migrations

```bash
# SQL files live at supabase/migrations/
# They're run automatically during Vercel build by packages/web/scripts/migrate.mjs,
# which tracks applied names in public._migrations to stay idempotent.
# If SUPABASE_DB_URL isn't set, the build skips migrations (local dev is fine).

# To run them from your dev machine:
export SUPABASE_DB_URL="postgresql://postgres.PROJECT_REF:PASSWORD@..."
cd packages/web && node scripts/migrate.mjs
```

### Cutting a desktop release

```bash
# Bump version in packages/desktop/build.py (VERSION constant)
cd packages/desktop
python3 build.py --mac
# Output: dist/ApplyLoop-<version>.dmg

# Upload to GitHub Releases
shasum -a 256 dist/ApplyLoop-<version>.dmg > dist/ApplyLoop-<version>.dmg.sha256
gh release create v<version> dist/ApplyLoop-<version>.dmg dist/ApplyLoop-<version>.dmg.sha256 \
  --title "v<version>" --notes "..." --target main

# Update RELEASE_TAG and DMG_NAME in packages/web/src/app/setup-complete/page.tsx
# Commit + push → Vercel redeploys → new download link is live
```

---

## Supported platforms

### ATS appliers (packages/worker/applier/)

| Platform | Status | Notes |
|---|---|---|
| Greenhouse | Full | Embed URL bypass, email security codes, reCAPTCHA detection |
| Ashby | Full | 45s upload wait, Enter for location, type (not fill) |
| Lever | Full | Single-page, full name field, radio buttons |
| SmartRecruiters | Full | Confirm email, multi-page flow |
| Workday | Partial | Account creation required, 7-step wizard |

### Job scanners (packages/worker/scanner/)

| Source | Auth | Typical yield |
|---|---|---|
| Greenhouse API | None | 271+ company boards |
| Ashby API | None | 102+ company boards |
| Lever API | None | ~7 active companies |
| LinkedIn Voyager | Session cookie | 1200+ jobs per scrape |
| Himalayas / Indeed / JSearch / ZipRecruiter | Varies | Supplemental |

---

## Security model

Short version:

- **Users never hold Supabase keys.** They hold a worker token that's minted by the activation flow and hashed server-side.
- **The desktop app doesn't bundle secrets.** After the v1.0.0 audit (see Appendix), no Telegram bot tokens, Claude CLI paths, or `.openclaw` legacy paths are baked in.
- **Worker tokens are per-user and revocable.** Admin can revoke from `/admin`. The desktop surfaces `token_revoked` state and bounces to the setup wizard.
- **Activation codes are time- and use-limited.** 7-day TTL, 5 uses by default. Race-safe atomic decrement prevents double-redemption. IP-based rate limit prevents brute force.
- **Resumes are validated.** 10MB cap, PDF magic-byte sniff, filename sanitization before Storage write.
- **GitHub Releases distributes the `.dmg`.** Public binary, useless without a valid activation code. SHA256 sidecar published alongside for verification.

Longer version: see the [April 2026 QA audit plan](./docs/CHANGELOG-2026-04-09.md) and the commit log from `9c04935` onward — 33 commits of hardening, including a cross-tenant PII leak fix (`d7f84f4`), atomic activation-code decrement (`61b8690`), rate limiting, MIME validation, arch detection, and token-revocation propagation.

---

## Known limitations

- **macOS only** — Windows build is pending
- **Not Apple-signed** — users see Gatekeeper warning on first launch, must right-click → Open
- **`SUPABASE_DB_URL` currently unset in production** — migrations are pre-applied via the Supabase MCP, so not blocking. Set this before cutting the next migration so `migrate.mjs` can run during Vercel build.
- **Rate limit is in-process Map** (per serverless container) — distributed attackers could brute-force across containers. Upgrade to Upstash Redis or Vercel KV when needed. `packages/web/src/lib/rate-limit.ts` is already written for Upstash.
- **Telegram integration requires manual `telegram_chat_id` setup per user** — no auto-linking via bot `/start` yet.
- **Stripe webhook is a placeholder** — payment verification is currently manual (Phase 5 on the roadmap).

---

## Roadmap

- **Phase 2 (in progress)** — Retire the legacy OpenClaw Telegram path; full Telegram-first chat via desktop gateway (already landed in `cf2f404`, needs cleanup)
- **Phase 3** — Telegram niceties: YOLO mode toggle, message splitting for long replies, `/status` shortcut, permission whitelist for Telegram-originated tool calls
- **Phase 4** — Windows `.exe` installer; `.dmg` Apple code signing
- **Phase 5** — Stripe webhook auto-generates activation codes on successful payment; tiered daily limits enforced

---

## License

Private, invite-only beta. Contact the admin for access.

---

## Credits

Built with [Claude Code](https://claude.com/product/claude-code). Architected through multi-agent audit sessions — see the [plan file](https://github.com/snehitvaddi/AutoApply/blob/main/docs/CHANGELOG-2026-04-09.md) for the audit methodology.
