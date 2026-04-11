# ApplyLoop — Architecture (start to end)

This document walks through the full lifecycle of an ApplyLoop install, from the moment a user signs up on the web to the moment the worker is actively applying to jobs on their Mac. It describes every moving piece and where state lives — nothing hand-waved.

---

## 1. The two surfaces

ApplyLoop is a **hybrid SaaS**:

- **Cloud** (`applyloop.vercel.app`, Next.js + Supabase): sign-up, onboarding, admin approval, activation codes, the worker-token auth pipeline, per-user config.
- **Local desktop app** (`/Applications/ApplyLoop.app` on the user's Mac): wizard, checklist, terminal pane, chat, jobs pipeline, settings, and the background worker that actually applies to jobs.

The cloud **never** runs apply logic. All browser automation, form filling, and LLM calls happen on the user's machine. The cloud only stores profile data and brokers auth.

```
┌─────────────────────────────────────────────┐
│  applyloop.vercel.app  (Next.js, Vercel)   │
│  ─────────────────────────────────────────  │
│  • Landing, signup, onboarding              │
│  • /admin (activation codes, approvals)    │
│  • /api/activate            (public, code)  │
│  • /api/worker/auth         (token check)  │
│  • /api/settings/cli-config (per-user data)│
│  • /api/worker/proxy        (profile R/W)  │
└─────────────────────────┬───────────────────┘
                          │ service-role key
                          ▼
┌─────────────────────────────────────────────┐
│            Supabase                         │
│  Postgres + Auth + Storage                  │
│  ─────────────────────────────────────────  │
│  users, user_profiles, user_job_preferences │
│  user_resumes, activation_codes,            │
│  worker_tokens, apply_queue, applications   │
└─────────────────────────┬───────────────────┘
                          │ worker_token
                          ▼
┌─────────────────────────────────────────────┐
│  /Applications/ApplyLoop.app  (user's Mac) │
│  ─────────────────────────────────────────  │
│  • FastAPI server (localhost:18790)         │
│  • pywebview native window → React UI       │
│  • Claude Code PTY terminal                 │
│  • Python worker subprocess (apply loop)    │
│  • Local SQLite mirror (~/.autoapply/...)   │
└─────────────────────────────────────────────┘
```

---

## 2. The user journey

### Stage 1 — Web sign-up (cloud only)

1. User visits `applyloop.vercel.app` → signs up with Google.
2. Walks the onboarding flow: profile JSON paste (name / phone / experience / education / skills), resume upload, target job titles + locations + salary floor.
3. Data lands in Supabase across four tables:
   - `users` (id, email, full_name, approval_status='pending')
   - `user_profiles` (all the structured profile fields)
   - `user_job_preferences` (target_titles[], excluded_titles[], etc.)
   - `user_resumes` (uploaded files in Supabase Storage)
4. Status: **pending admin approval**.

### Stage 2 — Admin approval + activation code (cloud only)

1. Admin visits `applyloop.vercel.app/admin`, reviews the new user's profile.
2. Clicks **Approve** → `users.approval_status = 'approved'`.
3. Clicks **Generate activation code** → row inserted into `activation_codes` with format `AL-XXXX-XXXX`, `uses_remaining=1`, `expires_at=now+7d`.
4. Admin delivers the code out-of-band (Telegram DM or email).

### Stage 3 — Web /setup-complete (cloud only)

1. The user returns to `applyloop.vercel.app/setup-complete`.
2. Page renders two things side-by-side:
   - **Activation code**: `AL-X1Y2-Z3W4` with a Copy button
   - **macOS install command**: a single `curl` one-liner with the code already embedded

```bash
curl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh | bash -s -- AL-X1Y2-Z3W4
```

3. User copies the command and pastes into Terminal.app. **This is the last thing they manually type for the entire install.**

---

## 3. What `install.sh` does (on the user's Mac, ~3–5 min)

Every step below is in a single bash script that self-reexecs (so `curl | bash` can't corrupt it via the brew→pip stdin bug), validates inputs, and stores state only in `~/.applyloop/` + `~/.openclaw/` + `~/Library/LaunchAgents/`.

### 3a. Self-reexec + guards
- Detect if we're running under `curl | bash` (stdin is a pipe, not a tty).
- curl-fetch the script to a tmpfile, re-exec with `stdin=/dev/null` so child processes (brew → pip) can't drain our pipe.
- Pass `"$@"` through the re-exec so positional args (the activation code) survive.
- macOS guard: abort if not Darwin.

### 3b. Phase A — Activation gate (**the security boundary**)
- Extract the activation code from `APPLYLOOP_CODE` env, positional arg, or `/dev/tty` prompt (in that order).
- `POST https://applyloop.vercel.app/api/activate` with the code.
- On success, the response is a single round-trip that carries:
  - `worker_token` (long-form `al_xxxx_xxxx`, per-user, SHA-256 hashed in Supabase `worker_tokens` table)
  - `user_id`, `email`, `full_name`, `tier`
  - Full `profile` (every column from `user_profiles`)
  - `preferences` (every column from `user_job_preferences`)
  - `default_resume`
  - `telegram_chat_id` (if set on the user row)
- On failure, the script aborts **before touching the machine**. Bad code → zero disk writes.

### 3c. Phase B — Bootstrap system dependencies
- `brew` → install if missing (Apple's official installer, prompts once for sudo)
- `python@3.11` → pinned version, so every install targets the same minor
- `node` → brew's current LTS (22.x today)
- `git`, `claude`, `openclaw` → via brew / npm
- Register the OpenClaw gateway as a **user-scope launchd service** (`openclaw gateway install && start`)

### 3d. Phase C — Write `~/.openclaw/openclaw.json` directly
- The old interactive `openclaw config` wizard hangs when invoked non-interactively.
- install.sh writes a minimal config via a heredoc:
  - Browser profile (chrome CDP port 18800)
  - Gateway config (port 18789, loopback, random 24-byte token via `openssl rand -hex 24`)
  - **No auth profile, no LLM provider.** OpenClaw is used only for browser DOM actions; the LLM calls go through Claude Code (Layer 1), not OpenClaw.

### 3e. Phase D — Clone repo + create venv + build UI
- `git clone --depth 1 --branch main` → `~/.applyloop`
- `python3.11 -m venv ~/.applyloop/venv`
- Single-pass pip install of `packages/desktop/requirements.txt` + `packages/worker/requirements.txt` (pip resolves the full graph in one pass, so any future conflict fails loudly)
- `cd packages/desktop/ui && npm install && npm run build` (isolated `NPM_CONFIG_CACHE=~/.applyloop/.npm-cache` to avoid root-owned cache collisions)

### 3f. Phase E — Sync profile from cloud
- `GET /api/settings/cli-config` with `X-Worker-Token: <worker_token>` header
- Returns `telegram_bot_token`, `supabase_url`, `supabase_anon_key` (the three admin-global fields not returned by `/api/activate`)
- Transform the activation response into the nested `profile.json` shape Claude Code expects (user/personal/work/legal/eeo/experience[]/education[]/skills[]/standard_answers{}/preferences{}/resumes[])
- Write to `~/.applyloop/profile.json`

### 3g. Phase F — Interactive optional prompts (with `.env` reuse)
On first install, prompts for 5 optional integrations:
- **Telegram Chat ID** (digits or `-` for group chats)
- **AgentMail API key** (disposable inboxes for email verification, verified via curl)
- **Finetune Resume API key** (per-job tailored PDF generation)
- **Gmail email** (for Himalaya CLI IMAP reader)
- **Gmail app password** (16 chars, auto-strips spaces)

On **re-install** (same `APPLYLOOP_HOME`), the existing values in `~/.applyloop/.env` are shown masked (`****abcd`) and each prompt becomes `[Enter to keep / 's' to unset / type new]`. No more re-typing.

### 3h. Phase G — Write `~/.applyloop/.env`
```
WORKER_TOKEN=al_xxxx_xxxx
NEXT_PUBLIC_APP_URL=https://applyloop.vercel.app
ENCRYPTION_KEY=<openssl rand -hex 32>
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
WORKER_ID=worker-<hostname>-<random>
POLL_INTERVAL=10
APPLY_COOLDOWN=30
RESUME_DIR=~/.autoapply/workspace/resumes
SCREENSHOT_DIR=~/.autoapply/workspace/screenshots
TELEGRAM_BOT_TOKEN=<admin's bot>
TELEGRAM_CHAT_ID=<per-user>
AGENTMAIL_API_KEY=<optional>
FINETUNE_RESUME_API_KEY=<optional>
GMAIL_EMAIL=<optional>
GMAIL_APP_PASSWORD=<optional>
```
Also writes `~/.autoapply/workspace/.api-token` (the worker token, chmod 600) — this is where the desktop wizard looks for activation state, so pre-seeding it means the wizard opens already activated.

### 3i. Phase H — Write `~/.applyloop/AGENTS.md`
A system-context file Claude Code reads on first PTY spawn. Contains:
- Install dir, venv path, profile path, worker code path, desktop log path
- User's first name (for personalized greeting)
- Status of each configured integration (Telegram/AgentMail/Finetune/Gmail)
- Role instructions: "read profile.json, read SOUL.md, greet user, wait for commands, never auto-start the loop"
- Critical rules: "never apply to a company >5× per 15 days, never skip required fields, always screenshot + Telegram notify, if rate-limited or auth error → pause and surface to user"

### 3j. Phase I — Generate `/Applications/ApplyLoop.app`
- Bundle structure: `Contents/Info.plist` + `Contents/MacOS/launcher` + `Contents/Resources/AppIcon.icns`
- The launcher is a ~60-line bash script that:
  1. Sources brew shellenv (so `/opt/homebrew/bin` is on PATH for Finder-launched processes)
  2. Prepends `~/.local/bin` + npm global prefix
  3. Sources `~/.applyloop/.env` so WORKER_TOKEN, TELEGRAM_*, etc. are inherited by the Python process
  4. Logs startup to `~/.autoapply/desktop.log`
  5. Execs `~/.applyloop/venv/bin/python3 ~/.applyloop/packages/desktop/launch.py`
- **Because the bundle is generated locally, macOS never attaches a quarantine bit.** Double-click works on first try with zero Gatekeeper interaction — no codesigning, no notarization, no $99/year to Apple.
- `lsregister -f` is called so Spotlight + Dock pick up the new bundle immediately.

### 3k. Phase J — Symlink + launchd plist
- Symlink `~/.local/bin/applyloop → ~/.applyloop/packages/desktop/scripts/applyloop` (the CLI shim: `start/stop/status/logs/update/uninstall`)
- Write `~/Library/LaunchAgents/com.applyloop.update.plist` — runs `applyloop update` daily at 3 AM via `launchctl bootstrap gui/<uid>`

### 3l. Phase K — Success summary
Colored output, paths, next steps. User double-clicks the .app and moves on.

---

## 4. First launch — what happens when the user double-clicks `ApplyLoop.app`

1. **macOS Launch Services → launcher script** (`Contents/MacOS/launcher`)
   - Sources brew shellenv + `.env`
   - Logs to `~/.autoapply/desktop.log`
   - Execs `venv/bin/python3 ~/.applyloop/packages/desktop/launch.py`

2. **`launch.py`** — FastAPI server + pywebview native window
   - FastAPI boots on `127.0.0.1:18790`
   - Starts background threads: Telegram gateway (if token set), message router, local_data SQLite bootstrap
   - Lifespan handler auto-spawns the Claude Code PTY session if `preflight.ready == true` (token on disk, claude on PATH, profile synced)
   - pywebview opens a native WKWebView window pointing at `http://127.0.0.1:18790/`

3. **Wizard (`/setup`)** — reads `/api/setup/status`
   - 8 preflight checks: token, profile, resume, preferences, claude_cli, openclaw_cli, openclaw_gateway, git
   - All 8 green on a fresh install (install.sh seeded everything)
   - User clicks **Start ApplyLoop**:
     - Frontend calls `createNewPTYSession()` → backend spawns PTY (or confirms one's already alive from the lifespan auto-start)
     - Router navigates to `/` (dashboard)

4. **Terminal tab** — PTY session (Claude Code)
   - Child process execs a **bash wrapper script** (not claude directly):
     1. Checks `~/.claude/` for existing auth tokens
     2. If authed: runs `claude --dangerously-skip-permissions '<initial prompt>'`
     3. When Claude exits (normal, auth error, rate limit, anything): **falls through to `exec /bin/zsh -l`** so the user always has a real shell to type into
   - Initial prompt tells Claude: "read `./AGENTS.md`, read `./packages/worker/SOUL.md`, read `./profile.json`, greet the user by first name, wait for commands"
   - If Claude crashes, the wrapper classifies the exit reason by pattern-matching `~/.claude/logs/*.log`:
     - Rate limit / quota hit → "Wait a few minutes and try again, or upgrade your plan"
     - Auth expired → "Run: claude login"
     - Network error → "Check your internet / VPN"
     - Plan limit → "Upgrade at claude.com/billing"
   - The user sees a human-readable line instead of a raw red error, plus a shell prompt they can keep typing into.

5. **Chat tab** — `/chat`
   - Separate code path from the Terminal PTY. Runs `claude --print` as a **one-shot subprocess** per message (via `packages/desktop/server/qa_agent.py`).
   - Uses the SAME `~/.claude/` auth the Terminal uses (inherited automatically).
   - No API keys are embedded in the app. Zero. The chat works because the user has their own Claude Code OAuth cached locally.
   - Sees profile context + current state via a system prompt that's built from `profile.json` + recent apply-pipeline events.

6. **Jobs + Pipeline tabs** — `/jobs` and `/pipeline`
   - Read from the local SQLite mirror at `~/.autoapply/workspace/applications.db`
   - Desktop server (`local_data.py`) has been running a background sync that mirrors Supabase `apply_queue` + `applications` rows into the local DB
   - Kanban columns: **Applying → Submitted → Verified → Failed → Skipped**
   - Each card shows company, role, URL, status, optional screenshot, Telegram message link

7. **Telegram gateway** (if configured)
   - `packages/desktop/server/telegram_gateway.py` reads `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` from env
   - Opens a long-poll against `api.telegram.org`
   - Any message the user sends to the bot gets routed via `message_router.py` to the chat feed
   - Chat replies get sent back via `send_message(chat_id, text)`
   - So the user can literally talk to the bot from their phone while they're out, and both sides of the conversation appear in the desktop Chat tab too

8. **Worker subprocess** — the actual apply loop
   - Triggered by Claude Code when the user says "start" or "scout"
   - Runs `~/.applyloop/venv/bin/python3 ~/.applyloop/packages/worker/worker.py` as a child process
   - Inherits all the env vars from `.env` (WORKER_TOKEN, RAPIDAPI_KEY, AGENTMAIL_API_KEY, etc.)
   - Main loop:
     1. Fetch pending jobs from Supabase `apply_queue` via the worker proxy
     2. For each job: load the applier (greenhouse, lever, ashby, smartrecruiters, workday), call `openclaw browser navigate / snapshot / fill / click / upload`
     3. Use an LLM call (via `claude --print` subprocess) to map the user's `answer_key_json` + `profile.json` to the current form's fields
     4. Submit, screenshot, update Supabase status, mirror to local SQLite, send Telegram notification
   - **Nudge watchdog**: every 5 min, checks `last_output_at` on the Claude PTY. If >30 min idle, writes a nudge message directly into Claude's stdin ("status check — what have you been doing? If you finished the current round, start the next one. If you're waiting on user input, tell them explicitly."). Prevents Claude from silently napping mid-campaign.

---

## 5. Where state lives

| State | Path | Lifetime |
|---|---|---|
| AutoApply source code | `~/.applyloop/` | Updated by `applyloop update` |
| Python venv | `~/.applyloop/venv/` | Rebuilt on requirements change |
| Static UI bundle | `~/.applyloop/packages/desktop/ui/out/` | Rebuilt on `npm run build` |
| User profile (nested) | `~/.applyloop/profile.json` | Written at install time, editable via Settings UI |
| Runtime env | `~/.applyloop/.env` | Written at install time, editable via Settings UI (planned Wave 1) |
| System context for Claude | `~/.applyloop/AGENTS.md` | Written at install time |
| Install version | `~/.applyloop/.applyloop-version` | git HEAD sha, used by `applyloop update` for drift detection |
| Claude Code auth tokens | `~/.claude/` | Per-user per-machine, survives install.sh (not touched) |
| OpenClaw config | `~/.openclaw/openclaw.json` | Written at install time if missing |
| OpenClaw gateway state | `~/.openclaw/workspace/` | Runtime browser state |
| Worker token | `~/.autoapply/workspace/.api-token` | chmod 600, the desktop wizard reads this |
| Local SQLite mirror | `~/.autoapply/workspace/applications.db` | Apply pipeline, jobs, history — preserved across reinstalls |
| Runtime logs | `~/.autoapply/desktop.log` | Launcher + server + worker output |
| Resume downloads | `~/.autoapply/workspace/resumes/` | Preserved |
| Application screenshots | `~/.autoapply/workspace/screenshots/` | Preserved |
| /Applications bundle | `/Applications/ApplyLoop.app` | Regenerated by `applyloop update` |
| CLI shim | `~/.local/bin/applyloop` | Symlink to `packages/desktop/scripts/applyloop` |
| Auto-update plist | `~/Library/LaunchAgents/com.applyloop.update.plist` | Daily 3 AM |

**What's preserved across `applyloop uninstall`**: everything in `~/.autoapply/` (runtime workspace, apply pipeline, logs). Deleted intentionally: `~/.applyloop/`, `/Applications/ApplyLoop.app`, the CLI symlink, the launchd plist, and `.api-token`.

---

## 6. Update flow

| Trigger | Mechanism |
|---|---|
| Daily 3 AM | launchd plist runs `applyloop update` in the background |
| Manual | User runs `applyloop update` in any Terminal |
| Re-running curl one-liner | install.sh detects existing install, git-pulls, reuses `.env` values with per-field `[Enter to keep / 's' to unset / type new]` |

`applyloop update` does:
1. `git fetch origin main && git reset --hard origin/main`
2. `pip install -q -r requirements.txt` (both files, single-pass)
3. `npm install --silent && npm run build`
4. Regenerate `/Applications/ApplyLoop.app` from the new `build_local_app.sh`
5. Stop any running launch.py → user re-opens the app to get the new version

**No GitHub release cut is needed for most updates.** The curl URL points at `main`, and `applyloop update` pulls from `main`. Only architectural changes get tagged releases (v1.0.4, v1.0.6, v1.0.8, v1.0.9).

---

## 7. What's NOT in the bundle (explicit non-goals)

- **No embedded API keys.** No Anthropic, OpenAI, RapidAPI, or anything else. Every LLM call goes through the user's own Claude Code OAuth (`~/.claude/`), which they do once via `claude login` in the terminal tab.
- **No Gatekeeper bypass for downloaded bundles.** The trick is that the `.app` is *generated* on the user's machine, not downloaded. macOS quarantines downloaded files only. The `xattr`/codesign pain is sidestepped entirely.
- **No per-user worker running in the cloud.** The worker runs locally on the user's Mac. The cloud only proxies reads/writes to Supabase with per-user RLS enforced via the worker_token.
- **No SQLite settings table.** Settings live in `~/.applyloop/.env` and are mirrored to Supabase for admin visibility (Telegram chat ID only; other secrets stay local).
- **No OpenClaw Pro subscription.** OpenClaw is open source. The "gateway" is a local launchd service with no payment involved. Earlier labels in the code that called this "OpenClaw Pro subscription" were a hallucination from an earlier wave and have been removed.

---

## 8. Failure modes and recovery

| Symptom | Most likely cause | Fix |
|---|---|---|
| Double-click does nothing | Gatekeeper (older v1.0.4–1.0.7 .dmg installs) | Re-run the curl one-liner — v1.0.9+ generates the .app locally, no quarantine |
| Wizard opens with empty checklist | Preflight cloud call failed | Check `~/.autoapply/desktop.log`, try `applyloop update` |
| Wizard opens, profile row red | Profile missing email — **fixed in v1.0.7** (Phase A) by reading email from `users` table instead of `user_profiles` | Update to v1.0.7+ |
| Terminal tab black screen | Claude PTY spawn failed or Claude hit an error | **v1.0.10 Wave 0.5 fix**: wrapper always falls through to zsh -l on exit, user can type `claude login` or `claude` to retry |
| `npm install -g openclaw` fails with EACCES | `/tmp/npm-cache` has root-owned files | v1.0.8 moved cache to `~/.applyloop/.npm-cache`, fixed |
| install.sh re-prompts everything on rerun | `.env` reuse was added in v1.0.10 Wave 0 | Update install.sh via `applyloop update` once, then subsequent reruns will reuse |
| Chat works, terminal doesn't | Chat uses one-shot `claude --print` (qa_agent.py) while terminal uses persistent PTY (pty_terminal.py) — separate code paths, chat inherits `~/.claude/` auth but the PTY wrapper was previously not handling auth failures gracefully | v1.0.10 Wave 0.5 wrapper classifies exit reasons and drops to shell |
| Apply loop stops mid-campaign | Claude Code rate limit / plan quota | v1.0.10 nudge watchdog detects idle >30min and writes a status-check prompt directly into Claude's stdin |
| `/api/activate` returns 429 | IP rate limit on the activation endpoint (10 req/min) | Wait a minute and try again |

---

## 9. The install is the security boundary

The activation code is the **only** thing a stranger would need to compromise to install a working ApplyLoop. Everything downstream is gated on that code:

1. Stranger fetches `install.sh` from GitHub → script is public, no credentials inside
2. Stranger tries to run it → `POST /api/activate` requires a valid `AL-XXXX-XXXX` from the `activation_codes` table
3. Without a code → install aborts before any brew/git/pip is touched
4. With a fake code → HTTP 400, abort
5. With a real code → atomic CAS decrement of `uses_remaining`, one-use tokens by default
6. Worker_token returned → hashed with SHA256, stored in `worker_tokens` table, scoped to `user_id`
7. Every future cloud call uses `X-Worker-Token: <token>` → RLS + column allowlists enforce per-user isolation

So the only way to get a working install is to be a user that an admin explicitly approved + issued a code to. The whole pipeline is designed around the assumption that install.sh is public and the code is the secret.

---

## 10. The layered LLM architecture

| Layer | Tool | Role | Auth |
|---|---|---|---|
| **Layer 1 — Orchestrator** | Claude Code CLI | User-facing chat in the Terminal tab. Orchestrates the scout/apply loop. Reads profile.json, SOUL.md, AGENTS.md. | OAuth via `claude login`, tokens cached in `~/.claude/` |
| **Layer 2a — Worker runtime** | `python3 worker.py` | Background loop that polls `apply_queue`, runs appliers (Greenhouse, Lever, Ashby, etc.), mirrors to local SQLite | Inherits env from `.env` via launcher |
| **Layer 2b — Browser executor** | OpenClaw CLI | Called by applier classes via `openclaw browser navigate/snapshot/fill/click/upload`. **No LLM backend of its own.** | No auth needed — local only |
| **Layer 3 — Form-field mapper** | `claude --print` subprocess | Called inside the applier loop when filling out a specific job form. Gets the browser snapshot + profile + question list, returns structured answers. | Same `~/.claude/` tokens as Layer 1 |
| **Chat tab** | `claude --print` subprocess (`qa_agent.py`) | Separate from Layer 1. One-shot Q&A per message, stateless. | Same `~/.claude/` tokens |

**Key insight**: Claude Code is *the* LLM backend for everything — the terminal session, the Q&A chat, AND the form-field mapping inside the worker. It's one auth (`claude login`), one set of tokens, billed to the user's Claude account. OpenClaw is a dumb browser driver.

---

## 11. What shipped when

| Version | Focus |
|---|---|
| v1.0.0–1.0.3 | Initial .dmg distribution with bundled venv |
| v1.0.4 | Wave 4: 8-check setup readiness, auto-install bootstrap for CLIs, multi-step wizard |
| v1.0.5 | Fix `python-multipart` missing from requirements (unbreaks v1.0.4 launch) |
| v1.0.6 | Fix launcher ignoring bundled venv — was running system python and failing pyobjc compile |
| v1.0.7 | Profile email read from `users` table (was only reading `user_profiles`); SetupGuard exempts `/settings`; auto-install bootstrap chain after activation; OpenClaw Pro mislabel removed |
| v1.0.8 | **Distribution rewrite**: `.dmg` deprecated in favor of curl install script that generates the `.app` locally (no Gatekeeper) + npm cache isolation + brew shellenv in launcher |
| v1.0.9 | **Full feature port** from old `ApplyLoop-Setup-Mac.sh`: install-time code gate, OpenClaw config written directly (no interactive wizard), profile sync from cli-config, interactive prompts for Telegram/AgentMail/Finetune/Gmail, `.env` generation, AGENTS.md, auto-update launchd plist |
| v1.0.10 Wave 0 | Terminal visibility: startup banner, explicit PATH, post-fork death check. install.sh reuses existing `.env` values. |
| v1.0.10 Wave 0.5 | PTY bash wrapper: auto-check Claude auth, run claude if authed, drop to zsh -l on exit. Exit-code classifier translates rate limits / auth errors / plan limits into human-readable messages. |
| v1.0.10 Wave 1 (planned) | Settings UI coverage: `excluded_titles`, `preferred_locations`, `max_daily`, `cover_letter_template`, `answer_key_json`, resume delete/set-default, Telegram Chat ID edit, Integrations tab for `.env` fields |
| v1.0.10 Wave 1.5 (planned) | CI-gated `latest-stable` branch + in-app "update available" banner |
| v1.0.10 Wave 2 (planned) | Structured array editors for work_experience / education / skills; chat/Telegram lifecycle events; PTY pattern-match → chat bridge for auth errors |

---

## 12. Quick command reference

```bash
# Install (first time)
curl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh | bash -s -- AL-XXXX-XXXX

# Update
applyloop update

# Status
applyloop status

# Logs
applyloop logs

# Start / stop
applyloop start
applyloop stop

# Full uninstall (preserves ~/.autoapply workspace)
applyloop uninstall
```

```bash
# Non-interactive install with all optional integrations pre-filled
APPLYLOOP_CODE=AL-X1Y2-Z3W4 \
APPLYLOOP_TELEGRAM_CHAT_ID=123456789 \
APPLYLOOP_AGENTMAIL_KEY=am_... \
APPLYLOOP_FINETUNE_RESUME_KEY=... \
APPLYLOOP_GMAIL_EMAIL=you@example.com \
APPLYLOOP_GMAIL_APP_PASSWORD=abcdefghijklmnop \
APPLYLOOP_SKIP_PROMPTS=1 \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh)"
```

---

## 13. Open questions / future architecture calls

- **CI-gated updates**: do we create a `latest-stable` branch that GitHub Actions fast-forwards only on green CI, and have `applyloop update` pull from that instead of `main`? This prevents users from pulling broken commits between pushes.
- **Chat session lifecycle events in Telegram**: do we want "Session started" / "Session rate-limited" / "Auth expired" events to auto-post to the user's Telegram so they don't have to open the desktop app to see status?
- **Shared admin Claude credentials**: currently every user brings their own Claude Code account. For a first-time-user experience, would it be worth offering a limited "trial mode" that uses a shared admin key with per-user rate limits? (Security + billing concerns — deferred.)
- **Windows parity**: the `.app` bundle generation + launchd plist are macOS-only. Windows needs a `.ps1` installer + scheduled task + `ApplyLoop.exe` wrapper. Blocked until first Windows user.

---

## 14. Contact

Issues: flag in Telegram DM or open a GitHub issue. The installer URL is `https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh` and is updated continuously — there's no "old version" to downgrade to.
