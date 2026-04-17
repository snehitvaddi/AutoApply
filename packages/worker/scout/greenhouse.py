"""Greenhouse scout plugin — polls each board in tenant.greenhouse_boards.

Ported from worker.scout_greenhouse_boards. Submit feasibility (reCAPTCHA)
is NOT checked here — that happens at apply time in GreenhouseApplier. Scout
just discovers; filter decides per-tenant relevance.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import httpx

from .ashby import _is_fresh_24h
from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig


def _fetch_greenhouse_board(slug: str, tenant: "TenantConfig") -> list[JobPost]:
    jobs: list[JobPost] = []
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
            if resp.status_code != 200:
                return jobs
            for job in resp.json().get("jobs", []):
                if not _is_fresh_24h(job.get("updated_at")):
                    continue
                title = job.get("title", "")
                loc = job.get("location", {})
                if isinstance(loc, dict):
                    loc = loc.get("name", "")
                if not tenant.passes_filter(title, slug, loc):
                    continue
                job_id = job.get("id", "")
                jobs.append({
                    "title": title,
                    "company": slug,
                    "location": loc,
                    "apply_url": f"https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}",
                    "external_id": str(job_id),
                    "ats": "greenhouse",
                })
    except Exception:
        pass
    return jobs


class GreenhouseScout(ScoutSource):
    name = "greenhouse"
    priority = "high"
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        # Parallel board fetch — 8 workers keeps API pressure modest but
        # cuts ~74 × 0.5s serialization to a few seconds.
        jobs: list[JobPost] = []
        boards = list(tenant.greenhouse_boards)
        if not boards:
            return jobs
        with ThreadPoolExecutor(max_workers=8) as pool:
            for fut in as_completed(pool.submit(_fetch_greenhouse_board, s, tenant) for s in boards):
                try:
                    jobs.extend(fut.result())
                except Exception as e:
                    self.logger.debug(f"greenhouse board fetch failed: {e}")
        return jobs
