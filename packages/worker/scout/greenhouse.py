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


def _fetch_greenhouse_board(slug: str, tenant: "TenantConfig") -> tuple[list[JobPost], str | None]:
    """Fetch one board. Returns (jobs, error_str). error_str is None on success,
    a short label like 'http_500', 'connect_error', 'timeout', or
    'parse_error' on failure. The caller aggregates these so the dispatcher
    can tell the agent 'all 74 boards failed: connect_error' vs '74 boards
    polled, no new jobs.'"""
    jobs: list[JobPost] = []
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
            if resp.status_code != 200:
                return jobs, f"http_{resp.status_code}"
            for job in resp.json().get("jobs", []):
                # See scout/ashby.py for rationale — Greenhouse boards API
                # only lists currently-open jobs. Dropping by updated_at
                # <24h eliminates everything (most listings sit open for
                # weeks). Local stale-queue prune handles "sat in our
                # queue too long" separately.
                title = job.get("title", "")
                loc = job.get("location", {})
                if isinstance(loc, dict):
                    loc = loc.get("name", "")
                if not tenant.passes_filter(title, slug, loc):
                    continue
                job_id = job.get("id", "")
                # Greenhouse exposes updated_at and first_published on
                # each job. Prefer first_published as the canonical
                # "posted at"; fall back to updated_at.
                posted_at = job.get("first_published") or job.get("updated_at") or None
                jobs.append({
                    "title": title,
                    "company": slug,
                    "location": loc,
                    "apply_url": f"https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}",
                    "external_id": str(job_id),
                    "ats": "greenhouse",
                    "posted_at": posted_at,
                })
    except httpx.ConnectError as e:
        return jobs, f"connect_error: {e}"
    except httpx.TimeoutException:
        return jobs, "timeout"
    except Exception as e:
        return jobs, f"parse_error: {type(e).__name__}"
    return jobs, None


class GreenhouseScout(ScoutSource):
    name = "greenhouse"
    priority = "high"
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        # Parallel board fetch — 8 workers keeps API pressure modest but
        # cuts ~74 × 0.5s serialization to a few seconds.
        jobs: list[JobPost] = []
        boards = list(tenant.greenhouse_boards)
        self.last_attempts = len(boards)
        self.last_failures = 0
        self.last_error = None
        if not boards:
            return jobs
        with ThreadPoolExecutor(max_workers=8) as pool:
            for fut in as_completed(pool.submit(_fetch_greenhouse_board, s, tenant) for s in boards):
                try:
                    board_jobs, err = fut.result()
                    jobs.extend(board_jobs)
                    if err is not None:
                        self.last_failures += 1
                        # Keep the first error as representative; most network
                        # outages affect every board identically.
                        if self.last_error is None:
                            self.last_error = err
                except Exception as e:
                    self.last_failures += 1
                    if self.last_error is None:
                        self.last_error = f"worker_exception: {type(e).__name__}"
                    self.logger.debug(f"greenhouse board fetch failed: {e}")
        return jobs
