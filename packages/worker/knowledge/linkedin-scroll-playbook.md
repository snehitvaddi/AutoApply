# LinkedIn Scroll Playbook (no login required)

Operational notes for anyone debugging `scout/linkedin_scroll.py` or extending
LinkedIn ingestion. Written for the Claude-in-terminal driver and for humans.

## Entry URLs (both shapes work)

Guest job search accepts two equivalent shapes. The scout uses the second
(more general) form but either will work:

1. Category-framed:
   `https://www.linkedin.com/jobs/ai-engineer-jobs?keywords=Ai%20Engineer&location=United%20States&geoId=103644278&f_TPR=r86400&position=1&pageNum=0`
2. Generic search (what the scout builds):
   `https://www.linkedin.com/jobs/search?keywords=<q>&location=<loc>&geoId=103644278&f_TPR=r86400&f_E=3,4&position=1&pageNum=0`

### Relevant query params

- `keywords` — role query (URL-encoded)
- `location` — free-text location (URL-encoded)
- `geoId=103644278` — internal geo ID for "United States"
- `f_TPR=r86400` — time-posted-range = last 24 hours
- `f_E=3,4` — experience level filter. `3`=Associate, `4`=Mid-Senior. Other
  valid values: `1`=Internship, `2`=Entry, `5`=Director, `6`=Executive.

## Guest view mechanics

- Pages render server-side HTML initially (~25 cards) + a small JS shim
  that lazy-loads more cards on scroll.
- Cards live in `ul.jobs-search__results-list > li` OR as top-level
  `div.base-card` elements depending on viewport width.
- Each card exposes: `a.base-card__full-link` (job URL),
  `h3.base-search-card__title`, `h4.base-search-card__subtitle` (company),
  `span.job-search-card__location`.
- No login is required for the search page. The *individual job page*
  may show a sign-in modal — that is handled downstream by
  `llm_first_apply` (LinkedIn gate → Google search → ATS URL).

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

## Things that will break this scout (and what to do)

- **LinkedIn renames a CSS class**: update the selectors in `_EXTRACT_JS`.
  Hit the search URL in a normal browser, inspect one card, and paste
  the new class names in. Leave the old selectors in as a fallback
  (the JS uses `querySelectorAll` with a comma-separated list).
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
