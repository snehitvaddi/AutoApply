"""Himalayas.app remote job API."""
import logging
import httpx

logger = logging.getLogger(__name__)

HIMALAYAS_API = "https://himalayas.app/jobs/api"


def scan_himalayas(queries: list[str], limit: int = 150) -> list[dict]:
    """Search Himalayas remote job API for each query."""
    all_jobs = []
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for query in queries:
            try:
                resp = client.get(HIMALAYAS_API, params={"q": query, "limit": limit})
                if resp.status_code != 200:
                    logger.warning(f"Himalayas [{query}]: HTTP {resp.status_code}")
                    continue
                jobs = resp.json().get("jobs", [])
                for job in jobs:
                    all_jobs.append({
                        "title": job.get("title", ""),
                        "company": job.get("companyName", job.get("company", "")),
                        "location": job.get("location", "Remote"),
                        "apply_url": job.get("applicationUrl", job.get("url", "")),
                        "external_id": str(job.get("id", "")),
                        "ats": "himalayas",
                    })
                logger.info(f"Himalayas [{query}]: {len(jobs)} jobs")
            except Exception as e:
                logger.warning(f"Himalayas [{query}] failed: {e}")

    logger.info(f"Himalayas total: {len(all_jobs)} jobs")
    return all_jobs
