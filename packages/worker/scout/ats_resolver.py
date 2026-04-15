"""ATS slug resolver — turn a raw company name from a title-based scout
(LinkedIn / Himalayas / Indeed) into a first-class Ashby / Greenhouse /
Lever board slug we can sweep in the next company-based cycle.

The flow:
  title-scout finds "Acme Corp" → normalize_slug_candidates() generates
  ["acme-corp", "acme", "acmecorp"] → probe each candidate against each
  ATS's public board-listing endpoint → first 200 OK wins → return
  {"platform": "ashby", "slug": "acme-corp"}.

No heuristics on the result. If none of the probes returns 200, we
return None and the caller just enqueues the title-scout hit as usual.

This closes the "breadth → depth" loop: companies discovered via title
search today become first-class company-based scout targets tomorrow,
so we never have to rediscover them from LinkedIn.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_ASHBY_PROBE = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
_GREENHOUSE_PROBE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_LEVER_PROBE = "https://api.lever.co/v0/postings/{slug}?mode=json"

# Suffixes worth stripping before slug-ifying. "Inc" and "Corp" never
# appear in the slug; "Labs" / "AI" / "Technologies" sometimes do, so
# we generate variants both ways.
_STRIP_SUFFIXES = (
    "inc", "inc.", "incorporated", "corp", "corp.", "corporation",
    "llc", "ltd", "ltd.", "limited", "co", "co.", "company",
    "gmbh", "s.a.", "sa", "pte", "pty",
)
_SOFT_STRIP = ("labs", "technologies", "ai", "systems", "group")

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def normalize_slug_candidates(company: str) -> list[str]:
    """Produce ordered slug candidates for a company name.

    Example: "Acme Labs, Inc." → ["acme-labs", "acme", "acmelabs", "acme-labs-inc"].
    Caller probes each against each ATS in priority order, first hit wins.
    De-duplicated while preserving order.
    """
    if not company:
        return []
    raw = company.strip().lower()
    # Drop hard suffixes ("Inc", "LLC", …) once up front
    tokens = [t for t in _NON_SLUG.split(raw) if t]
    while tokens and tokens[-1] in _STRIP_SUFFIXES:
        tokens.pop()
    if not tokens:
        return []
    candidates: list[str] = []

    def _add(slug: str) -> None:
        if slug and slug not in candidates and 2 <= len(slug) <= 60:
            candidates.append(slug)

    _add("-".join(tokens))
    _add("".join(tokens))  # e.g. "openai"
    # Without soft-strip tokens at the end
    trimmed = tokens[:]
    while trimmed and trimmed[-1] in _SOFT_STRIP:
        trimmed.pop()
    if trimmed and trimmed != tokens:
        _add("-".join(trimmed))
        _add("".join(trimmed))
    _add(tokens[0])  # first token alone (e.g. "acme")
    return candidates


def try_resolve_ats_slug(company: str, timeout: float = 4.0) -> Optional[dict]:
    """Probe Ashby / Greenhouse / Lever public board APIs for `company`.

    Returns the first platform+slug that returns HTTP 200. Returns None
    if every candidate on every platform 404s, which means either the
    company doesn't use any of these ATSes OR our slug guesses missed.
    Silent on network errors — this is best-effort enrichment, never
    fatal to the scout cycle.
    """
    candidates = normalize_slug_candidates(company)
    if not candidates:
        return None
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            for slug in candidates:
                for platform, url_template in (
                    ("ashby", _ASHBY_PROBE),
                    ("greenhouse", _GREENHOUSE_PROBE),
                    ("lever", _LEVER_PROBE),
                ):
                    try:
                        r = client.get(url_template.format(slug=slug))
                    except Exception:
                        continue
                    if r.status_code == 200:
                        logger.info(
                            f"ats_resolver: {company!r} → {platform}:{slug}"
                        )
                        return {"platform": platform, "slug": slug}
    except Exception as e:
        logger.debug(f"ats_resolver probe failed for {company!r}: {e}")
    return None
