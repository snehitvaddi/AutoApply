import logging
import time
import httpx

logger = logging.getLogger(__name__)

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"
RATE_LIMIT_DELAY = 1.0


def scan_ashby_boards(board_slugs: list[str]) -> list[dict]:
    """Fetch jobs from Ashby job board API for each board slug.

    Args:
        board_slugs: List of Ashby board slugs (e.g. ['notion', 'ramp']).

    Returns:
        List of normalized job dicts.
    """
    all_jobs = []

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for slug in board_slugs:
            try:
                jobs = _fetch_ashby_jobs(client, slug)
                all_jobs.extend(jobs)
                logger.info(f"Ashby [{slug}]: {len(jobs)} jobs")
            except Exception as e:
                logger.warning(f"Ashby [{slug}] failed: {e}")
            time.sleep(RATE_LIMIT_DELAY)

    logger.info(f"Ashby total: {len(all_jobs)} jobs from {len(board_slugs)} boards")
    return all_jobs


def _fetch_ashby_jobs(client: httpx.Client, slug: str) -> list[dict]:
    """Fetch all jobs from a single Ashby job board."""
    url = f"{ASHBY_API}/{slug}"
    jobs = []

    resp = client.get(url)
    resp.raise_for_status()
    data = resp.json()

    for job in data.get("jobs", []):
        location = job.get("location", "")
        if isinstance(location, dict):
            location = location.get("name", "")

        apply_url = f"https://jobs.ashbyhq.com/{slug}/application?jobId={job['id']}"
        if job.get("applicationUrl"):
            apply_url = job["applicationUrl"]

        jobs.append({
            "external_id": job.get("id", ""),
            "title": job.get("title", ""),
            "company": slug,
            "location": location,
            "apply_url": apply_url,
            "posted_at": job.get("publishedAt", ""),
            "ats": "ashby",
            "metadata": {
                "department": job.get("department", ""),
                "team": job.get("team", ""),
                "employment_type": job.get("employmentType", ""),
            },
        })

    return jobs
