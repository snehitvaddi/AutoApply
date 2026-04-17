import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

logger = logging.getLogger(__name__)

LEVER_API = "https://api.lever.co/v0/postings"


def scan_lever_boards(companies: list[str]) -> list[dict]:
    """Fetch jobs from Lever postings API for each company (parallel)."""
    all_jobs: list[dict] = []

    def _one(company: str) -> list[dict]:
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                return _fetch_lever_jobs(client, company)
        except Exception as e:
            logger.warning(f"Lever [{company}] failed: {e}")
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_one, c): c for c in companies}
        for fut in as_completed(futs):
            jobs = fut.result()
            all_jobs.extend(jobs)
            logger.info(f"Lever [{futs[fut]}]: {len(jobs)} jobs")

    logger.info(f"Lever total: {len(all_jobs)} jobs from {len(companies)} companies")
    return all_jobs


def _fetch_lever_jobs(client: httpx.Client, company: str) -> list[dict]:
    """Fetch all postings from a single Lever company board."""
    url = f"{LEVER_API}/{company}"
    params = {"mode": "json"}
    jobs = []

    resp = client.get(url, params=params)
    resp.raise_for_status()
    postings = resp.json()

    if not isinstance(postings, list):
        return []

    for posting in postings:
        location = ""
        categories = posting.get("categories", {})
        if categories.get("location"):
            location = categories["location"]

        jobs.append({
            "external_id": posting.get("id", ""),
            "title": posting.get("text", ""),
            "company": company,
            "location": location,
            "apply_url": posting.get("applyUrl") or posting.get("hostedUrl", ""),
            "posted_at": _ms_to_iso(posting.get("createdAt", 0)),
            "ats": "lever",
            "metadata": {
                "team": categories.get("team", ""),
                "department": categories.get("department", ""),
                "commitment": categories.get("commitment", ""),
            },
        })

    return jobs


def _ms_to_iso(ms_timestamp: int) -> str:
    """Convert millisecond timestamp to ISO format string."""
    if not ms_timestamp:
        return ""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(ms_timestamp / 1000, tz=timezone.utc)
    return dt.isoformat()
