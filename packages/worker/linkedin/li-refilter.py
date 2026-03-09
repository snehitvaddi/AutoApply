import json

with open('/tmp/li-mega-raw.json') as f:
    jobs = json.load(f)
with open('/tmp/applied-dedup.json') as f:
    dedup_tokens = set(json.load(f).get('tokens', []))

AI_KW = ['ai ', 'ai/', 'ai-', 'ml ', 'ml/', 'ml-', 'machine learning', 'data scientist',
         'data engineer', 'data science', 'genai', 'generative ai', 'llm', 'nlp',
         'deep learning', 'computer vision', 'applied scientist', 'research scientist',
         'research engineer', 'mlops', 'ai infrastructure', 'ml platform',
         'artificial intelligence', 'agentic', 'neural', 'reinforcement learning',
         'ai/ml', 'analytics engineer', 'ai developer', 'ai researcher']

SKIP_TITLES = ['lead ', 'principal', 'staff ', 'director', 'manager', 'vp ',
               'intern', 'co-op', 'head of', 'chief', 'executive', 'president',
               'professor', 'teacher', 'instructor', 'fellow']

FAANG = ['google', 'meta', 'apple', 'amazon', 'microsoft', 'netflix']

STAFFING = [
    'tata', 'infosys', 'wipro', 'cognizant', 'hcl', 'capgemini',
    'accenture', 'deloitte', 'ernst', 'kpmg', 'pwc', 'mckinsey',
    'manpower', 'randstad', 'adecco', 'robert half', 'insight global',
    'tek systems', 'compunnel', 'collabera', 'yochana', 'synergis',
    'cybercoder', 'talentify', 'jobot', 'dice', 'motion recruitment',
    'harnham', 'braintrust', 'toptal', 'turing', 'andela', 'crossover',
    'general dynamics', 'raytheon', 'lockheed', 'northrop', 'bae systems',
    'leidos', 'booz allen', 'saic', 'l3harris',
    'ntt data', 'cgi ', 'dxc ', 'atos', 'mphasis', 'tech mahindra',
    'persistent systems', 'zensar', 'ltimindtree', 'hexaware',
    'soho square', 'raas infotek', 'sibitalent', 'infovision',
    'coretek', 'galent', 'acceler8', 'people in ai', 'ssi people',
    'element technologies', 'clevanoo', 'vysystems', 'sprezzatura',
    'millennium software', 'sri tech', 'sharp decisions', 'voto consulting',
    'new york technology', 'kforce', 'x-wave', 'remotehunter', 'alta it',
    'us tech solutions', 'quik hire', 'envision technology', 'wiraa',
    'staffing', 'efinancialcareers', 'judge group', 'apex systems',
    'modis', 'experis', 'horizontal talent', 'synechron', 'virtusa',
    'globant', 'epam', 'pentangle', 'pgc digital', 'rivago', 'nlb services',
    'astir it', 'logisolve', 'persimmons', 'ciliandry', 'lorven',
    'gac solutions', 'highbrow', 'nam info', 'provisions group', 'akkodis',
    'kmm technologies', 'pacer group', 'brooksource', 'gravity it',
    'smart it frame', 'pdssoft', 'haar recruitment', 'mokshaa',
    'northbound executive', 'jobright', 'cisco',
]

NON_US = ['india', 'london', 'berlin', 'toronto', 'canada', 'europe', 'uk,',
          'singapore', 'japan', 'australia', 'brazil', 'germany', 'france',
          'netherlands', 'ireland', 'bangalore', 'hyderabad', 'pune', 'mumbai',
          'chennai', 'delhi', 'noida', 'gurgaon', 'mexico', 'costa rica']

BAD_TITLES = ['consultant', 'evangelist', 'talent pipeline', 'freelance',
              'w2 contract', 'contract only', 'part-time', 'bilingual',
              'medical expert', 'verification engineer', 'physicist',
              'clinical', '.net', 'java developer', 'trainer', 'tutor',
              'recruiter', 'coordinator', 'architect(only']

filtered = []
skip = {'applied': 0, 'not_ai': 0, 'level': 0, 'staffing': 0, 'faang_sr': 0,
        'non_us': 0, 'bad_role': 0, 'generic_swe': 0, 'over_24h': 0}

for j in jobs:
    t = j.get('title', '')
    tl = t.lower()
    cl = j.get('company', '').lower()
    ll = j.get('location', '').lower()
    jid = j.get('id', '')
    age = j.get('age_hours')
    
    # Keep reposts! But enforce 24h
    if age and age > 24: skip['over_24h'] += 1; continue
    
    if jid in dedup_tokens: skip['applied'] += 1; continue
    if not any(k in tl for k in AI_KW): skip['not_ai'] += 1; continue
    if any(s in tl for s in SKIP_TITLES): skip['level'] += 1; continue
    if any(s in cl for s in STAFFING): skip['staffing'] += 1; continue
    if any(x in ll for x in NON_US): skip['non_us'] += 1; continue
    if any(s in tl for s in BAD_TITLES): skip['bad_role'] += 1; continue
    if 'senior' in tl and any(f in cl for f in FAANG): skip['faang_sr'] += 1; continue
    
    swe = ['software engineer', 'backend engineer', 'fullstack', 'full stack',
           'frontend', 'devops', 'site reliability']
    if any(x in tl for x in swe):
        if not any(k in tl for k in ['machine learning', 'ml', 'ai', 'data', 'nlp', 'llm', 'genai']):
            skip['generic_swe'] += 1; continue
    
    filtered.append(j)

# Dedup by company+title
seen = set()
deduped = []
for j in filtered:
    key = f"{j.get('company','').lower().strip()}|{j.get('title','').lower().strip()}"
    if key not in seen:
        seen.add(key)
        deduped.append(j)

deduped.sort(key=lambda x: x.get('age_hours', 999))

print(f'Raw: {len(jobs)} → Title/company/level filter: {len(filtered)} → Deduped: {len(deduped)}')
print(f'Skips: {json.dumps(skip)}')
print(f'\nNeed applicant count for {len(deduped)} jobs. Saving IDs...')

with open('/tmp/li-need-applicants.json', 'w') as f:
    json.dump(deduped, f, indent=2)

# Print preview
for i, j in enumerate(deduped[:10]):
    age = f"{j.get('age_hours','?')}h" if j.get('age_hours') else '?'
    rp = '(repost)' if j.get('reposted') else ''
    print(f'  {i+1}. {j.get("company",""):25s} | {j["title"]:45s} | {age:>5s} {rp}')
print(f'  ... and {len(deduped)-10} more')
