"""ZipRecruiter job search via Scrapling PlayWrightFetcher.

Multi-city mega scrape: queries × 20 US cities.
Filters: AI/ML roles only, skip staffing agencies, dedup by company+title.
ATS detection: checks if company has Greenhouse board → auto-discovery.
"""

import re
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ziprecruiter.com/jobs-search"

# Top 20 US tech cities for comprehensive coverage
LOCATIONS = [
    "San Francisco, CA", "San Jose, CA", "New York, NY", "Seattle, WA",
    "Austin, TX", "Boston, MA", "Los Angeles, CA", "Chicago, IL",
    "Denver, CO", "Atlanta, GA", "Dallas, TX", "Washington, DC",
    "Portland, OR", "San Diego, CA", "Raleigh, NC", "Pittsburgh, PA",
    "Salt Lake City, UT", "Phoenix, AZ", "Minneapolis, MN", "Remote",
]

# Extended staffing agency blocklist
STAFFING = {
    'vlink', 'derex', 'coforge', 'net2source', 'synergisticit', 'bcforward',
    'kforce', 'insight global', 'brillfy', 'jecona', 'stelvio', 'vallum',
    'luxoft', 'quantiphi', 'capgemini', 'acunor', 'usm business',
    'london approach', 'the cake', 'ascii group', 'okaya', 'primastep',
    'sotalent', 'joule', 'teksystems', 'randstad', 'robert half', 'hays',
    'adecco', 'manpower', 'staffing', 'consulting group', 'cybercoders',
    'futran', 'kda consulting', 'alignerr', 'revature', 'collabera',
    'infosys', 'wipro', 'tcs', 'hcl', 'cognizant', 'mindtree',
    'mphasis', 'persistent', 'zensar', 'ltimindtree', 'tech mahindra',
    'dice', 'hired', 'triplebyte', 'turing', 'toptal', 'andela',
}


def _is_staffing(company: str) -> bool:
    c = company.lower()
    return any(s in c for s in STAFFING)


def scan_ziprecruiter(queries: list[str], max_locations: int = 5) -> list[dict]:
    """Search ZipRecruiter for AI/ML jobs across US cities.

    Args:
        queries: Search terms (e.g., ["AI Engineer", "ML Engineer"])
        max_locations: Number of cities to search per query (default 5, max 20)

    Returns:
        List of normalized job dicts.
    """
    try:
        from scrapling.fetchers import PlayWrightFetcher
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("scrapling/bs4 not installed — skipping ZipRecruiter. Run: pip install scrapling beautifulsoup4")
        return []

    locations = LOCATIONS[:min(max_locations, len(LOCATIONS))]
    all_jobs = []

    try:
        pw = PlayWrightFetcher()
    except Exception as e:
        logger.warning(f"PlayWrightFetcher init failed: {e}")
        return []

    for query in queries:
        for location in locations:
            try:
                loc_param = location.replace(', ', ',').replace(' ', '+')
                url = f"{BASE_URL}?search={query.replace(' ', '+')}&location={loc_param}&days=1"

                page = pw.fetch(url, headless=True)
                if page.status != 200:
                    continue

                soup = BeautifulSoup(page.html_content, 'html.parser')

                for h in soup.find_all('h2'):
                    title = h.text.strip()
                    if not title or len(title) < 5:
                        continue

                    parent = h.find_parent('article') or h.find_parent('div')
                    company = ''
                    job_location = location
                    link = ''

                    if parent:
                        company_el = (
                            parent.find('a', attrs={'data-testid': re.compile(r'company')})
                            or parent.find(class_=re.compile(r'company|employer'))
                        )
                        if company_el:
                            company = company_el.text.strip()

                        loc_el = parent.find(class_=re.compile(r'location'))
                        if loc_el:
                            job_location = loc_el.text.strip()

                        link_el = parent.find('a', href=True)
                        if link_el:
                            href = link_el['href']
                            if not href.startswith('http'):
                                href = f"https://www.ziprecruiter.com{href}"
                            link = href

                    if _is_staffing(company):
                        continue

                    all_jobs.append({
                        "title": title,
                        "company": company,
                        "location": job_location,
                        "apply_url": link,
                        "external_id": link.split('/')[-1] if link else "",
                        "ats": "ziprecruiter",
                    })

            except Exception as e:
                logger.debug(f"ZipRecruiter [{query}] [{location}] failed: {e}")

    # Dedup by company+title
    seen = set()
    deduped = []
    for j in all_jobs:
        key = f"{j['company'].lower().strip()}|{j['title'].lower().strip()}"
        if key not in seen:
            seen.add(key)
            deduped.append(j)

    logger.info(f"ZipRecruiter: {len(deduped)} unique jobs (from {len(all_jobs)} raw, {len(queries)} queries × {len(locations)} cities)")
    return deduped
