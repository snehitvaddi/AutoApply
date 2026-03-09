import logging
import time
import httpx

logger = logging.getLogger(__name__)

BOARDS_API = "https://boards-api.greenhouse.io/v1/boards"
RATE_LIMIT_DELAY = 1.0  # seconds between requests


def scan_greenhouse_boards(board_tokens: list[str]) -> list[dict]:
    """Fetch jobs from Greenhouse boards API for each company token.

    Args:
        board_tokens: List of Greenhouse board tokens (e.g. ['stripe', 'airbnb']).

    Returns:
        List of normalized job dicts.
    """
    all_jobs = []

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for token in board_tokens:
            try:
                jobs = _fetch_board_jobs(client, token)
                all_jobs.extend(jobs)
                logger.info(f"Greenhouse [{token}]: {len(jobs)} jobs")
            except Exception as e:
                logger.warning(f"Greenhouse [{token}] failed: {e}")
            time.sleep(RATE_LIMIT_DELAY)

    logger.info(f"Greenhouse total: {len(all_jobs)} jobs from {len(board_tokens)} boards")
    return all_jobs


def _fetch_board_jobs(client: httpx.Client, token: str) -> list[dict]:
    """Fetch all jobs from a single Greenhouse board, handling pagination."""
    url = f"{BOARDS_API}/{token}/jobs"
    params = {"content": "true"}
    jobs = []

    resp = client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    for job in data.get("jobs", []):
        location = ""
        if job.get("location"):
            location = job["location"].get("name", "")

        jobs.append({
            "external_id": str(job["id"]),
            "title": job.get("title", ""),
            "company": token,
            "location": location,
            "apply_url": f"https://boards.greenhouse.io/embed/job_app?for={token}&token={job['id']}",
            "posted_at": job.get("updated_at", ""),
            "ats": "greenhouse",
            "metadata": {
                "departments": [d.get("name", "") for d in job.get("departments", [])],
                "offices": [o.get("name", "") for o in job.get("offices", [])],
            },
        })

    return jobs
