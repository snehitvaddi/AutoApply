"""Indeed job search via python-jobspy."""
import logging

logger = logging.getLogger(__name__)


def scan_indeed(queries: list[str], location: str = "United States", results_per_query: int = 50) -> list[dict]:
    """Search Indeed for jobs matching each query."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        logger.warning("python-jobspy not installed — skipping Indeed. Run: pip install python-jobspy")
        return []

    all_jobs = []
    for query in queries:
        try:
            df = scrape_jobs(site_name=["indeed"], search_term=query, location=location, results_wanted=results_per_query, hours_old=24)
            for _, row in df.iterrows():
                all_jobs.append({
                    "title": str(row.get("title", "")),
                    "company": str(row.get("company_name", row.get("company", ""))),
                    "location": str(row.get("location", "")),
                    "apply_url": str(row.get("job_url", "")),
                    "external_id": str(row.get("id", row.get("job_url", ""))),
                    "ats": "indeed",
                })
            logger.info(f"Indeed [{query}]: {len(df)} jobs")
        except Exception as e:
            logger.warning(f"Indeed [{query}] failed: {e}")

    logger.info(f"Indeed total: {len(all_jobs)} jobs")
    return all_jobs
