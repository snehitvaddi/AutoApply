"""LinkedIn scroll scout — headful OpenClaw browser, no login required.

The existing `linkedin_public.py` scout uses scrapling's HTTP Fetcher
against LinkedIn's guest view — fast but only returns the first page
(~25 jobs) and silently fails when LinkedIn decides to gate the
response behind a sign-in modal.

This scout drives the real OpenClaw headful browser: navigate to the
guest job search URL, scroll a few times to trigger lazy-loaded cards,
then extract title/company/location/job URL via a single JS snippet.

Card URLs are LinkedIn `/jobs/view/<slug>-<jobId>` links. The Claude
brain (packages/worker/brain/) handles LinkedIn sign-in walls at apply
time by running a Google search for the company + title and
auto-navigating to the first ATS result (greenhouse / lever / ashby /
workday / smartrecruiters). So we do NOT need to resolve to a real ATS
URL here — just surface the LinkedIn card and let the brain drive.

Guest-mode DOM notes (verified 2026-04):
  - ul.jobs-search__results-list and div.base-card selectors are STALE.
  - Working selectors: <li> elements that contain a[href*="/jobs/view/"]
  - h3.base-search-card__title, h4.base-search-card__subtitle still work.
  - Job description text is gated behind login — not extractable as guest.
  - List-panel metadata (title, company, location, posted time, applicant
    count) IS available as guest and sufficient for pre-filtering.

Two LinkedIn URL shapes are supported via the same builder:
  - /jobs/search?keywords=...&location=...&f_TPR=r86400
  - /jobs/search?keywords=...&location=...&f_TPR=r86400&f_E=2,3,4
    (experience filter: 2=Entry, 3=Associate, 4=Mid-Senior)
"""
from __future__ import annotations

import re
import time
import logging
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from applier.greenhouse import (
    browser, navigate_url, wait_load, evaluate_js,
)
from applier.browser import dismiss_stray_tabs

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig

logger = logging.getLogger(__name__)


# LinkedIn's geoId for "United States". Hardcoded because it's a stable
# LinkedIn internal identifier, not a role keyword — tests allow this.
_GEO_US = "103644278"

# Experience filter values on LinkedIn guest search:
#   1=Internship, 2=Entry, 3=Associate, 4=Mid-Senior, 5=Director, 6=Executive
# Include Entry (2) so mid-level IC postings that skip the "Associate" label
# are not missed. Senior/Lead/Staff are caught by seniority filter downstream.
_EXP_DEFAULT = "2,3,4"

# How many times to press End to trigger LinkedIn's infinite-scroll
# loader. Each press typically loads ~25 more cards. 4 scrolls ≈ 100
# cards per query — good balance between freshness and runtime.
_SCROLL_ROUNDS = 4

# LinkedIn guest sessions allow ~5 card-click interactions before the
# hard popup locks the session permanently (regardless of dismissal).
# Verified live 2026-04: after ~5 clicks, the "Join LinkedIn" modal
# re-renders instantly after every dismiss attempt, including button clicks.
# Rotate to the next query keyword rather than fighting it — a new search
# URL resets the session counter. Log in once to remove the limit entirely.
_GUEST_CLICK_LIMIT = 5

# Human-paced delay between any browser interactions (key presses, clicks).
# Rapid automated actions trigger LinkedIn's bot guard (li.protechts.net)
# which spawns blank tracker tabs and escalates the popup to the hard tier.
_HUMAN_DELAY_S = 1.8


def _search_url(keywords: str, location: str, exp: str = _EXP_DEFAULT) -> str:
    q = quote_plus(keywords)
    loc = quote_plus(location)
    return (
        f"https://www.linkedin.com/jobs/search"
        f"?keywords={q}&location={loc}&geoId={_GEO_US}"
        f"&f_TPR=r86400&f_E={exp}&position=1&pageNum=0"
    )


# Selectors verified against live LinkedIn guest DOM (2026-04).
# The old ul.jobs-search__results-list and div.base-card are stale —
# LinkedIn no longer renders those class names. <li> elements with no
# class now wrap each card; we identify them by whether they contain a
# /jobs/view/ anchor.
_EXTRACT_JS = r"""
() => {
  const cards = Array.from(document.querySelectorAll("li"))
    .filter(li => li.querySelector('a[href*="/jobs/view/"]'));
  const out = [];
  for (const li of cards) {
    const link    = li.querySelector('a[href*="/jobs/view/"]');
    const title   = li.querySelector('h3.base-search-card__title');
    const company = li.querySelector('h4.base-search-card__subtitle');
    const loc     = li.querySelector('.job-search-card__location');
    const timeEl  = li.querySelector('time');
    const metaEl  = li.querySelector('.job-search-card__benefits, .job-search-card__easy-apply-label');
    if (!link || !title) continue;
    const href = (link.getAttribute('href') || '').split('?')[0];
    out.push({
      title:         (title.textContent   || '').trim(),
      company:       (company ? company.textContent : '').trim(),
      location:      (loc     ? loc.textContent     : '').trim(),
      href,
      posted_text:   (timeEl  ? (timeEl.getAttribute('datetime') || timeEl.textContent || '') : '').trim(),
      meta_text:     (metaEl  ? metaEl.textContent : '').trim(),
    });
  }
  return JSON.stringify(out);
}
"""

# Matches posted_text values that are clearly stale (over 24h).
# f_TPR=r86400 should keep LinkedIn's results to 24h, but the DOM
# sometimes shows older promoted/sponsored cards that slip through.
_STALE_POSTED_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}|"   # ISO date = older than today
    r"\b([2-9]\d+|[1-9]\d+)\s+days?\s+ago\b",  # "2 days ago" or more
    re.IGNORECASE,
)

# JS that detects whether we are on a login/auth wall rather than a job list.
# Returns "wall" | "ok".
_LOGIN_WALL_CHECK_JS = r"""
() => {
  const url = window.location.href;
  if (/\/(login|authwall|checkpoint|signup|uas\/login)/i.test(url)) return "wall";
  // Also catch in-page login gates: if jobs list is gone AND a login form exists
  const hasJobs = !!document.querySelector('a[href*="/jobs/view/"]');
  const hasLoginForm = !!document.querySelector('form.login__form, input[name="session_key"]');
  if (!hasJobs && hasLoginForm) return "wall";
  return "ok";
}
"""

def _dismiss_popup() -> bool:
    """Close any 'Join LinkedIn' / sign-in overlay using Escape ONLY.

    CRITICAL: Do NOT click the button[aria-label="Dismiss"] button.
    Verified live 2026-04: LinkedIn's JS intercepts the button click and
    re-renders the popup immediately. After ~5 guest interactions it upgrades
    to a "hard" popup backed by Google OAuth iframes (accounts.google.com/gsi/
    button) — clicking dismiss triggers the iframe re-render cycle instantly.
    Escape closes the popup shell at the browser level before LinkedIn's JS
    can react — the only reliable method confirmed in live testing.

    After Escape, sweep any stray blank / tracker tabs that the popup's Google
    OAuth iframes may have spawned (li.protechts.net, about:blank). Keeping
    the browser single-tabbed on linkedin.com prevents future snapshots from
    targeting the wrong context.
    """
    try:
        browser("press Escape", timeout=3)
        time.sleep(0.5)
    except Exception:
        pass
    # Sweep blank tabs and li.protechts.net tracker tabs that the hard popup's
    # Google OAuth iframes spawn. Keep only the linkedin.com tab.
    try:
        closed = dismiss_stray_tabs(keep_url_substring="linkedin.com")
        if closed:
            logger.debug(f"Swept {closed} stray tab(s) after popup Escape")
    except Exception:
        pass
    return True


def _is_login_wall() -> bool:
    """Return True if the current page is a LinkedIn login/auth wall."""
    try:
        raw = evaluate_js(_LOGIN_WALL_CHECK_JS) or ""
        return "wall" in raw.lower()
    except Exception:
        return False


def _recover_from_login_wall(search_url: str, max_attempts: int = 3) -> bool:
    """Try to get back to the jobs list after LinkedIn redirected to a login wall.

    Strategy (verified from live session 2026-04):
      1. Refresh the page (1–2 times) — often enough for transient gates.
      2. If still blocked: navigate Back repeatedly until the jobs list returns.
      3. After max_attempts: give up — LinkedIn is hard-rate-limiting this
         session. Caller should skip this query and log a warning.

    Returns True if the jobs list was successfully recovered.
    """
    for attempt in range(1, max_attempts + 1):
        # First two tries: refresh
        if attempt <= 2:
            logger.info(f"Login wall detected — refreshing (attempt {attempt}/{max_attempts})")
            try:
                browser("refresh", timeout=8)
                time.sleep(3)
            except Exception:
                pass
        else:
            # Subsequent tries: navigate back
            logger.info(f"Login wall persists — navigating back (attempt {attempt}/{max_attempts})")
            try:
                browser("go back", timeout=5)
                time.sleep(2)
            except Exception:
                pass

        _dismiss_popup()

        if not _is_login_wall():
            # Verify jobs actually loaded, not just a blank or error page
            try:
                raw = evaluate_js("() => !!document.querySelector('a[href*=\"/jobs/view/\"]')") or ""
                if "true" in raw.lower():
                    logger.info(f"Recovered jobs list after {attempt} attempt(s)")
                    return True
            except Exception:
                pass

    logger.warning(
        f"LinkedIn is hard-rate-limiting guest access after {max_attempts} recovery "
        f"attempts. LinkedIn may be forcing login for this session. Skipping this query."
    )
    return False


def _scroll_and_extract(
    search_url: str,
    rounds: int = _SCROLL_ROUNDS,
    guest_clicks_used: int = 0,
) -> tuple[list[dict], int]:
    """Scroll to load more cards, then extract.

    Returns (cards, updated_guest_clicks_used). The caller passes the
    running guest_clicks_used total across queries so we can bail early
    if we've burned through the session's ~5-click budget.

    Human-paced delays (_HUMAN_DELAY_S) between every key press prevent
    LinkedIn's bot guard from triggering blank tracker tabs (li.protechts.net).

    Handles:
      - Login wall mid-scroll: refresh → back → give up (see _recover).
      - Join LinkedIn popup: Escape + stray tab sweep before each press.
      - Guest click limit (~5): stop scrolling and return what we have.
    """
    import json as _json

    clicks = guest_clicks_used
    for _ in range(rounds):
        if clicks >= _GUEST_CLICK_LIMIT:
            logger.info(
                f"Guest click limit ({_GUEST_CLICK_LIMIT}) reached — "
                f"stopping scroll early; rotate to next query to reset"
            )
            break

        if _is_login_wall():
            if not _recover_from_login_wall(search_url):
                return [], clicks

        _dismiss_popup()

        try:
            browser("press End", timeout=3)
            clicks += 1
        except Exception:
            pass
        time.sleep(_HUMAN_DELAY_S)

    # Final sweep before DOM read
    _dismiss_popup()

    if _is_login_wall():
        if not _recover_from_login_wall(search_url):
            return [], clicks

    raw = evaluate_js(_EXTRACT_JS) or ""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return [], clicks
    try:
        return _json.loads(m.group(0)), clicks
    except Exception as e:
        logger.warning(f"LinkedIn extract JSON parse failed: {e}")
        return [], clicks


def _is_stale(posted_text: str) -> bool:
    """Return True if the posted_text indicates the card is older than 24h.

    LinkedIn's f_TPR=r86400 filter handles most of this, but sponsored
    and promoted cards occasionally slip through with older dates.
    """
    if not posted_text:
        return False
    return bool(_STALE_POSTED_RE.search(posted_text.strip()))


def _external_id(href: str) -> str:
    """Extract the numeric jobId tail from a LinkedIn job URL."""
    if not href:
        return ""
    tail = href.rstrip("/").split("-")[-1]
    return tail if tail.isdigit() else href.rstrip("/").split("/")[-1]


class LinkedInScrollScout(ScoutSource):
    name = "linkedin_scroll"
    priority = "high"  # live 24h window, scrolled — freshest single source
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        loc = tenant.preferred_locations[0] if tenant.preferred_locations else "United States"
        queries = list(tenant.linkedin_seed_queries or tenant.search_queries or [])
        if not queries:
            return []

        seen: set[str] = set()
        out: list[JobPost] = []
        # Guest click budget is shared across all queries in this scout cycle.
        # Navigating to a new search URL resets LinkedIn's internal counter,
        # so we reset ours too at each query boundary.
        guest_clicks: int = 0

        for q in queries:
            guest_clicks = 0  # new URL = fresh session context on LinkedIn's side
            url = _search_url(q, loc)
            try:
                navigate_url(url)
                wait_load(6000)
                time.sleep(_HUMAN_DELAY_S)
                # Dismiss any sign-in popup that loaded with the page
                _dismiss_popup()
                # If the navigation itself landed on a login wall, try to recover
                # before investing time in scroll rounds
                if _is_login_wall():
                    if not _recover_from_login_wall(url):
                        self.logger.warning(
                            f"LinkedIn scroll [{q}]: login wall unrecoverable — "
                            f"skipping query (LinkedIn forcing login for this session)"
                        )
                        continue
                cards, guest_clicks = _scroll_and_extract(url, guest_clicks_used=guest_clicks)
            except Exception as e:
                self.logger.warning(f"LinkedIn scroll [{q}] failed: {e}")
                continue

            stale = 0
            kept = 0
            for c in cards:
                title = (c.get("title") or "").strip()
                company = (c.get("company") or "").strip()
                location = (c.get("location") or "").strip()
                href = (c.get("href") or "").strip()
                posted_text = (c.get("posted_text") or "").strip()
                if not title or not href:
                    continue
                if href in seen:
                    continue
                seen.add(href)
                if _is_stale(posted_text):
                    stale += 1
                    continue
                if not tenant.passes_filter(title, company, location):
                    continue
                out.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "apply_url": href,
                    "external_id": _external_id(href),
                    "ats": "linkedin",
                    "posted_text": posted_text,
                })
                kept += 1
            self.logger.info(
                f"LinkedIn scroll [{q}]: {len(cards)} cards, "
                f"{kept} kept, {stale} stale"
            )

        return out
