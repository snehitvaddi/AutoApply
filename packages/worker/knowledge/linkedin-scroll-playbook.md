# LinkedIn Scroll Playbook (no login required)

Operational notes for anyone debugging `scout/linkedin_scroll.py` or extending
LinkedIn ingestion. Written for the Claude-in-terminal driver and for humans.

## Entry URLs (both shapes work)

Guest job search accepts two equivalent shapes. The scout uses the second
(more general) form but either will work:

1. Category-framed:
   `https://www.linkedin.com/jobs/ai-engineer-jobs?keywords=Ai%20Engineer&location=United%20States&geoId=103644278&f_TPR=r86400&position=1&pageNum=0`
2. Generic search (what the scout builds):
   `https://www.linkedin.com/jobs/search?keywords=<q>&location=<loc>&geoId=103644278&f_TPR=r86400&f_E=2,3,4&position=1&pageNum=0`

### Relevant query params

- `keywords` — role query (URL-encoded)
- `location` — free-text location (URL-encoded)
- `geoId=103644278` — internal geo ID for "United States"
- `f_TPR=r86400` — time-posted-range = last 24 hours
- `f_E=2,3,4` — experience level filter. `2`=Entry, `3`=Associate, `4`=Mid-Senior.
  Other valid values: `1`=Internship, `5`=Director, `6`=Executive.
  Default was changed from `3,4` → `2,3,4` (2026-04) after observing that many
  genuine IC mid-level postings use "Entry" level and were being missed.

## Guest view mechanics (verified 2026-04)

- Pages render server-side HTML initially (~25 cards) + a small JS shim
  that lazy-loads more cards on scroll.
- **STALE selectors (no longer work):**
  - `ul.jobs-search__results-list > li` — class no longer exists
  - `div.base-card` — no longer a top-level container
  - `a.base-card__full-link` — not reachable via the above
- **Working selectors:**
  - Card detection: `Array.from(document.querySelectorAll("li")).filter(li => li.querySelector('a[href*="/jobs/view/"]'))`
    (`<li>` elements now have no class — identify them by whether they contain a job link)
  - Job title: `h3.base-search-card__title` ✅
  - Company name: `h4.base-search-card__subtitle` ✅
  - Location: `.job-search-card__location` ✅
  - Posted time: `time` element — `.getAttribute('datetime')` gives ISO timestamp ✅
  - Job URL: `a[href*="/jobs/view/"]` href attribute ✅
- Clicking a card updates the RIGHT PANEL in-place (no navigation away from search page).
- **Job description text is GATED for guest users.** DOM selectors
  `.show-more-less-html__markup`, `.description__text`, `.scaffold-layout__detail`
  return empty strings for guests. Long-term fix: log into LinkedIn once in the
  OpenClaw browser so the session cookie persists and DOM extraction works.
- List-panel metadata (title, company, location, posted time, applicant count) IS
  available without login and is sufficient for pre-filtering before apply.

## Query quality

Bad queries (produce noise): `"Associate ML Engineer"`, `"Junior AI Engineer"`,
or any query with a seniority prefix. Results get dominated by Senior/Staff/Lead
roles and staffing agency postings.

Good queries (clean signal) for AI/ML IC roles:
- `ML Engineer`
- `AI Engineer`
- `Applied AI Engineer`
- `LLM Engineer`
- `GenAI Engineer`
- `NLP Engineer`
- `Machine Learning Engineer`

Rule: use the pure role name without a seniority prefix. Seniority filtering
happens downstream via `tenant.passes_filter()` → `excluded_levels`. The URL's
`f_E=2,3,4` already limits to Entry/Associate/Mid-Senior at the source.

## Scroll loop

The scout presses the `End` key a few times (default 4) with a ~1.5s
pause between each press. Every press triggers LinkedIn's lazy loader,
which appends another batch of ~25 cards. Four rounds ≈ 100 cards/query,
which is a good runtime/freshness balance.

If LinkedIn starts throttling (cards stop growing after a press), just
live with whatever we already have — do not add retries here. The scout
catches its own errors and returns what it collected.

## Card → JobPost

- `apply_url` is the LinkedIn card URL (`/jobs/view/<slug>-<jobId>`).
  It is **not** a real ATS URL — the applier will hit LinkedIn's
  sign-in wall, at which point Claude's `search_direct_url` action
  kicks in and Googles for the actual ATS form.
- `external_id` is the numeric `<jobId>` at the tail of the URL. Used
  for local SQLite dedup so we don't re-enqueue the same LinkedIn posting.
- `ats` is `"linkedin"` — the applier registry maps that to the
  generic LLM-driven flow, which resolves to the real ATS at apply time.
- `posted_text` is passed through from the `<time>` element for freshness
  logging. The scout drops cards where `_is_stale()` returns True (ISO dates
  or "2+ days ago" patterns — sponsored cards that slip past `f_TPR=r86400`).

## Manual mode (browser hand-off)

When you need to drive the OpenClaw browser manually without the worker racing
against you, set `APPLYLOOP_MANUAL_MODE=1` in the worker's environment before
starting any manual session. The scout loop and apply loop both check this flag
at the top of each iteration and pause until it is unset.

Previous workaround was `kill -9 <pid>` — no longer needed.

```sh
export APPLYLOOP_MANUAL_MODE=1   # pause automation
# ... do your manual browser work ...
unset APPLYLOOP_MANUAL_MODE      # resume — worker picks up on next iteration
```

## Login wall recovery (verified 2026-04)

LinkedIn can redirect to a login/authwall mid-session — most often after several
rapid navigations or when the guest IP has been rate-limited.

Recovery sequence implemented in `_recover_from_login_wall()`:
1. **Refresh ×2** — transient gates (cookie edge case, CDN hiccup) clear on refresh.
2. **Go back ×1** — if refresh doesn't work, navigate back to the previous page
   (the jobs list we were scrolling) and let it reload.
3. **After 3 failed attempts: give up for this query.** LinkedIn is hard-rate-limiting
   this session. The scout logs a warning and moves on to the next keyword.

Detection: `_is_login_wall()` checks both the URL path (`/login`, `/authwall`,
`/checkpoint`, `/uas/login`, `/signup`) and the DOM (no job links + a login form
visible = in-page gate).

**Never blindly keep retrying.** Recognize the pattern and adapt — skip the query
and let the next scout cycle try again with a clean session state.

## "Join LinkedIn" popup dismissal (verified 2026-04)

LinkedIn has a **two-tier popup system**:

| Tier | When | How dismiss button behaves |
|------|------|---------------------------|
| Soft | First few interactions | Dismissible — button click works |
| Hard | After ~5 card clicks | Button click is intercepted by LinkedIn's JS → popup re-renders instantly |

The hard popup also loads Google OAuth iframes (`accounts.google.com/gsi/button`)
as background contexts. Each iframe spawns a separate browser context, causing
blank tabs and `li.protechts.net` tracker tabs to appear alongside the popup.

**ONLY reliable method (confirmed live): press Escape.**
Escape closes the popup shell at the browser level before LinkedIn's JS fires.
Button clicks are caught by LinkedIn's event listener and trigger an immediate
re-render — useless once in hard-popup territory.

The scout calls `_dismiss_popup()`:
- immediately after `navigate_url` lands
- before every `End`-key scroll press
- once more before the final JS extraction

`_dismiss_popup()` always uses Escape, then sweeps stray tabs with
`dismiss_stray_tabs(keep_url_substring="linkedin.com")` to close the Google
OAuth iframe tabs and any `about:blank` / `li.protechts.net` entries.

**Do NOT add button-click logic back to `_dismiss_popup()`.** It was tried,
it doesn't work for the hard popup tier, and it makes the soft popup tier
slower for no gain.

## Guest session interaction limit (verified 2026-04)

LinkedIn guest sessions have a hard limit of **~5 card-click interactions**
before the hard popup locks the session permanently. After that point no
amount of dismissal recovers it — the popup re-renders on every subsequent
action.

Implemented as `_GUEST_CLICK_LIMIT = 5`. The scroll loop tracks
`guest_clicks_used` and stops pressing `End` once the budget is hit, logging:
```
Guest click limit (5) reached — stopping scroll early; rotate to next query to reset
```

**Rotating to a new search URL resets LinkedIn's internal counter.** The scout
resets `guest_clicks = 0` at the start of every query for exactly this reason.
Long-term fix: log in once → limit disappears entirely.

## Bot detection and human-paced delays (verified 2026-04)

Rapid automated key presses (no sleep between) trigger LinkedIn's bot guard:
- `li.protechts.net` tracker tabs spawn alongside the popup
- Blank tabs open as side-effect of the bot detection iframe

`_HUMAN_DELAY_S = 1.8` is enforced between every `End` key press and after
every navigation. Do not remove or reduce this sleep.

## Things that will break this scout (and what to do)

- **LinkedIn renames a CSS class**: update the selectors in `_EXTRACT_JS`.
  Hit the search URL in a normal browser, inspect one card, and verify which
  selectors still resolve. The `h3.base-search-card__title` family has been
  stable; the list container class changes more frequently.
- **`_EXTRACT_JS` returns 0 cards**: most likely a stale container selector.
  Open the search URL in Chrome DevTools, run `document.querySelectorAll("li").length`
  and `document.querySelector('a[href*="/jobs/view/"]')` to verify the DOM shape.
- **OpenClaw browser not running / no session**: scout returns `[]` and
  logs a warning. The worker moves on to other sources. Nothing else
  is affected.
- **LinkedIn gates the search page with a sign-in modal**: rare but
  possible under rate limiting. Extractor returns 0 cards, scout logs
  it, returns `[]`. Back off and retry on the next cycle.

## Filter contract

The scout calls `tenant.passes_filter(title, company, location)` on
every card before keeping it. Role keywords come from
`tenant.linkedin_seed_queries` (falls back to `tenant.search_queries`),
location from `tenant.preferred_locations[0]`. No admin defaults, no
hardcoded role strings — enforced by
`tests/test_scout_contract.py`.
