# APPLYLOOP ARCHITECTURE — How the 3 Layers Work Together

You are building a SaaS job application bot. Understanding the 3-layer architecture
is CRITICAL. Each layer has a specific role. DO NOT mix them up.

═══ THE 3 LAYERS ═══

┌─────────────────────────────────────────────────────────┐
│  LAYER 1: CLAUDE CODE (The Brain / Intelligence)        │
│                                                         │
│  What it is: Claude Code CLI running in the terminal    │
│  What it does:                                          │
│    - DECIDES what to do (scout, filter, apply, skip)    │
│    - READS form snapshots and UNDERSTANDS what fields   │
│      need what values                                   │
│    - WRITES company-specific answers ("Why interested") │
│    - READS job descriptions and checks if role matches  │
│    - HANDLES errors (missing fields, validation, stuck) │
│    - READS email for verification codes (via himalaya)  │
│    - SENDS Telegram notifications with proof            │
│    - TRACKS pipeline status, dedup, rate limits         │
│                                                         │
│  Claude Code does NOT directly touch the browser.       │
│  It sends COMMANDS to OpenClaw (Layer 2).               │
│                                                         │
│  Think of it as: The human brain that decides and       │
│  thinks, but uses hands (OpenClaw) to act.              │
└────────────────────┬────────────────────────────────────┘
                     │ sends commands like:
                     │   openclaw browser navigate "url"
                     │   openclaw browser snapshot
                     │   openclaw browser fill --fields '[...]'
                     │   openclaw browser click e123
                     │   openclaw browser upload --ref e45 file.pdf
                     │   openclaw browser screenshot
                     │   openclaw browser evaluate --fn "() => ..."
                     ▼
┌─────────────────────────────────────────────────────────┐
│  LAYER 2: OPENCLAW (The Hands / Browser Automation)     │
│                                                         │
│  What it is: Browser automation tool (like Playwright)  │
│  What it does:                                          │
│    - NAVIGATES to URLs                                  │
│    - TAKES SNAPSHOTS (accessibility tree of the page)   │
│    - FILLS form fields by ref ID                        │
│    - CLICKS buttons/dropdowns by ref ID                 │
│    - UPLOADS files (resume)                             │
│    - TAKES SCREENSHOTS (for Telegram proof)             │
│    - EVALUATES JavaScript on the page                   │
│    - READS COOKIES (for LinkedIn tokens)                │
│                                                         │
│  OpenClaw is DUMB. It does exactly what it's told.      │
│  It does NOT decide what to fill or which button to     │
│  click. That intelligence comes from Claude Code above. │
│                                                         │
│  Think of it as: The hands that type and click,         │
│  following instructions from the brain.                 │
└────────────────────┬────────────────────────────────────┘
                     │ controls
                     ▼
┌─────────────────────────────────────────────────────────┐
│  LAYER 3: CODEX / LLM (OpenClaw's Internal Engine)     │
│                                                         │
│  What it is: OpenAI Codex (gpt-5.3-codex) or any LLM   │
│  What it does:                                          │
│    - Powers OpenClaw's snapshot parsing                  │
│    - Handles autonomous agent loops when Claude Code    │
│      is not actively connected                          │
│    - Configurable per user in openclaw.json             │
│                                                         │
│  Think of it as: The engine that keeps running when     │
│  the brain (Claude Code) is sleeping.                   │
└─────────────────────────────────────────────────────────┘

═══ HOW THEY INTERACT — EXAMPLE FLOW ═══

1. Claude Code scouts via API calls (curl/python — no browser needed):
   → Calls Greenhouse/Ashby APIs
   → Filters jobs by rules
   → Finds: "Samsara AI Engineer (Remote US)"

2. Claude Code tells OpenClaw to navigate:
   → `openclaw browser navigate "https://job-boards.greenhouse.io/..."`
   → OpenClaw opens Chrome, loads the page

3. Claude Code takes a snapshot:
   → `openclaw browser snapshot`
   → OpenClaw returns the accessibility tree (all form fields, refs, labels)
   → Claude Code READS the snapshot and UNDERSTANDS the fields

4. Claude Code DECIDES what to fill:
   → Reads profile.json for user data
   → Writes company-specific answers
   → Builds a JSON array of fill commands

5. Claude Code tells OpenClaw to fill:
   → `openclaw browser fill --fields '[{"ref":"e31","type":"text","value":"Snehit"}, ...]'`
   → OpenClaw fills the fields (dumb execution)

6. Claude Code handles dropdowns:
   → `openclaw browser click e130` (open dropdown)
   → `openclaw browser snapshot` (see options)
   → Claude Code picks the right option
   → `openclaw browser click e474` (select value)

7. Claude Code submits and handles verification:
   → `openclaw browser click e441` (submit)
   → `openclaw browser snapshot` (check result)
   → If email verification needed → reads via himalaya CLI
   → Fills code → resubmits

8. Claude Code confirms and notifies:
   → `openclaw browser screenshot` (proof image)
   → Sends to Telegram via curl sendPhoto API
   → Logs to dedup DB

═══ KEY RULES ═══

- Claude Code = BRAIN (orchestrates everything)
- OpenClaw = HANDS (executes browser commands)
- Codex = ENGINE (always-on when Claude Code is not active)
- For scouting: use curl/python API calls (no browser needed)
- For applying: use openclaw browser commands (browser needed)
- NEVER use web search for scouting — use direct API calls
- NEVER run worker.py — Claude Code IS the worker
