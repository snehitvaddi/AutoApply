# LinkedIn Voyager API — Job Discovery Guide

## Endpoints

### Job Search
```
GET https://www.linkedin.com/voyager/api/voyagerJobsDashJobCards
```
Query params:
- `decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-227`
- `count=25`
- `q=jobSearch`
- `start={offset}` (0, 25, 50, 75, 100)
- `query=(origin:JOB_SEARCH_PAGE_SEARCH_BUTTON, keywords:{query}, locationUnion:(geoId:103644278), selectedFilters:(sortBy:List(DD), timePostedRange:List({tpr})))`

**geoId:** `103644278` = United States
**Time posted ranges:** `r10800` (3h), `r21600` (6h), `r43200` (12h), `r86400` (24h)

### Job Detail
```
GET https://www.linkedin.com/voyager/api/jobs/jobPostings/{JOB_ID}
```
Returns: `applies` (applicant count), `views`, `applyMethod` (ATS URL + type), `description`

Note: Applicant count returns `None`/`0` for fresh/low-activity accounts.

## Required Headers
```python
{
    'csrf-token': CSRF,
    'cookie': f'li_at={LI_AT}; JSESSIONID="{CSRF}"',
    'accept': 'application/vnd.linkedin.normalized+json+2.1',
    'x-restli-protocol-version': '2.0.0',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}
```

## Token Extraction
```bash
openclaw browser cookies | python3 -c "
import json, sys
cookies = json.load(sys.stdin)
csrf = next(c['value'] for c in cookies if c['name'] == 'JSESSIONID')
li_at = next(c['value'] for c in cookies if c['name'] == 'li_at')
open('/tmp/li-csrf.txt','w').write(csrf)
open('/tmp/li-at.txt','w').write(li_at)
"
```

## Rate Limiting
- 0.8s between API calls
- 2s pause every 10 requests
- 60s sleep on HTTP 429, then retry once
- Break early if page returns 0 results or all duplicates
- 30 queries x 5 pages x 4 TPR ranges = max ~600 calls per mega scrape

## Response Parsing

**Key `$type` values:**
- `com.linkedin.voyager.dash.jobs.JobPosting` — title, entityUrn (job ID), repostedJob, workRemoteAllowed
- `com.linkedin.voyager.dash.organization.Company` — company name
- `com.linkedin.voyager.dash.jobs.JobPostingCard` — primaryDescription (company), secondaryDescription (location), tertiaryDescription (salary), footerItems (posted timestamp)

**ATS Detection from applyMethod:**
- `$type` containing `EasyApply`/`InAppApply` = LinkedIn Easy Apply
- `$type` containing `OffsiteApply` = external ATS with `companyApplyUrl`
- Check URL for: greenhouse, lever.co, ashby, workday, smartrecruiters

## Three-Stage Pipeline

### Stage 1: Mega Scrape (`li-mega-scrape.py`)
- 30 search queries x 5 pages x 4 time ranges
- Output: `li-mega-raw.json` (~1200-1600+ jobs)
- Deduplicates by job ID

### Stage 2: Refilter (`li-refilter.py`)
- AI/ML keyword matching (25+ keywords)
- Title exclusions (Staff, Principal, Director, VP, Intern, etc.)
- FAANG senior exclusion
- Staffing/defense company exclusions (80+ companies)
- Non-US location filtering (40+ patterns)
- Generic SWE filter (unless has AI modifier)
- 24h max age, dedup by company+title
- Output: `li-filtered.json`

### Stage 3: Applicant Enrichment (`li-fetch-applicants.py`)
- Fetches job detail for each filtered job
- Extracts applicant count, views, ATS type, apply URL
- Filters: <100 applicants (or unknown)
- Sorts by applicant count ascending
- Output: `linkedin-final-with-applicants.json`

## LinkedIn Account Management

**Key learnings:**
- LinkedIn blocks new accounts fast (hours of automated activity)
- Escalation: Login → Phone verification → Government ID verification (hard block)
- Voyager API is primary — browser scraping only gets ~7 cards (virtual scrolling DOM)
- `press End`, `ArrowDown`, JS `scrollTop` all FAIL to trigger LinkedIn's intersection observer
- Session cookies valid ~360 days
- LinkedIn may have blacklisted `agentmail.to` domain for verification emails

**For SaaS multi-user:** Each user needs their own LinkedIn session or the system scouts via public ATS APIs (Greenhouse, Ashby, Lever) which don't require LinkedIn.
