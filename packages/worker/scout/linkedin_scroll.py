"""LinkedIn scroll scout — headful OpenClaw browser, no login required.

The existing `linkedin_public.py` scout uses scrapling's HTTP Fetcher
against LinkedIn's guest view — fast but only returns the first page
(~25 jobs) and silently fails when LinkedIn decides to gate the
response behind a sign-in modal.

This scout drives the real OpenClaw headful browser: navigate to the
guest job search URL, scroll a few times to trigger lazy-loaded cards,
then extract title/company/location/job URL via a single JS snippet.

Card URLs are LinkedIn `/jobs/view/<slug>-<jobId>` links. The downstream
llm_first_apply loop handles LinkedIn sign-in walls by running a Google
search for the company + title and auto-navigating to the first ATS
result (greenhouse/lever/ashby/workday/smartrecruiters). So we do NOT
need to resolve to a real ATS URL here — just surface the LinkedIn card
and let Claude drive the rest.

Two LinkedIn URL shapes are supported via the same builder:
  - /jobs/search?keywords=...&location=...&f_TPR=r86400
  - /jobs/search?keywords=...&location=...&f_TPR=r86400&f_E=3,4
    (experience filter: 3=Associate, 4=Mid-Senior)
"""
from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from applier.greenhouse import (
    browser, navigate_url, wait_load, evaluate_js,
)

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig

logger = logging.getLogger(__name__)


# LinkedIn's geoId for "United States". Hardcoded because it's a stable
# LinkedIn internal identifier, not a role keyword — tests allow this.
_GEO_US = "103644278"

# Experience filter values on LinkedIn guest search:
#   1=Internship, 2=Entry, 3=Associate, 4=Mid-Senior, 5=Director, 6=Executive
# The user's tenant profile mostly targets mid-senior IC roles, so default
# to 3,4. Admin can override via tenant.linkedin_experience (future knob).
_EXP_DEFAULT = "3,4"

# How many times to press End to trigger LinkedIn's infinite-scroll
# loader. Each press typically loads ~25 more cards. 4 scrolls ≈ 100
# cards per query — good balance between freshness and runtime.
_SCROLL_ROUNDS = 4


def _search_url(keywords: str, location: str, exp: str = _EXP_DEFAULT) -> str:
    q = quote_plus(keywords)
    loc = quote_plus(location)
    return (
        f"https://www.linkedin.com/jobs/search"
        f"?keywords={q}&location={loc}&geoId={_GEO_US}"
        f"&f_TPR=r86400&f_E={exp}&position=1&pageNum=0"
    )


_EXTRACT_JS = r"""
() => {
  const cards = document.querySelectorAll(
    'ul.jobs-search__results-list > li, div.base-card'
  );
  const out = [];
  for (const c of cards) {
    const link = c.querySelector('a.base-card__full-link, a[data-tracking-control-name*="job-card"]');
    const title = c.querySelector('h3.base-search-card__title, .base-search-card__title');
    const company = c.querySelector('h4.base-search-card__subtitle a, .base-search-card__subtitle');
    const loc = c.querySelector('.job-search-card__location');
    if (!link || !title) continue;
    const href = (link.getAttribute('href') || '').split('?')[0];
    out.push({
      title: (title.textContent || '').trim(),
      company: (company ? company.textContent : '').trim(),
      location: (loc ? loc.textContent : '').trim(),
      href,
    });
  }
  return JSON.stringify(out);
}
"""


def _scroll_and_extract(rounds: int = _SCROLL_ROUNDS) -> list[dict]:
    """Scroll to load more cards, then extract. Tolerates JS errors —
    returns whatever was on screen at the time of the failure."""
    for i in range(rounds):
        try:
            browser("press End", timeout=3)
        except Exception:
            pass
        time.sleep(1.5)
    raw = evaluate_js(_EXTRACT_JS) or ""
    # OpenClaw wraps JS return values; strip to the JSON payload.
    import re as _re, json as _json
    m = _re.search(r"\[.*\]", raw, _re.S)
    if not m:
        return []
    try:
        return _json.loads(m.group(0))
    except Exception as e:
        logger.warning(f"LinkedIn extract JSON parse failed: {e}")
        return []


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

        for q in queries:
            url = _search_url(q, loc)
            try:
                navigate_url(url)
                wait_load(6000)
                time.sleep(2)
                cards = _scroll_and_extract()
            except Exception as e:
                self.logger.warning(f"LinkedIn scroll [{q}] failed: {e}")
                continue

            kept = 0
            for c in cards:
                title = (c.get("title") or "").strip()
                company = (c.get("company") or "").strip()
                location = (c.get("location") or "").strip()
                href = (c.get("href") or "").strip()
                if not title or not href:
                    continue
                if href in seen:
                    continue
                seen.add(href)
                if not tenant.passes_filter(title, company, location):
                    continue
                out.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "apply_url": href,
                    "external_id": _external_id(href),
                    "ats": "linkedin",
                })
                kept += 1
            self.logger.info(f"LinkedIn scroll [{q}]: {len(cards)} cards, {kept} kept")

        return out
