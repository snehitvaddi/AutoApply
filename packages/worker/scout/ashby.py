"""Ashby scout plugin — polls each board in tenant.ashby_boards.

Ported from worker.scout_ashby_boards. The important change: every filter
decision now routes through tenant.passes_filter() instead of the old
passes_filter(user_prefs=None) fallback that silently leaked admin defaults.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig


def _fetch_ashby_board(slug: str, tenant: "TenantConfig") -> list[JobPost]:
    jobs: list[JobPost] = []
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            if resp.status_code != 200:
                return jobs
            for job in resp.json().get("jobs", []):
                if not _is_fresh_24h(job.get("publishedAt")):
                    continue
                title = job.get("title", "")
                loc = job.get("location", "")
                if isinstance(loc, dict):
                    loc = loc.get("name", "")
                if not tenant.passes_filter(title, slug, loc):
                    continue
                apply_url = (
                    job.get("applicationUrl")
                    or f"https://jobs.ashbyhq.com/{slug}/application?jobId={job['id']}"
                )
                jobs.append({
                    "title": title,
                    "company": slug,
                    "location": loc,
                    "apply_url": apply_url,
                    "external_id": str(job.get("id", "")),
                    "ats": "ashby",
                })
    except Exception:
        pass
    return jobs


class AshbyScout(ScoutSource):
    name = "ashby"
    priority = "high"
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        jobs: list[JobPost] = []
        boards = list(tenant.ashby_boards)
        if not boards:
            return jobs
        with ThreadPoolExecutor(max_workers=8) as pool:
            for fut in as_completed(pool.submit(_fetch_ashby_board, s, tenant) for s in boards):
                try:
                    jobs.extend(fut.result())
                except Exception as e:
                    self.logger.debug(f"ashby board fetch failed: {e}")
        return jobs


def _is_fresh_24h(date_value) -> bool:
    """Return True if date_value is within the last 24h or unparseable."""
    if not date_value:
        return True
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    try:
        if isinstance(date_value, (int, float)):
            ts = date_value if date_value < 1e12 else date_value / 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt >= cutoff
        s = str(date_value).strip()
        if "T" in s:
            s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff
        if len(s) == 10 and s[4] == "-":
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt >= cutoff
    except Exception:
        pass
    return True
