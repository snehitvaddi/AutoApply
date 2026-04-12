"""Admin research tool — authenticated LinkedIn voyager scrape.

NOT called from the worker pipeline. This is a manual R&D script admin runs
when experimenting with LinkedIn-auth scraping. The official per-tenant
LinkedIn scout is packages/worker/scout/linkedin_public.py which uses the
unauthenticated public endpoint.

Queries and US geo are read from env vars or argv so this script doesn't
bake in any role assumptions. If you invoke it without LI_QUERIES, it
errors out rather than silently running against an admin-default list.

Usage:
  LI_QUERIES="Backend Engineer,Platform Engineer" python li-mega-scrape.py
  # or
  python li-mega-scrape.py "Backend Engineer" "Platform Engineer"
"""
import os
import sys
import json
import time
import urllib.parse
from datetime import datetime, timezone

import requests

with open('/tmp/li-csrf.txt') as f:
    CSRF = f.read().strip()
with open('/tmp/li-at.txt') as f:
    LI_AT = f.read().strip()

HEADERS = {
    'csrf-token': CSRF,
    'cookie': f'li_at={LI_AT}; JSESSIONID="{CSRF}"',
    'accept': 'application/vnd.linkedin.normalized+json+2.1',
    'x-restli-protocol-version': '2.0.0',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

# Queries from argv or env var — no hardcoded role list. Admin must supply
# what to search for. Prevents this research script from leaking into any
# client-facing path with hardcoded AI/ML opinions.
_argv_queries = [q for q in sys.argv[1:] if q and not q.startswith('-')]
_env_queries = [q.strip() for q in os.environ.get('LI_QUERIES', '').split(',') if q.strip()]
QUERIES = _argv_queries or _env_queries
if not QUERIES:
    print(
        "ERROR: no queries provided. Set LI_QUERIES='role,role' or pass as argv.\n"
        "Example: LI_QUERIES='Backend Engineer,Platform Engineer' python li-mega-scrape.py",
        file=sys.stderr,
    )
    sys.exit(2)

PAGES = 5
GEO_US = '103644278'
all_jobs = {}
total_calls = 0
now_ms = int(time.time() * 1000)

print(f"MEGA SCRAPE: {len(QUERIES)} queries x {PAGES} pages")
print(f"{'='*90}\n")

for qi, query in enumerate(QUERIES):
    query_new = 0
    for page in range(PAGES):
        start = page * 25
        encoded = urllib.parse.quote(query)
        url = (
            f'https://www.linkedin.com/voyager/api/voyagerJobsDashJobCards'
            f'?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-227'
            f'&count=25&q=jobSearch'
            f'&query=(origin:JOB_SEARCH_PAGE_SEARCH_BUTTON,'
            f'keywords:{encoded},'
            f'locationUnion:(geoId:{GEO_US}),'
            f'selectedFilters:(sortBy:List(DD),timePostedRange:List(r86400)))'
            f'&start={start}'
        )
        
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            total_calls += 1
            
            if r.status_code == 429:
                print(f'  RATE LIMITED — sleeping 60s...')
                time.sleep(60)
                r = requests.get(url, headers=HEADERS, timeout=15)
                total_calls += 1
            
            if r.status_code != 200:
                break
            
            data = r.json()
            elements = data.get('included', [])
            
            # Build lookup maps
            postings = {}
            companies = {}
            
            for el in elements:
                etype = el.get('$type', '')
                urn = el.get('entityUrn', '')
                
                if etype == 'com.linkedin.voyager.dash.jobs.JobPosting':
                    jid = urn.split(':')[-1]
                    postings[urn] = {
                        'id': jid,
                        'title': el.get('title', ''),
                        'reposted': el.get('repostedJob', False),
                        'remote': el.get('workRemoteAllowed', False),
                    }
                
                if etype == 'com.linkedin.voyager.dash.organization.Company':
                    companies[urn] = el.get('name', '')
            
            # Extract rich data from card elements
            for el in elements:
                if el.get('$type') != 'com.linkedin.voyager.dash.jobs.JobPostingCard':
                    continue
                
                job_urn = el.get('jobPostingUrn', '') or el.get('*jobPosting', '')
                if not job_urn or job_urn not in postings:
                    continue
                
                job = postings[job_urn]
                
                # Company
                pd = el.get('primaryDescription', {})
                if pd:
                    job['company'] = pd.get('text', '')
                
                # Location
                sd = el.get('secondaryDescription', {})
                if sd:
                    job['location'] = sd.get('text', '')
                
                # Salary/benefits
                td = el.get('tertiaryDescription', {})
                if td:
                    job['salary'] = td.get('text', '')
                
                # Posted timestamp
                footer = el.get('footerItems', [])
                for fi in footer:
                    if fi.get('type') == 'LISTED_DATE' and fi.get('timeAt'):
                        job['posted_at'] = fi['timeAt']
                        age_h = (now_ms - fi['timeAt']) / 3600000
                        job['age_hours'] = round(age_h, 1)
                
                # Title from card (sometimes cleaner)
                job['title'] = el.get('jobPostingTitle', '') or job['title']
            
            if len(postings) == 0:
                break
            
            added = 0
            for urn, job in postings.items():
                jid = job['id']
                if jid and jid not in all_jobs:
                    job['query'] = query
                    all_jobs[jid] = job
                    added += 1
                    query_new += 1
            
            if added == 0 and page > 0:
                break  # All dupes, skip rest
                
        except Exception as e:
            print(f'  [{query}] ERROR: {e}')
            break
        
        time.sleep(0.8)
    
    print(f'  [{qi+1:2d}/{len(QUERIES)}] {query:35s} → +{query_new:3d} new | Total: {len(all_jobs)}')
    
    if (qi + 1) % 10 == 0:
        time.sleep(2)

# Save
jobs_list = list(all_jobs.values())
with open('/tmp/li-mega-raw.json', 'w') as f:
    json.dump(jobs_list, f, indent=2)

print(f'\n{"="*90}')
print(f'DONE — {len(jobs_list)} unique jobs | {total_calls} API calls | {len(QUERIES)} queries')
