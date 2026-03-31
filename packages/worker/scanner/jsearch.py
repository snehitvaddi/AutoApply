"""Google Jobs via JSearch RapidAPI (optional — requires RAPIDAPI_KEY).

Daily quota: max 6 queries per day (free tier = 500/month ≈ 16/day, but conservative).
Usage tracked in /tmp/jsearch-daily-usage.json.
"""
import os
import json
import logging
import httpx
from datetime import date

logger = logging.getLogger(__name__)

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"
JSEARCH_DAILY_MAX = 6
JSEARCH_USAGE_FILE = "/tmp/jsearch-daily-usage.json"


def _get_daily_usage() -> int:
    """Read today's query count from usage file."""
    try:
        with open(JSEARCH_USAGE_FILE) as f:
            data = json.load(f)
        if data.get("date") == date.today().isoformat():
            return data.get("count", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return 0


def _increment_usage():
    """Increment today's query count."""
    count = _get_daily_usage() + 1
    with open(JSEARCH_USAGE_FILE, "w") as f:
        json.dump({"date": date.today().isoformat(), "count": count}, f)


def scan_jsearch(queries: list[str], location: str = "United States") -> list[dict]:
    """Search Google Jobs via JSearch API. Skips if no RAPIDAPI_KEY or daily quota exceeded."""
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        logger.debug("JSearch skipped — no RAPIDAPI_KEY set")
        return []

    current_usage = _get_daily_usage()
    if current_usage >= JSEARCH_DAILY_MAX:
        logger.info(f"JSearch skipped — daily quota reached ({current_usage}/{JSEARCH_DAILY_MAX})")
        return []

    remaining = JSEARCH_DAILY_MAX - current_usage
    queries = queries[:remaining]  # only run as many queries as quota allows

    all_jobs = []
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}

    with httpx.Client(timeout=15) as client:
        for query in queries:
            _increment_usage()
            try:
                resp = client.get(JSEARCH_URL, params={
                    "query": f"{query} in {location}",
                    "num_pages": 1,
                    "date_posted": "today",
                }, headers=headers)
                if resp.status_code != 200:
                    continue
                for job in resp.json().get("data", []):
                    all_jobs.append({
                        "title": job.get("job_title", ""),
                        "company": job.get("employer_name", ""),
                        "location": job.get("job_city", "") + ", " + job.get("job_state", ""),
                        "apply_url": job.get("job_apply_link", ""),
                        "external_id": job.get("job_id", ""),
                        "ats": "jsearch",
                    })
                logger.info(f"JSearch [{query}]: {len(resp.json().get('data', []))} jobs")
            except Exception as e:
                logger.warning(f"JSearch [{query}] failed: {e}")

    logger.info(f"JSearch total: {len(all_jobs)} jobs")
    return all_jobs
