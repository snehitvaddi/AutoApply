"""Google-site search scout — finds ATS apply URLs via search-engine
`site:` restrictions.

Inspired by Brian's Job Search (briansjobsearch.com): instead of polling
each ATS's posting API or scraping LinkedIn, build site-restricted search
queries against Greenhouse, Lever, Ashby, SmartRecruiters, and Workday,
and parse the search results to surface fresh job URLs.

Why this complements the per-ATS scouts:
  - Catches small ATS slugs we don't have in default_boards.py yet —
    every result is a candidate for `scout_propose_board`.
  - Workday in particular has no public posting API; this is the only
    practical source for Workday jobs short of per-company scraping.
  - Same role-keyword targeting as the LinkedIn scroll scout, but no
    guest-click budget and no anti-bot wall.

Search backend: Startpage. We tried DuckDuckGo first; their `/html/`
endpoint started returning a 2.9KB shell with no results in 2026-Q2,
and Brave Search rate-limits unauthenticated UAs. Startpage is built
on Google results (privacy proxy) and parses cleanly: each result is a
`<a class="result-title result-link">` containing an `<h2 class="wgl-title">`
with the page title and a sibling `<p class="description">` snippet.

Per cycle this issues `len(target_titles) × len(ats_hosts)` queries —
about 25 for a 5-title tenant — paced at 0.5s/query so we stay
well under any reasonable rate limit.
"""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig

logger = logging.getLogger(__name__)

# Search-engine endpoint + UA. Startpage rejects the default httpx UA
# with a JS-only shell page; a real-browser UA returns the static
# server-rendered results.
_STARTPAGE_URL = "https://www.startpage.com/sp/search"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HTTP_TIMEOUT = 15.0
# Pace between queries — gentle enough that 25 queries in a cycle don't
# trip rate limits or look like an attack.
_QUERY_PAUSE_S = 0.6

# ATS host map — each entry is (display name, list of search-engine
# `site:` host strings). Multiple sites per ATS because companies
# straddle URL conventions (Greenhouse boards.* vs job-boards.*).
_ATS_QUERY_SITES: dict[str, list[str]] = {
    "greenhouse":      ["boards.greenhouse.io", "job-boards.greenhouse.io"],
    "lever":           ["jobs.lever.co"],
    "ashby":           ["jobs.ashbyhq.com"],
    "smartrecruiters": ["jobs.smartrecruiters.com"],
    "workday":         ["myworkdayjobs.com"],
}

# Reverse map host substring → ATS, used to classify a result URL.
_HOST_TO_ATS: list[tuple[str, str]] = [
    (host, ats) for ats, hosts in _ATS_QUERY_SITES.items() for host in hosts
]


def _classify_ats(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None
    for needle, ats in _HOST_TO_ATS:
        if needle in host:
            return ats
    return None


def _slug_from_url(url: str, ats: str) -> str | None:
    """Best-effort slug pull. Used to grow board pools via
    `scout_propose_board` and to route the apply through the right
    recipe.
    """
    try:
        u = urlparse(url)
        path = u.path.strip("/").split("/")
        host = u.netloc.lower()
    except Exception:
        return None
    if not path or not path[0]:
        return None
    if ats in ("greenhouse", "lever", "ashby", "smartrecruiters"):
        return path[0].lower()
    if ats == "workday":
        return host.split(".")[0].lower()
    return None


def _looks_like_job_posting(url: str, ats: str) -> bool:
    """Filter out company/career index pages; keep individual postings.

    The same site:-restricted query can return a company's careers
    landing page and individual job URLs. Index pages cause the apply
    loop to choke (no form to fill). The path-shape heuristics here
    are deliberately loose — false negatives just mean we lose a
    posting; false positives waste an apply attempt.
    """
    p = urlparse(url).path.lower()
    if ats == "greenhouse":
        return "/jobs/" in p and len(p.split("/jobs/")[-1]) >= 4
    if ats == "lever":
        return p.count("/") >= 2
    if ats == "ashby":
        # Real Ashby posting paths contain a UUID-like segment (8-4-4-4-12).
        return bool(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", p))
    if ats == "smartrecruiters":
        return p.count("/") >= 2
    if ats == "workday":
        return "/job/" in p or "/jobs/" in p
    return False


# Result-block extraction. Startpage wraps each result in:
#   <a class="result-title result-link css-XXX" href="<url>">
#     <h2 class="wgl-title css-XXX">TITLE</h2>
#   </a>
#   <p class="description css-XXX">SNIPPET</p>
# We capture (url, h2-title, snippet) per block.
_RESULT_BLOCK_RE = re.compile(
    r'<a[^>]+class="result-title result-link[^"]*"[^>]+href="([^"]+)"[^>]*>'
    r'.*?'
    r'<h2[^>]+class="wgl-title[^"]*"[^>]*>(.*?)</h2>'
    r'.*?</a>'
    r'(?:.*?<p[^>]+class="description[^"]*"[^>]*>(.*?)</p>)?',
    re.DOTALL,
)


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _split_h2_into_title_company(h2_text: str, fallback_company: str) -> tuple[str, str]:
    """Startpage h2 looks like `"Backend Engineer @ Distyl - Jobs"` or
    `"Staff Software Engineer | Acme Corp - Jobs"`. Pull the role + company.
    Falls back to (h2_text, slug) when the separators aren't there.
    """
    text = h2_text.strip()
    # Strip trailing " - Jobs" / " | Acme Careers" suffixes that Startpage
    # appends from the page <title>. Heuristic: keep everything before
    # the LAST " - " segment iff it looks like a company-suffix tag.
    # Conservative: only strip "Jobs" / "Careers" / "Job Board" / similar.
    text = re.sub(
        r"\s*[-|–]\s*(jobs|careers|job board|job openings|hiring)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # "Role @ Company"
    if " @ " in text:
        role, company = text.split(" @ ", 1)
        return role.strip(), company.strip() or fallback_company
    # "Role | Company"
    if " | " in text:
        role, company = text.split(" | ", 1)
        return role.strip(), company.strip() or fallback_company
    # "Role - Company"
    if " - " in text:
        # Only treat as role-company if the right side looks like a name
        # (not a location / employment type). Keep the rule loose:
        # right side ≤4 words and starts with a capital.
        left, right = text.rsplit(" - ", 1)
        right_words = right.split()
        if right_words and right_words[0][:1].isupper() and len(right_words) <= 4:
            return left.strip(), right.strip() or fallback_company
    # Couldn't split — return as-is. Tenant filter still gets a chance.
    return text, fallback_company


def _search_startpage(query: str) -> list[dict]:
    """One Startpage search → list of {url, title_text, snippet}.

    Soft-fails to [] on any HTTP / parse error so a single bad query
    doesn't poison the whole scout cycle.
    """
    try:
        with httpx.Client(
            timeout=_HTTP_TIMEOUT, follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as c:
            r = c.get(_STARTPAGE_URL, params={"q": query})
        if r.status_code != 200:
            logger.debug(f"Startpage status {r.status_code} for query {query!r}")
            return []
        html = r.text
    except Exception as e:
        logger.debug(f"Startpage fetch failed for {query!r}: {e}")
        return []

    out: list[dict] = []
    for m in _RESULT_BLOCK_RE.finditer(html):
        url = m.group(1).strip()
        title_text = _strip_tags(m.group(2) or "")
        snippet = _strip_tags(m.group(3) or "")
        if not url or not title_text:
            continue
        out.append({"url": url, "title_text": title_text, "snippet": snippet})
    return out


class GoogleSiteScout(ScoutSource):
    """Brian-style site-restricted search across the major ATSes.

    Per cycle: for each tenant.search_queries title, run one
    site-restricted query against each known ATS host. Parse results,
    classify by host, extract slug, run tenant.passes_filter, return
    a JobPost per surviving result.
    """

    name = "google_site"
    priority = "medium"  # broader reach than per-ATS scouts, but
                         # noisier — let high-priority sources win
                         # the dedup race for known slugs.
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        queries = list(tenant.search_queries or [])
        if not queries:
            return []

        seen_urls: set[str] = set()
        out: list[JobPost] = []

        for title in queries:
            for ats, sites in _ATS_QUERY_SITES.items():
                site_clause = " OR ".join(f"site:{s}" for s in sites)
                q = f'({site_clause}) "{title}"'
                try:
                    results = _search_startpage(q)
                except Exception as e:
                    self.logger.debug(f"google_site [{title}/{ats}] search err: {e}")
                    results = []
                kept = 0
                for r in results:
                    url = r["url"].split("?")[0].rstrip("/")
                    if url in seen_urls:
                        continue
                    classified = _classify_ats(url)
                    if classified != ats:
                        # Cross-host bleed (a SmartRecruiters URL surfacing
                        # in a Workday-restricted query, etc.). Trust the
                        # actual host, not the query.
                        ats = classified or ats
                    if not _looks_like_job_posting(url, ats):
                        continue
                    seen_urls.add(url)
                    slug = _slug_from_url(url, ats) or ""
                    role, company = _split_h2_into_title_company(
                        r["title_text"], fallback_company=slug
                    )
                    # Default location to empty; passes_filter only
                    # excludes against an explicit preferred_locations
                    # list, so blank text is permissive.
                    location = ""
                    if not tenant.passes_filter(role, company, location):
                        continue
                    out.append({
                        "title":       role,
                        "company":     company,
                        "location":    location,
                        "apply_url":   url,
                        "external_id": slug,
                        "ats":         ats,
                        "posted_text": "",
                    })
                    kept += 1
                self.logger.info(
                    f"google_site [{title}/{ats}]: "
                    f"{len(results)} hits → {kept} kept"
                )
                # Pace queries so 25-per-cycle doesn't look like an attack.
                time.sleep(_QUERY_PAUSE_S)

        return out
