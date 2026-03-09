import requests, json, time

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

with open('/tmp/li-need-applicants.json') as f:
    jobs = json.load(f)

# Skip Google
jobs = [j for j in jobs if j.get('company', '').lower() not in ['google', 'google llc']]
print(f'Fetching applicant counts for {len(jobs)} jobs (Google excluded)...\n')

for i, j in enumerate(jobs):
    jid = j['id']
    url = f'https://www.linkedin.com/voyager/api/jobs/jobPostings/{jid}'
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            
            # Look for applicant count
            applies = data.get('applies', None)
            views = data.get('views', None)
            desc = data.get('description', {})
            description_text = desc.get('text', '')[:200] if isinstance(desc, dict) else ''
            
            # Also check for apply URL to determine ATS
            apply_url = data.get('applyMethod', {})
            if isinstance(apply_url, dict):
                ext = apply_url.get('companyApplyUrl', '') or apply_url.get('easyApplyUrl', '')
                j['apply_url'] = ext
                if 'greenhouse' in ext.lower():
                    j['ats'] = 'greenhouse'
                elif 'lever' in ext.lower():
                    j['ats'] = 'lever'
                elif 'ashby' in ext.lower():
                    j['ats'] = 'ashby'
                elif 'workday' in ext.lower():
                    j['ats'] = 'workday'
                elif 'smartrecruiters' in ext.lower():
                    j['ats'] = 'smartrecruiters'
                elif ext:
                    j['ats'] = 'external'
                else:
                    j['ats'] = 'easy_apply'
            
            j['applicants'] = applies
            j['views'] = views
            j['description_preview'] = description_text
            
            status = f"applicants={applies}, views={views}, ats={j.get('ats','?')}"
        elif r.status_code == 429:
            print(f'  RATE LIMITED at job {i+1} — sleeping 60s')
            time.sleep(60)
            j['applicants'] = None
            status = 'rate limited'
        else:
            j['applicants'] = None
            status = f'HTTP {r.status_code}'
    except Exception as e:
        j['applicants'] = None
        status = f'error: {e}'
    
    if (i+1) % 10 == 0:
        print(f'  [{i+1}/{len(jobs)}] {status}')
    
    time.sleep(0.5)

# Filter: <100 applicants (or unknown)
under100 = [j for j in jobs if j.get('applicants') is None or j.get('applicants', 0) < 100]

print(f'\n{"="*120}')
print(f'Total checked: {len(jobs)}')
print(f'Under 100 applicants (or unknown): {len(under100)}')
print(f'Over 100 applicants: {len(jobs) - len(under100)}')

# Sort by applicants (lowest first), unknowns at end
under100.sort(key=lambda x: (x.get('applicants') is None, x.get('applicants') or 0))

print(f'\n{"#":>3} | {"Apps":>5} | {"Age":>5} | {"ATS":12s} | {"Company":25s} | {"Title":45s} | {"Location":25s} | {"Salary":18s}')
print('-' * 155)
for i, j in enumerate(under100):
    apps = str(j.get('applicants', '?'))
    age = f"{j.get('age_hours','?')}h" if j.get('age_hours') else '?'
    sal = j.get('salary', '')[:18]
    ats = j.get('ats', '?')
    rp = '*' if j.get('reposted') else ' '
    print(f'{i+1:3d} |{apps:>5s} | {age:>5s}{rp}| {ats:12s} | {j.get("company",""):25s} | {j["title"]:45s} | {j.get("location",""):25s} | {sal}')

with open('/tmp/linkedin-final-with-applicants.json', 'w') as f:
    json.dump(under100, f, indent=2)
