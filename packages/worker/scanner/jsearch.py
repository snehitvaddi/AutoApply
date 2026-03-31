"""Google Jobs via JSearch RapidAPI (optional — requires RAPIDAPI_KEY)."""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"


def scan_jsearch(queries: list[str], location: str = "United States") -> list[dict]:
    """Search Google Jobs via JSearch API. Skips if no RAPIDAPI_KEY."""
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        logger.debug("JSearch skipped — no RAPIDAPI_KEY set")
        return []

    all_jobs = []
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}

    with httpx.Client(timeout=15) as client:
        for query in queries:
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
