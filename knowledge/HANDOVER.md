# HANDOVER — Job Application Bot: Complete Knowledge Transfer

## MESSAGE TO THE AGENT

Read this entire file carefully before writing any code. It contains:

1. **Battle-tested code** — Two working Greenhouse form fillers (Playwright-based and CLI-based). REUSE these. Don't rewrite from scratch.
2. **Field mappings** — Every form field label → answer, learned from 60+ real applications across 13 companies.
3. **Platform-specific quirks** — Greenhouse, Lever, Ashby, Workday, SmartRecruiters. Each has unique pitfalls that took dozens of failed attempts to solve.
4. **User profile** — All personal details, credentials, preferences, and canned answers.

**Your job:** Read through everything, extract what's useful, and if your architecture uses a programmatic approach, **reuse the existing code** (especially the field matching, dropdown handling, combobox patterns, and submit logic). Don't reinvent what already works.

---

## ARCHITECTURE OVERVIEW

The system has three layers:

```
SCRAPER (no AI)          →  AI FILTER (batched)      →  APPLICATOR (no AI)       →  AI SUPERVISOR
LinkedIn, Greenhouse API     Score & rank jobs            Fill forms, click submit     Handles unknowns
Lever API, Ashby API         Kill irrelevant ones         Pure code, no LLM per field  Writes new code when stuck
```

**Key principle:** AI is expensive and slow. Use it for decisions (is this job relevant?), NOT for form filling. Form filling is 100% deterministic — same fields, same answers, every time. Code handles it.

---

## USER PROFILE (copy-paste ready)

```yaml
personal:
  first_name: "{first_name}"
  last_name: "{last_name}"
  full_name: "{full_name}"
  preferred_name: "{first_name}"
  email: "{email}"
  phone: "{phone}"
  pronouns: "he/him"

address:
  street: "{street_address}"
  apt: "{apt}"
  city: "{city}"
  state: "Texas"
  zip: "{zip_code}"
  country: "United States"

links:
  linkedin: "{linkedin_url}"
  github: "{github_url}"
  website: "{github_url}"

work:
  current_company: "{current_company}"
  current_title: "AI Engineer"
  years_experience: 4

education:
  school: "University of Florida"
  degree: "Master's in Computer & Information Science"
  graduation_year: "2024"

legal:
  authorized_to_work_us: true
  requires_sponsorship: true
  visa_status: "F-1 OPT STEM Extension"

eeo:
  gender: "Male"
  race: "Asian"
  hispanic: "No"
  veteran: "I am not a protected veteran"
  disability: "No, I do not have a disability"

credentials:
  ats_email: "{email}"
  ats_password: "{REMOVED_PASSWORD}"
  telegram_bot_token: "{TELEGRAM_BOT_TOKEN}"
  telegram_chat_id: "{TELEGRAM_CHAT_ID}"

resumes:
  default: "{full_name} GenAI Resume.pdf"       # AI/ML/SWE roles
  data_science: "{full_name} DS Resume.pdf"      # Data Scientist/Data Engineer/Analytics roles

preferences:
  salary_range: "$120,000 - $170,000"
  salary_min: 110000
  location: "Remote or Hybrid, US"
  willing_to_relocate: true
  start_date: "2 weeks from offer acceptance"
  target_roles:
    - "AI Engineer"
    - "Machine Learning Engineer"
    - "GenAI Engineer"
    - "LLM Engineer"
    - "MLOps Engineer"
    - "Applied Scientist"
    - "Data Scientist"
    - "Data Engineer"
    - "Software Engineer AI/ML"
    - "Research Engineer AI"
    - "NLP Engineer"
    - "Computer Vision Engineer"
  exclude_roles:
    - "Frontend"
    - "Mobile"
    - "Backend Engineer (non-AI)"
    - "DevOps"
    - "QA/SDET"
    - "Security"
    - "Blockchain"
    - "Embedded/Firmware"
  exclude_companies:
    - "Anduril, Palantir, Lockheed, Raytheon, Northrop Grumman, L3Harris"  # Defense
    - "Wipro, Infosys, TCS, Cognizant, HCL, Robert Half, Randstad"        # Staffing
    - "{current_company}"                                                              # Current employer
    - "Wiraa, BestJobTool, Jobright.ai, Hirenza"                           # Shady sites
```

---

## FIELD MAP (field_map.json)

This maps form field labels to answers. Learned from 60+ applications. Use longest-match on label.lower().

```json
{
  "_description": "Maps form field labels (case-insensitive substring match) to profile values. Longest match wins.",

  "text_fields": {
    "first name": "{first_name}",
    "last name": "{last_name}",
    "preferred name": "{first_name}",
    "full name": "{full_name}",
    "name": "{full_name}",
    "email": "{email}",
    "confirm email": "{email}",
    "phone": "{phone}",
    "mobile": "{phone}",
    "linkedin": "{linkedin_url}",
    "github": "{github_url}",
    "website": "{github_url}",
    "portfolio": "{github_url}",
    "current company": "{current_company}",
    "employer": "{current_company}",
    "company name": "{current_company}",
    "current title": "AI Engineer",
    "job title": "AI Engineer",
    "current location": "Dallas, TX",
    "city": "{city}",
    "state": "Texas",
    "zip": "{zip_code}",
    "postal": "{zip_code}",
    "address": "{street_address}, {apt}, {city}, TX {zip_code}",
    "school": "University of Florida",
    "university": "University of Florida",
    "degree": "Master's in Computer & Information Science",
    "field of study": "Computer & Information Science",
    "graduation year": "2024",
    "graduation": "December 2024",
    "years experience": "4",
    "salary": "$120,000 - $170,000",
    "compensation": "$120,000 - $170,000",
    "earliest start": "2 weeks from offer acceptance",
    "start date": "2 weeks from offer acceptance",
    "notice period": "2 weeks",
    "pronoun": "he/him",
    "signature": "{full_name}",
    "how did you hear": "LinkedIn",
    "how did you learn": "LinkedIn"
  },

  "dropdown_fields": {
    "authorized": "Yes",
    "legally authorized": "Yes",
    "sponsorship": "Yes",
    "require visa": "Yes",
    "will you now or will you in the future": "Yes",
    "country": "United States",
    "phone country": "United States",
    "relocat": "Yes",
    "remote": "Yes",
    "reside": "Yes",
    "previously applied": "No",
    "previously employed": "No",
    "interviewed": "No",
    "non-compete": "No",
    "noncompete": "No",
    "privacy": "Yes",
    "certification": "Yes",
    "how did you hear": "LinkedIn",
    "source": "LinkedIn",
    "brighthire": "Yes",
    "whatsapp": "No"
  },

  "eeo_fields": {
    "gender": "Male",
    "race": "Asian",
    "ethnicity": "Asian",
    "hispanic": "No",
    "latino": "No",
    "veteran": "I am not a protected veteran",
    "disability": "No, I do not have a disability"
  },

  "essay_fields": {
    "why interested": "I am passionate about building AI-powered solutions that create real-world impact. With 4+ years of experience spanning AI engineering, data engineering, and software development, I bring hands-on expertise in production ML systems, multi-agent architectures, and large-scale data pipelines. At {current_company}, I shipped an ambient AI Scribe serving 5,000+ healthcare providers and built hallucination detection systems achieving 92% accuracy. I thrive in fast-paced environments where I can take ideas from prototype to production.",
    "what makes you": "I bring a rare combination of AI/ML depth and production engineering skills. I have built and shipped multi-agent RAG systems, fine-tuned LLMs with LoRA, designed real-time data pipelines processing 1M+ logs/day, and deployed computer vision models. I also have two published research papers (SPIE 2024, IEEE Explore 2023).",
    "cover letter": "I am writing to express my interest in this role. With 4+ years of experience in AI engineering, software development, and data engineering, along with a Master's in Computer & Information Science from the University of Florida, I bring a strong foundation in building production AI systems at scale. In my current role as an AI Engineer at {current_company}, I shipped a clinical ambient AI Scribe serving 5,000+ providers that automates 70% of documentation, built an AI Fax system cutting costs from $400K to $20K/month, and open-sourced MEDHALT — a hallucination detection suite achieving 92% accuracy.",
    "additional info": "I am currently on F-1 OPT STEM Extension and will require H-1B visa sponsorship. I have two published research papers (SPIE 2024, IEEE Explore 2023). Portfolio: {github_url}",
    "anything else": "I am currently on F-1 OPT STEM Extension and will require H-1B visa sponsorship. I have two published research papers (SPIE 2024, IEEE Explore 2023)."
  }
}
```

---

## PLATFORM KNOWLEDGE (hard-won, do NOT skip)

### Greenhouse (most common — 80% of applications)

**URLs:**
- Embed: `https://job-boards.greenhouse.io/embed/job_app?for={company}&token={job_id}`
- Board: `https://job-boards.greenhouse.io/{company}/jobs/{job_id}`
- API: `https://boards-api.greenhouse.io/v1/boards/{company}/jobs` (public, no auth)

**Critical quirks:**
1. **Comboboxes are ARIA widgets, NOT native `<select>`** — You MUST click to open, find option in listbox, click option. Typing alone doesn't select.
2. **Phone country dropdown** — There's a country code selector BEFORE the phone field. Must set to "United States" FIRST or phone won't save.
3. **Location autocomplete** — "{city}, TX" returns nothing. Type "Dallas" instead → select "Dallas, Texas, United States".
4. **Resume upload** — Use file input interceptor (`set_input_files` in Playwright, or `browser upload --ref` in CLI). NEVER click the attach button directly — opens native file dialog that hangs.
5. **reCAPTCHA Enterprise** — Invisible, usually passes silently. If it blocks, skip the job.
6. **Email verification** — Some companies (Stripe, Datadog) show 8 single-character input boxes after first submit. Read email from `no-reply@us.greenhouse-mail.io`, enter one char per box, submit again.
7. **Post-submit** — Either "Thank you for applying" page OR blank redirect. Screenshot immediately.

**Combobox fill pattern (Playwright):**
```python
def select_combobox_option(page, combobox, answer):
    combobox.scroll_into_view_if_needed()
    time.sleep(0.3)
    try:
        combobox.click(force=True, timeout=5000)
    except:
        combobox.evaluate("el => { el.focus(); el.click(); }")
    time.sleep(0.5)
    combobox.fill("")
    combobox.type(answer[:30], delay=30)
    time.sleep(0.5)
    listbox = page.query_selector('[role="listbox"]')
    if listbox:
        options = listbox.query_selector_all('[role="option"]')
        for opt in options:
            if answer.lower() in opt.inner_text().strip().lower():
                opt.click(force=True, timeout=3000)
                return True
    combobox.press("Enter")
    combobox.press("Escape")
    return True
```

**Phone country JS fallback:**
```python
page.evaluate("""() => {
    const selects = document.querySelectorAll('select');
    for (const s of selects) {
        const name = (s.name || s.id || '').toLowerCase();
        if (name.includes('country') || name.includes('phone')) {
            for (const o of s.options) {
                if (o.text.includes('United States') || o.text.includes('US (+1)')) {
                    s.value = o.value;
                    s.dispatchEvent(new Event('change', {bubbles: true}));
                    break;
                }
            }
        }
    }
}""")
```

**Submit button selectors (try in order):**
```python
submit_btn = (
    page.query_selector('button[type="submit"]')
    or page.query_selector('input[type="submit"]')
    or page.query_selector('button:has-text("Submit Application")')
    or page.query_selector('button:has-text("Submit")')
    or page.query_selector('button:has-text("Apply")')
    or page.query_selector('button:has-text("Send Application")')
)
if not submit_btn:
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)
    # try again...
```

### Lever (simplest ATS)

**URL:** `https://jobs.lever.co/{company}/{job_id}/apply`

**Key differences from Greenhouse:**
- **Full name is ONE field** — type "{full_name}" (not separate first/last)
- **No comboboxes** — all dropdowns are radio buttons
- **No EEO on apply page** — comes via email after
- **No location autocomplete** — plain text field
- **Single page** — everything visible, straight to "Submit application"

### Ashby

**URL:** `https://jobs.ashbyhq.com/{company}/{job_id}/application`

**Pitfalls:**
- Location can LOOK filled but fail validation — must press Enter to commit
- Resume upload targets wrong file input if generic `input[type='file']` — use `#_systemfield_resume`
- Anti-bot: submit button may do nothing (no error, no confirmation) — classify as blocked
- Upload lock warning: "We're updating your application" — wait then retry

### Workday (multi-step wizard)

**URL:** `https://{company}.wd{N}.myworkdayjobs.com/.../apply/applyManually`

**7-step wizard** (requires account creation first):
1. Create Account/Sign In (accounts are GLOBAL across all Workday companies)
2. My Information
3. My Experience
4. Application Questions
5. Voluntary Disclosures (EEO)
6. Self Identify (disability/veteran)
7. Review + Submit

**Account:** `{email}` / `{REMOVED_PASSWORD}`

**"How Did You Hear" is a TWO-LEVEL multi-select** — click "Job Board" → then click "LinkedIn Jobs" in sub-dropdown.

**Date fields** use spinbutton elements — click Calendar button → click today.

### SmartRecruiters

**URL:** `https://jobs.smartrecruiters.com/oneclick-ui/company/{Company}/publication/{uuid}`

**Unique:** Has "Confirm your email" field — MUST fill both email fields.

---

## EXISTING CODE — REUSE THIS

### 1. greenhouse-filler.py (Playwright-based, battle-tested)

This is a standalone Python script using Playwright directly. It:
- Maps ALL form fields using `query_selector_all('input, textarea')`
- Matches labels to profile values via `match_answer()` (longest substring match)
- Handles comboboxes with `select_combobox_option()` (click→type→find option→click)
- Handles phone country code dropdown (JS fallback)
- Uploads resume via `set_input_files()`
- Finds submit button with multiple selector fallbacks + scroll retry
- Takes screenshots
- Returns status: submitted / captcha_blocked / no_submit_button / flagged

**Location:** `~/.openclaw/scripts/greenhouse-filler.py`

**Key functions to reuse:**
- `match_answer(label, answers_dict)` — longest substring match for field→value mapping
- `select_combobox_option(page, combobox, answer)` — handles Greenhouse ARIA comboboxes
- `fill_greenhouse_form(url)` — end-to-end fill + submit
- `DROPDOWN_ANSWERS` dict — all dropdown mappings
- `TEXT_ANSWERS` dict — all text field mappings

### 2. fast-apply-greenhouse.py (CLI-based, uses OpenClaw browser commands)

Same logic but uses `openclaw browser` CLI subprocess calls instead of Playwright directly. Useful if you're running inside OpenClaw. Has:
- `parse_snapshot(raw)` — parses OpenClaw snapshot output into {ref, type, label} dicts
- `match_text_field(label)` — maps labels to profile values
- `match_dropdown(label)` — maps dropdown labels to answers
- `pick_resume(title)` — selects GenAI or DS resume based on job title
- `pre_filter(job)` — kills irrelevant jobs by title/company/seniority
- Batch mode from LinkedIn scraper results
- Telegram notifications

**Location:** `~/.openclaw/scripts/fast-apply-greenhouse.py`

### 3. linkedin-scraper-v2.py (LinkedIn job scraper)

Playwright-based scraper that:
- Searches 14 AI/ML/Data role queries on LinkedIn
- Deduplicates against seen jobs
- Classifies: external apply vs Easy Apply
- Extracts external apply URLs (needs Playwright, not just API)
- Pre-filters by title, company, consultancy detection
- Outputs JSON with job details + apply URLs

**Location:** `~/.openclaw/scripts/linkedin-scraper-v2.py`

---

## LEARNINGS (sorted by importance)

### CRITICAL — Will break your applicator if ignored

1. **Greenhouse comboboxes are NOT native selects** — ARIA widgets. Must click→type→pick from listbox.
2. **Phone country dropdown** — Set "United States" BEFORE filling phone or it won't save.
3. **Resume upload** — Use file input interceptor. NEVER click attach button directly (opens native dialog, hangs).
4. **Location autocomplete** — Type "Dallas" not "{city}". "{city}" returns zero results.
5. **Lever uses "Full Name" as ONE field** — Not separate first/last like Greenhouse.
6. **SmartRecruiters has "Confirm Email"** — Must fill email twice.
7. **Workday accounts are GLOBAL** — One signup works across ALL Workday companies.
8. **Greenhouse email verification** — Some companies (Stripe, Datadog) require 8-char code after submit. One char per input box.

### IMPORTANT — Will waste time if ignored

9. **Pre-filter before opening browser** — Filter on scraped data first. Don't open irrelevant jobs.
10. **Batch fill text fields** — Fill ALL text fields in one call, not one at a time. 10x faster.
11. **EEO dropdowns can be filled via JS** — One `evaluate()` call fills gender, race, veteran, disability. No click→snapshot→click needed.
12. **DOM refs are unstable** — Re-snapshot before every interaction. Never cache refs.
13. **Submit button may need scroll** — Some forms have submit below the fold. Scroll to bottom and retry.
14. **Post-submit varies** — Greenhouse shows "Thank you" OR blank redirect. Screenshot within 3 seconds.
15. **Anthropic forms don't load** — Skip Anthropic Greenhouse jobs, their embed is broken.

### NICE TO KNOW — Edge cases

16. **Stripe has many form variants** — Different required fields per role. Some need residence country, work countries checkbox, BrightHire consent.
17. **Ashby has anti-bot** — Submit may silently fail. If button does nothing after 2 tries, classify as blocked.
18. **Workday "How Did You Hear" is two-level** — Click "Job Board" → then click "LinkedIn Jobs" in sub-dropdown.
19. **Cloudflare "How did you hear" is a text field** — Not a dropdown. Just type "LinkedIn".
20. **Brex requires explicit phone country** — Submit fails without it selected.
21. **Stripe pause** — DO NOT apply to Stripe until 2026-03-25 (applied recently).

---

## RESUME SELECTION LOGIC

```python
DS_KEYWORDS = ["data scientist", "data engineer", "data analyst", "analytics", "business intelligence"]

def pick_resume(title):
    if any(kw in title.lower() for kw in DS_KEYWORDS):
        return "{full_name} DS Resume.pdf"
    return "{full_name} GenAI Resume.pdf"
```

---

## PRE-FILTER LOGIC (reuse this)

```python
TITLE_KILL = [
    "staff", "principal", "distinguished", "fellow", "director", "vp ", "vice president",
    "head of", "chief", "manager", "lead engineer", "lead software", "lead data",
    "senior lead", "scientific lead", "intern ", "internship",
    "frontend", "front end", "front-end", "ui engineer", "mobile",
    "ios ", "android", "embedded", "firmware", "hardware",
    "cybersecurity", "security engineer", "network engineer",
    "qa ", "qe ", "sdet", "test engineer", "devops", "site reliability",
    "solutions architect", "sales engineer", "support engineer",
    "blockchain", "crypto", "web3", "tax ", "accounting",
    "backend engineer", "backend developer",
]

COMPANY_KILL = [
    "anduril", "palantir", "lockheed", "raytheon", "northrop", "l3harris",
    "wipro", "infosys", "tcs", "cognizant", "hcl", "robert half", "randstad",
    "harnham", "brooksource", "kastech", "hire5", "career hire", "modmed",
    "wiraa", "bestjobtool", "jobright", "hirenza",
]
```

---

## CANNED ANSWERS (for essays/textareas)

### Why interested?
I am passionate about building AI-powered solutions that create real-world impact. With 4+ years of experience spanning AI engineering, data engineering, and software development, I bring hands-on expertise in production ML systems, multi-agent architectures, and large-scale data pipelines. At {current_company}, I shipped an ambient AI Scribe serving 5,000+ healthcare providers and built hallucination detection systems achieving 92% accuracy. I thrive in fast-paced environments where I can take ideas from prototype to production.

### What makes you a good fit?
I bring a rare combination of AI/ML depth and production engineering skills. I have built and shipped multi-agent RAG systems, fine-tuned LLMs with LoRA, designed real-time data pipelines processing 1M+ logs/day, and deployed computer vision models. I also have two published research papers (SPIE 2024, IEEE Explore 2023).

### Additional info
I am currently on F-1 OPT STEM Extension and will require H-1B visa sponsorship. I have two published research papers (SPIE 2024, IEEE Explore 2023). Portfolio: {github_url}

### Cover letter
I am writing to express my interest in this role. With 4+ years of experience in AI engineering, software development, and data engineering, along with a Master's in Computer & Information Science from the University of Florida, I bring a strong foundation in building production AI systems at scale. In my current role as an AI Engineer at {current_company}, I shipped a clinical ambient AI Scribe serving 5,000+ providers that automates 70% of documentation, built an AI Fax system cutting costs from $400K to $20K/month, and open-sourced MEDHALT — a hallucination detection suite achieving 92% accuracy.

---

## TELEGRAM NOTIFICATIONS

```python
TOKEN = "{TELEGRAM_BOT_TOKEN}"
CHAT_ID = "{TELEGRAM_CHAT_ID}"

# Send text
curl -s -X POST "https://api.telegram.org/bot{TOKEN}/sendMessage" -F "chat_id={CHAT_ID}" -F "text={message}"

# Send photo with caption
curl -s -X POST "https://api.telegram.org/bot{TOKEN}/sendPhoto" -F "chat_id={CHAT_ID}" -F "photo=@{path}" -F "caption={text}"
```

---

## GMAIL VERIFICATION (for ATS email codes)

```bash
# List recent emails
himalaya envelope list --account gmail --folder INBOX --page-size 5 -o json

# Read email body
himalaya message read --account gmail --folder INBOX {id}

# Check spam
himalaya envelope list --account gmail --folder "[Gmail]/Spam" --page-size 5
```

Common verification senders:
- Greenhouse: `no-reply@us.greenhouse-mail.io`
- Workday: `{company}@otp.workday.com`

---

## STATS (as of Feb 28, 2026)

- 61 applications submitted
- 354 total entries tracked
- Platforms conquered: Greenhouse (50+), Lever, Ashby, Workday, SmartRecruiters
- Companies applied to: 15+
- Biggest blockers: reCAPTCHA, Anthropic broken forms, senior roles at big tech

---

## EXISTING SCRIPT LOCATIONS

| File | Description |
|------|-------------|
| `~/.openclaw/scripts/greenhouse-filler.py` | Playwright-based Greenhouse form filler (battle-tested) |
| `~/.openclaw/scripts/fast-apply-greenhouse.py` | CLI-based fast Greenhouse applier (uses OpenClaw browser) |
| `~/.openclaw/scripts/linkedin-scraper-v2.py` | LinkedIn job scraper (Playwright, saved session) |
| `~/.openclaw/agents/job-bot/workspace/PROFILE.md` | Full user profile (all 16 sections) |
| `~/.openclaw/agents/job-bot/workspace/SOUL.md` | Agent instructions (apply flow, platform rules) |
| `~/.openclaw/agents/job-bot/workspace/memory/learnings.md` | Platform learnings (everything above + more) |
| `~/Downloads/my-details.md` | All personal details in one file |
| `~/Downloads/auto-apply-agent-product-prompt.md` | Full product blueprint for self-learning system |
