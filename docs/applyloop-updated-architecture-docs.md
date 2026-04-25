# ApplyLoop — Updated Architecture Documentation

**Version:** 2.0  
**Date:** 2026-04-24  
**Status:** Plan — pending implementation

---

## 1. The Core Decision

**What changed and why:**  
The system went through a "Phase 1.3 cloud-planner migration" that removed the PTY watchdog/nudge system and replaced it with `brain/main.py` — a separate `ClaudeSDKClient` loop that fires autonomously every 5 minutes. That was the wrong direction. It created a headless, invisible process that:

- Burns Claude tokens with no user supervision
- Cannot be seen or stopped from the terminal tab
- Runs in parallel with worker.py, potentially double-claiming queue rows
- Ignores the daily token budget until `$25` is exhausted

**The correct architecture:** PTY Claude Code terminal is the single brain. It owns every decision. A watchdog loop writes context-rich nudge messages to its stdin when it goes idle, so it can run unattended overnight without any second autonomous process.

---

## 2. Architecture Diagram

See: `applyloop-updated-architecture.drawio`

To view: open [app.diagrams.net](https://app.diagrams.net) → File → Open → select the `.drawio` file.

---

## 3. Components

### 3.1 PTY Claude Code Session — THE ONLY BRAIN

- **Path:** `packages/desktop/server/pty_terminal.py` → spawns `claude --dangerously-skip-permissions`
- **Auth:** `claude login` → `~/.claude/` tokens. User's own Claude account. No embedded API keys.
- **Purpose:** The single decision-maker. Decides scout vs apply vs sleep based on queue state and time signals.
- **Capabilities via MCP tools:** scout all 7 sources, apply to any ATS, update queue, send Telegram, read profile/answers
- **Kept alive by:** Watchdog nudges (every 30 min if idle) + heartbeat (every 15 min for context)
- **Stopped by:** User says stop, or daily apply limit is reached

### 3.2 Nudge Watchdog — RESTORE (removed in Phase 1.3)

- **Path:** `packages/desktop/server/pty_terminal.py` → `_watchdog_loop()` + `_build_mission_nudge()`
- **Status:** Was deliberately removed in Phase 1.3. Must be restored.
- **Behavior:** Ticks every 30 minutes. Reads `_read_mission_stats()` (queue depth, applied_today, scout_age_min, idle_min). If Claude has been idle for >25 min, writes a nudge message to PTY stdin via `_submit_to_pty()`.
- **Nudge format:**
  ```
  [applyloop-watchdog 14:32] queue=3 pending, applied_today=8/25,
  scout_last=47min ago, idle=31min.
  Queue is low — run scout first, then apply from new jobs.
  ```
- **Intelligence:** The nudge message includes the recommended next action so Claude can act without reasoning from scratch.
- **Silent when healthy:** If Claude is actively applying (idle_min < 5) and queue is full, the watchdog fires nothing. Zero noise when everything is working.

### 3.3 Context Heartbeat — KEEP (already exists)

- **Path:** `pty_terminal.py` → `_mission_heartbeat_loop()`
- **Status:** Already implemented and running.
- **Behavior:** Every 15 minutes, sends a one-line status to PTY stdin: `[heartbeat] queue=X applied_today=Y worker=ok. keep scout→filter→apply going.`
- **Purpose:** Keeps Claude's context fresh. Not asking Claude to do anything — just refreshing state so it doesn't act on stale information.

### 3.4 MCP Tool Server — WIRE TO PTY (currently wired to brain/main.py only)

- **Path:** `packages/worker/brain/tools.py`
- **Status:** 24 tools fully implemented. Currently only accessible to the `ClaudeSDKClient` brain. Must be exposed to the PTY Claude session via `.claude/settings.json` MCP config.
- **Tool groups:**
  - **Browser (13):** navigate, snapshot, fill, click, type, select, upload, press_key, evaluate_js, screenshot, list_tabs, dismiss_stray_tabs, wait_load
  - **Queue (4):** claim_next, update_status, log_application, get_pipeline
  - **Scout (2):** list_sources, run_source
  - **Tenant (1):** load
  - **Notify (3):** telegram, heartbeat, upload_screenshot
  - **Knowledge (1):** get_ats_playbook

### 3.5 brain/main.py — DISABLE AUTONOMOUS LOOP (keep --once)

- **Path:** `packages/worker/brain/main.py`
- **Change:** Remove the `while True: sleep(300); send("continue")` loop from `_run_brain()`.
- **Keep:** `--once` mode fully intact. PTY Claude can call `applyloop-brain --once` explicitly when it wants to delegate a cycle to the SDK.
- **Kill switch:** The existing `APPLYLOOP_BRAIN_DISABLED` env var now applies to the loop mode. `--once` is always allowed.

### 3.6 worker.py — KEEP AS CALLABLE LIBRARY (not autonomous process)

- **Path:** `packages/worker/worker.py`
- **Change:** `process_manager.py` should not auto-start worker.py. The coded appliers (GreenhouseApplier, LeverApplier, AshbyApplier, etc.) remain fully intact as importable Python classes.
- **How Claude uses them:** Via the MCP browser tools. The apply-agent navigates to the ATS URL, snapshots the form, and fills it — the same path the coded appliers used, but driven by Claude's decisions instead of hardcoded logic.

### 3.7 AGENTS.md / SOUL.md — UPDATE

- **Path:** `~/.applyloop/AGENTS.md` (generated at install time)
- **Change:** Must tell Claude:
  - It owns the full scout → filter → apply loop
  - Watchdog nudges will arrive in its stdin — act on them immediately
  - The nudge message format and what each field means
  - Never auto-start another Claude process for applying
  - Daily limit comes from `queue_get_pipeline` → respect it

---

## 4. The Full Apply Pipeline (preserved, brain-owned)

This is the pipeline that must run inside PTY Claude's brain. Every step must be implemented via MCP tool calls. Nothing runs autonomously outside this loop.

```
STEP 1 — SCOUT
  └─ Call: scout_list_sources
  └─ For each source: scout_run_source(name) → list of JobPost dicts
  └─ Sources: linkedin_scroll, ashby, greenhouse, lever, himalayas, indeed, linkedin_public
  └─ Result: raw candidate jobs (unfiltered)

STEP 2 — FILTER
  └─ Call: tenant_load → get target_titles, preferred_locations, excluded_titles, daily_apply_limit
  └─ Apply filters: role match, location match, company blocklist, dedup against applied history
  └─ Result: filtered job list ready to enqueue

STEP 3 — ENQUEUE
  └─ Write filtered jobs to apply_queue (SQLite + Supabase mirror)
  └─ Call: queue_update_status for each → status=pending
  └─ Dashboard auto-reflects: job count, status breakdown (driven by same DB)

STEP 4 — APPLY (per job)
  └─ Call: queue_claim_next → locked row (prevents double-claiming)
  └─ Call: knowledge_get_ats_playbook(job.ats) → ATS-specific rules
  └─ Drive browser:
       browser_navigate(apply_url)
       browser_snapshot → accessibility tree + ref IDs
       browser_fill(fields) using profile.json + answer_key
       browser_click(submit_ref)
       browser_dismiss_stray_tabs(ats_hostname) between every step
  └─ OTP path: gmail_reader.py → Himalaya IMAP → extract code → browser_fill

STEP 5 — CONFIRM + SCREENSHOT
  └─ browser_snapshot again → look for "thank you" / "application received"
  └─ Positive confirmation ONLY — no "didn't error" = success
  └─ browser_screenshot → PNG saved locally
  └─ notify_upload_screenshot(local_path) → Supabase Storage → signed URL

STEP 6 — LOG + NOTIFY
  └─ queue_log_application(job_id, status=submitted, screenshot_url)
  └─ queue_update_status(queue_id, submitted)
  └─ notify_telegram(kind=application_result, company, title, screenshot_url)
  └─ Dashboard auto-updates: pipeline kanban, stats, screenshot visible

STEP 7 — DECIDE NEXT
  └─ queue_get_pipeline → check pending count, applied_today vs daily_limit
  └─ If pending > 0 AND applied_today < limit → claim next job (STEP 4)
  └─ If pending < 20 → run scout cycle (STEP 1) to top up
  └─ If daily_limit hit → stop, send session summary via notify_telegram
  └─ If queue empty after scout → sleep (watchdog will nudge when needed)
```

**Dashboard consistency:** All stats (applied_today, in_queue, total_applied, success_rate) derive from `applications.db`. The desktop UI reads only this DB. Since PTY Claude writes every outcome to the DB via `queue_log_application`, the pipeline view, jobs list, and stats are always in sync — no separate sync needed.

---

## 5. What the Nudge Message Contains

The restored `_build_mission_nudge()` must include:

| Field | Source | Purpose |
|---|---|---|
| `queue` | `_read_mission_stats().in_queue` | Tell Claude how many jobs are pending |
| `applied_today` | `stats.applied_today` | Tell Claude how close it is to the daily cap |
| `daily_limit` | `_tenant_snapshot.daily_apply_limit` | Daily cap |
| `scout_last` | `stats.scout_age_min` | Tell Claude if scout is stale (>60 min) |
| `idle` | `stats.idle_min` | How long Claude has been silent |
| `recommended_action` | Computed from above | "apply from queue" / "run scout first" / "daily limit reached, stop" |

---

## 6. What Changes in Code

| File | Change | Priority |
|---|---|---|
| `pty_terminal.py` | Restore `_watchdog_loop()` + `_build_mission_nudge()` | P0 |
| `brain/main.py` | Remove `while True` loop; keep `--once` | P0 |
| `app.py` lifespan | Do NOT auto-start brain; only auto-start PTY | P0 |
| `.claude/settings.json` | Add `brain/tools.py` MCP server so PTY Claude has tools | P0 |
| `AGENTS.md` template | Update to tell Claude it owns the loop + nudge format | P1 |
| `SOUL.md` | Update: no spawning separate Claude processes | P1 |
| `process_manager.py` | worker.py start only on explicit request, not on app launch | P1 |
| `brain/prompts.py` | System prompt stays (used by --once subagents) | no change |
| `brain/tools.py` | No change — tools are correct | no change |
| `brain/subagents.py` | No change — used in --once mode | no change |
| `applier/*.py` | No change — remain as callable library | no change |
| `scout/*.py` | No change — called via scout_run_source tool | no change |

---

## 7. What's Removed

| Component | Reason |
|---|---|
| `brain/main.py` `while True` loop | Self-sustaining token burn, invisible to user |
| `worker.py` auto-start on app launch | Parallel autonomous process, no PTY coordination |
| Phase 1.3 "cloud planner" decision path | Wrong direction — PTY is the planner, not the cloud |

---

## 8. Token Budget Control

With this architecture:
- **Only one Claude process runs at a time** — the PTY session
- **Cycles are user-initiated** — "go, I'm sleeping" starts the loop
- **The watchdog keeps it going** — but only writes nudges, never spawns Claude
- **User can stop at any time** — type "stop" in the terminal tab
- **Daily limit enforced by Claude itself** — via `queue_get_pipeline` check

The `$25` budget cap in `brain/main.py` was a safety net for the wrong problem. With PTY Claude as the only brain, the user's Claude subscription governs usage directly — no hidden process can exhaust it.

---

## 9. Screenshot → Dashboard → Telegram Flow

After every successful application:

1. `browser_screenshot()` → PNG saved to `~/.autoapply/workspace/screenshots/` (local only)
2. `queue_log_application(screenshot=local_path)` → local path written to `applications.db`
3. Desktop dashboard (`/api/screenshots/{job_id}`) → FastAPI streams the local file directly — no URL, no Supabase
4. `notify_telegram(screenshot_path=local_path)` → `notifier.py` opens the file and calls `sendPhoto` with binary — no URL, no Supabase

**No Supabase Storage upload needed.** The `upload_screenshot()` in `db.py` exists only for the web dashboard (`applyloop.vercel.app`) where remote URL access is required. The local desktop dashboard and Telegram both work entirely off the local file path.

This is a single write path. Every outcome (success or failure) follows the same triple: `log_application` → `update_status` → `notify_telegram`. Nothing is skipped even on failure (just uses `status=failed` + `error=` string).

---

## 10. Technology Stack

| Layer | Technology | Role |
|---|---|---|
| Orchestrator | Claude Code CLI (PTY) | Single brain — all decisions |
| Nudge mechanism | `pty_terminal.py` watchdog | Keeps PTY Claude alive overnight |
| MCP tools | `brain/tools.py` | 24 tools PTY Claude calls |
| Browser | OpenClaw CLI → Chromium CDP | Dumb executor — zero decisions |
| Job discovery | `scout/*.py` (7 sources) | Called via `scout_run_source` tool |
| ATS form logic | `applier/*.py` (5 ATS) | Callable library, not autonomous |
| Data store | SQLite `applications.db` | Single source of truth for all stats |
| Cloud mirror | Supabase via worker proxy | Sync + screenshot storage |
| Notifications | `notifier.py` → Telegram Bot API | Per-outcome push + screenshots |
| Desktop shell | FastAPI 18790 + pywebview | Hosts PTY, serves dashboard UI |
