"""LinkedIn public job search via scrapling (no auth required)."""
import logging
from scrapling.fetchers import Fetcher

logger = logging.getLogger(__name__)


def scan_linkedin(queries: list[str], location: str = "United States") -> list[dict]:
    """Search LinkedIn public job listings for each query term."""
    all_jobs = []
    for query in queries:
        try:
            url = f"https://www.linkedin.com/jobs/search?keywords={query.replace(' ', '+')}&location={location.replace(' ', '+')}&f_TPR=r86400"
            page = Fetcher.get(url, timeout=15)
            titles = page.css('.base-search-card__title')
            companies = page.css('.base-search-card__subtitle a')
            locations = page.css('.job-search-card__location')
            links = page.css('.base-card__full-link')

            for i in range(min(len(titles), len(companies), len(links))):
                href = links[i].attrib.get('href', '') if hasattr(links[i], 'attrib') else str(links[i].attributes.get('href', ''))
                all_jobs.append({
                    "title": titles[i].text.strip() if titles[i].text else "",
                    "company": companies[i].text.strip() if companies[i].text else "",
                    "location": locations[i].text.strip() if i < len(locations) and locations[i].text else "",
                    "apply_url": href.split('?')[0] if href else "",
                    "external_id": href.split('?')[0].rstrip('/').split('-')[-1] if href else "",
                    "ats": "linkedin",
                })
            logger.info(f"LinkedIn [{query}]: {len(titles)} jobs")
        except Exception as e:
            logger.warning(f"LinkedIn [{query}] failed: {e}")

    logger.info(f"LinkedIn total: {len(all_jobs)} jobs")
    return all_jobs
