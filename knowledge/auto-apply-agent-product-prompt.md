# ApplyLoop — Self-Learning Autonomous Job Application Agent

## Build Prompt for an Agentic Coding AI (Claude / Codex / GPT)

You are building **ApplyLoop** — a fully autonomous, self-learning job application system. It starts with a user profile and within 100 applications across different platforms, it will have learned every ATS pattern, every form structure, every edge case, and can apply to any job for any user instantly.

**This is NOT an "LLM reads each form field" bot.** This is a self-improving codebase where:
- **Code does the execution** (scraping, form filling, file upload) at machine speed
- **AI is the supervisor** that watches, decides, and WRITES NEW CODE when it encounters something it hasn't seen before
- After enough applications, the system runs 95% on structured code and 5% on AI fallback

---

## THE CORE IDEA

```
First application on Greenhouse:
  → AI watches every field, figures out the structure
  → AI WRITES a Greenhouse handler (Python + Playwright)
  → Saves it as applicators/greenhouse.py

Second application on Greenhouse:
  → Runs the code it wrote last time
  → Encounters a new field type it hasn't seen → AI patches the code
  → Updates applicators/greenhouse.py

By application #10 on Greenhouse:
  → Code handles 100% of Greenhouse forms
  → AI is only called for custom company-specific questions
  → Each application takes 15-30 seconds

Same process for Lever, Ashby, Workday, SmartRecruiters, iCIMS, Taleo...
After 100 total applications across all platforms:
  → The codebase is a battle-tested ATS automation library
  → Works for ANY user profile (just change the config)
  → Ready to sell commercially
```

---

## ARCHITECTURE

```
┌────────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR (Python)                         │
│  Async loop: scrape → filter → apply → learn → repeat                │
├──────────┬──────────┬──────────────┬────────────┬─────────────────────┤
│ SCRAPER  │ FILTER   │ APPLICATOR   │ AI BRAIN   │ LEARNER            │
│ (code)   │ (code+AI)│ (code+AI)    │ (LLM API)  │ (code generation)  │
│          │          │              │            │                    │
│ Pure HTTP│ Rules +  │ Per-ATS      │ Supervisor │ Watches failures   │
│ + Playw. │ AI score │ handlers     │ + Coder    │ Writes new code    │
│          │          │ (auto-gen)   │            │ Updates playbooks  │
└──────────┴──────────┴──────────────┴────────────┴─────────────────────┘
         │              │              │               │
         └──────────────┴──────┬───────┴───────────────┘
                               │
              ┌────────────────▼────────────────┐
              │        KNOWLEDGE BASE           │
              │ • SQLite DB (jobs, apps, accts) │
              │ • playbooks/*.json (per ATS)    │
              │ • applicators/*.py (auto-gen)   │
              │ • field_map.json (learned)      │
              │ • profile.yaml (user config)    │
              └─────────────────────────────────┘
```

### The AI Brain Has Two Modes:

**1. SUPERVISOR MODE** — Watches the coded applicator run. If the code handles the form fine, AI does nothing. If the code errors or encounters an unknown field, AI steps in to:
   - Answer the unknown question
   - Figure out the correct selector/interaction
   - Patch the applicator code to handle this case next time

**2. CODER MODE** — When encountering a brand-new ATS platform for the first time, AI:
   - Takes a snapshot of the form
   - Analyzes the HTML structure
   - WRITES a complete Python applicator class for that ATS
   - Tests it on the current job
   - Saves it for future use

---

## TECH STACK

```
Language:       Python 3.11+
Browser:        Playwright (async API)
HTTP:           httpx (async)
Database:       SQLite (via aiosqlite)
AI Provider:    OpenAI API (Codex subscription) OR Anthropic API (Claude)
                — used for: scoring, code generation, error recovery
                — NOT used for: form filling, scraping, clicking
Fast LLM:      Groq API (Llama 4 Maverick) — for quick decisions ($0.15/10 apps)
Smart LLM:     Claude Opus or GPT-4o — for code generation and complex reasoning
Notifications:  Telegram Bot API
Email:          IMAP (Gmail) — for verification codes
Config:         YAML
```

---

## FILE STRUCTURE

```
applyloop/
├── main.py                        # Entry point — starts orchestrator
├── config/
│   ├── profile.yaml               # User profile (name, email, answers, etc.)
│   ├── settings.yaml              # API keys, Telegram, preferences, target roles
│   └── credentials.yaml           # ATS passwords, Gmail app password (encrypted)
├── core/
│   ├── orchestrator.py            # Main pipeline loop
│   ├── database.py                # SQLite models + queries
│   ├── browser.py                 # Playwright browser manager
│   └── llm.py                     # AI client (OpenAI/Anthropic/Groq)
├── scrapers/                      # Job source scrapers (all code, no AI)
│   ├── base.py                    # BaseScraper class
│   ├── greenhouse.py              # Pure HTTP API scraper
│   ├── lever.py                   # Pure HTTP API scraper
│   ├── linkedin.py                # Playwright (needs login session)
│   ├── workday.py                 # Playwright (SPA)
│   ├── indeed.py                  # HTTP + parsing
│   └── github_repos.py            # Pure HTTP
├── filters/
│   ├── rules.py                   # Hard rules: title/company/location/seniority
│   └── ai_scorer.py              # Batch LLM scoring (20 jobs per call)
├── applicators/                   # ATS-specific form fillers
│   ├── base.py                    # BaseApplicator class
│   ├── greenhouse.py              # Auto-generated + manually refined
│   ├── lever.py                   # Auto-generated
│   ├── ashby.py                   # Auto-generated
│   ├── workday.py                 # Auto-generated
│   ├── smartrecruiters.py         # Auto-generated
│   ├── icims.py                   # Auto-generated (when first encountered)
│   └── unknown.py                 # Fallback: AI-driven form filler for new ATS
├── brain/
│   ├── supervisor.py              # AI supervisor — watches applicator, intervenes on errors
│   ├── coder.py                   # AI code generator — writes new applicator code
│   └── learner.py                 # Active learning — updates playbooks after each app
├── knowledge/
│   ├── playbooks/                 # Per-ATS JSON playbooks (learned patterns)
│   │   ├── greenhouse.json        # Selector patterns, field maps, quirks
│   │   ├── lever.json
│   │   ├── ashby.json
│   │   ├── workday.json
│   │   └── ...
│   ├── field_map.json             # Global field label → answer mapping (grows over time)
│   ├── known_failures.json        # Patterns that cause failures + workarounds
│   └── ats_detection.json         # URL patterns → ATS type mapping
├── notifications/
│   └── telegram.py                # Telegram Bot API
├── email/
│   └── gmail_reader.py            # IMAP reader for verification codes
├── data/
│   └── autoapply.db               # SQLite database
└── requirements.txt
```

---

## DETAILED MODULE SPECIFICATIONS

### 1. USER PROFILE (config/profile.yaml)

This is the ONLY file a new user needs to fill out. Everything else is auto-configured.

```yaml
# ─── IDENTITY ─────────────────────────────────────────────────
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
  twitter: ""

# ─── WORK ─────────────────────────────────────────────────────
work:
  current_company: "{current_company}"
  current_title: "AI Engineer"
  years_experience: 4
  experiences:
    - title: "AI Engineer"
      company: "{current_company}"
      start: "2025-01"
      end: "Present"
      description: "Built ambient AI Scribe serving 5,000+ providers, AI Fax system cutting costs from $400K to $20K/month, open-sourced MEDHALT hallucination detection achieving 92% accuracy."
    - title: "Data Engineer"
      company: "{current_company}"
      start: "2024-05"
      end: "2025-01"
      description: "Built real-time data pipelines processing 1M+ logs/day, Apache Spark ETL, Airflow orchestration, Snowflake data warehouse."
    - title: "AI/ML Research Assistant"
      company: "University of Florida"
      start: "2023-01"
      end: "2024-05"
      description: "Multi-agent RAG systems, LLM fine-tuning with LoRA, computer vision models. Published at SPIE 2024 and IEEE Explore 2023."

# ─── EDUCATION ────────────────────────────────────────────────
education:
  school: "University of Florida"
  degree: "Master's in Computer & Information Science"
  field: "Computer & Information Science"
  graduation_year: "2024"
  gpa: ""

# ─── LEGAL ────────────────────────────────────────────────────
legal:
  authorized_to_work_us: true
  requires_sponsorship: true    # Needs H-1B visa sponsorship
  visa_status: "F-1 OPT STEM Extension"
  felony: false
  background_check: true
  drug_test: true
  non_compete: false
  security_clearance: false

# ─── EEO (Voluntary) ─────────────────────────────────────────
eeo:
  gender: "Male"
  race: "Asian"
  hispanic: "No"
  veteran: "I am not a protected veteran"
  disability: "No, I do not have a disability"

# ─── PREFERENCES ──────────────────────────────────────────────
preferences:
  target_roles:
    - "AI Engineer"
    - "Machine Learning Engineer"
    - "GenAI Engineer"
    - "LLM Engineer"
    - "MLOps Engineer"
    - "Applied Scientist"
    - "Data Scientist"
    - "Data Engineer"
    - "Software Engineer AI"
    - "Software Engineer Machine Learning"
    - "Platform Engineer ML"
    - "Research Engineer AI"
    - "NLP Engineer"
    - "Computer Vision Engineer"
  exclude_roles:
    - "Frontend"
    - "Mobile"
    - "iOS"
    - "Android"
    - "Backend Engineer"       # Unless AI/ML adjacent
    - "Full Stack Engineer"
    - "Systems Engineer"
    - "Infrastructure Engineer"
    - "Cloud Engineer"
    - "DevOps"
    - "QA"
    - "SDET"
    - "Security Engineer"
    - "Cybersecurity"
    - "Solutions Architect"
    - "Sales Engineer"
    - "Support Engineer"
    - "Blockchain"
    - "Embedded"
    - "Firmware"
    - "Hardware"
  exclude_companies:
    - "Anduril"                # Defense, needs US citizenship
    - "Palantir"               # Security clearance
    - "Lockheed Martin"
    - "Raytheon"
    - "Northrop Grumman"
    - "L3Harris"
    - "Wipro"                  # Staffing/outsourcing
    - "Infosys"
    - "TCS"
    - "Cognizant"
    - "HCL"
    - "Robert Half"
    - "Randstad"
    - "{current_company}"                 # Current employer
    - "Wiraa"                  # Shady sites
    - "BestJobTool"
    - "Jobright.ai"
    - "Hirenza"
  salary_range: "$120,000 - $170,000"
  salary_min: 110000
  location: "Remote or Hybrid, US"
  willing_to_relocate: true
  start_date: "2 weeks from offer acceptance"

# ─── RESUMES ─────────────────────────────────────────────────
resumes:
  default: "./resume.pdf"      # Place your resume here
  # Optional: role-specific resumes
  # data_science: "./ds_resume.pdf"

# ─── ANSWERS (common form questions) ─────────────────────────
answers:
  how_did_you_hear: "LinkedIn"
  cover_letter: >
    I am writing to express my interest in this role. With 4+ years of experience
    in AI engineering, software development, and data engineering, along with a
    Master's in Computer & Information Science from the University of Florida,
    I bring a strong foundation in building production AI systems at scale.
    In my current role as an AI Engineer at {current_company}, I shipped a clinical ambient
    AI Scribe serving 5,000+ providers that automates 70% of documentation,
    built an AI Fax system cutting costs from $400K to $20K/month, and
    open-sourced MEDHALT — a hallucination detection suite achieving 92% accuracy.
  why_interested: >
    I am passionate about building AI-powered solutions that create real-world
    impact. With 4+ years of experience spanning AI engineering, data engineering,
    and software development, I bring hands-on expertise in production ML systems,
    multi-agent architectures, and large-scale data pipelines. At {current_company}, I shipped
    an ambient AI Scribe serving 5,000+ healthcare providers and built hallucination
    detection systems achieving 92% accuracy. I thrive in fast-paced environments
    where I can take ideas from prototype to production.
  what_makes_you_good_fit: >
    I bring a rare combination of AI/ML depth and production engineering skills.
    I have built and shipped multi-agent RAG systems, fine-tuned LLMs with LoRA,
    designed real-time data pipelines processing 1M+ logs/day, and deployed
    computer vision models. I also have two published research papers
    (SPIE 2024, IEEE Explore 2023).
  additional_info: >
    I am currently on F-1 OPT STEM Extension and will require H-1B visa
    sponsorship. I have two published research papers (SPIE 2024, IEEE Explore 2023).
    Portfolio: {github_url}

# ─── CREDENTIALS ──────────────────────────────────────────────
credentials:
  ats_email: "{email}"
  ats_password: "{REMOVED_PASSWORD}"   # Default password for ATS account creation
  gmail_app_password: ""              # For IMAP (reading verification emails)
  telegram_bot_token: "{TELEGRAM_BOT_TOKEN}"
  telegram_chat_id: "{TELEGRAM_CHAT_ID}"
```

### 2. KNOWLEDGE BASE (Auto-Generated, Self-Updating)

#### knowledge/playbooks/greenhouse.json (example — auto-generated after first few apps)

```json
{
  "ats": "greenhouse",
  "version": 12,
  "last_updated": "2026-02-27T18:00:00Z",
  "applications_seen": 42,
  "success_rate": 0.88,

  "url_patterns": [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "boards-api.greenhouse.io"
  ],

  "embed_url_template": "https://boards.greenhouse.io/embed/job_app?for={company}&token={job_id}",
  "api_url_template": "https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true",

  "form_structure": {
    "type": "single_page",
    "sections": ["personal_info", "links", "resume", "custom_questions", "eeo"]
  },

  "field_selectors": {
    "first_name": ["#first_name", "input[name='first_name']", "input[aria-label*='First Name' i]"],
    "last_name": ["#last_name", "input[name='last_name']", "input[aria-label*='Last Name' i]"],
    "email": ["#email", "input[name='email']", "input[type='email']"],
    "phone": ["#phone", "input[name='phone']"],
    "resume_upload": ["input[type='file'][id*='resume' i]", "input[type='file']"],
    "submit": ["button[type='submit']", "input[type='submit']", "button:has-text('Submit')"]
  },

  "dropdown_type": "aria_combobox",
  "dropdown_interaction": "click_to_open → query_options → click_option",
  "dropdown_note": "Option elements are created dynamically. Must re-query after opening.",

  "location_autocomplete": {
    "type": "combobox_with_search",
    "search_term": "Dallas",
    "select_text": "Dallas, Texas, United States",
    "note": "'{city}' returns zero results. Always search 'Dallas'."
  },

  "eeo_section": {
    "type": "native_select",
    "fields": ["gender", "race", "ethnicity", "hispanic", "veteran", "disability"]
  },

  "resume_upload": {
    "method": "set_input_files",
    "selector": "input[type='file']",
    "note": "NEVER click the attach button directly — opens native file dialog. Use Playwright set_input_files()."
  },

  "post_submit": {
    "success_indicators": ["thank you for applying", "application submitted", "your application has been received"],
    "blank_page_is_success": true,
    "email_verification_possible": true,
    "verification_from": "no-reply@us.greenhouse-mail.io",
    "verification_code_length": 8,
    "verification_entry": "one_char_per_input_box"
  },

  "known_quirks": [
    {"issue": "combobox looks empty after selection", "resolution": "normal behavior — value is saved"},
    {"issue": "location field fails validation", "resolution": "must click autocomplete suggestion, not just type"},
    {"issue": "reCAPTCHA blocks after many apps", "resolution": "slow down to 1/min, or switch to another ATS"},
    {"issue": "country dropdown required but hidden", "resolution": "always set to 'United States'"},
    {"issue": "phone country code prefix", "resolution": "some forms need explicit 'United States +1' selection"}
  ],

  "companies_tested": [
    "figma", "datadog", "cloudflare", "stripe", "ramp", "brex", "postman",
    "databricks", "anthropic", "scale", "airbnb", "zscaler", "posthog"
  ]
}
```

#### knowledge/field_map.json (global — grows with every application)

```json
{
  "_description": "Maps form field labels to profile values. Updated automatically after each application.",
  "_entries": 147,

  "text_fields": {
    "first name": "profile.personal.first_name",
    "last name": "profile.personal.last_name",
    "full name": "profile.personal.full_name",
    "name": "profile.personal.full_name",
    "email": "profile.personal.email",
    "confirm email": "profile.personal.email",
    "confirm your email": "profile.personal.email",
    "phone": "profile.personal.phone",
    "linkedin": "profile.links.linkedin",
    "github": "profile.links.github",
    "website": "profile.links.website",
    "current company": "profile.work.current_company",
    "current title": "profile.work.current_title",
    "school": "profile.education.school",
    "degree": "profile.education.degree",
    "graduation year": "profile.education.graduation_year",
    "salary": "profile.preferences.salary_range",
    "years of experience": "profile.work.years_experience",
    "signature": "profile.personal.full_name"
  },

  "dropdown_fields": {
    "authorized to work": {"answer": "Yes", "variations": ["legally authorized", "eligible to work"]},
    "require sponsorship": {"answer": "profile.legal.requires_sponsorship", "variations": ["immigration sponsorship", "visa sponsorship"]},
    "gender": {"answer": "profile.eeo.gender"},
    "race": {"answer": "profile.eeo.race"},
    "veteran": {"answer": "profile.eeo.veteran"},
    "disability": {"answer": "profile.eeo.disability"}
  },

  "learned_fields": {
    "brighthire consent": {"answer": "Yes", "learned_from": "stripe_application_2026-02-24", "confidence": 0.95},
    "whatsapp opt-in": {"answer": "No", "learned_from": "stripe_application_2026-02-24", "confidence": 0.95},
    "acknowledge in-office policy": {"answer": "Yes", "learned_from": "brex_application_2026-02-24", "confidence": 0.9}
  }
}
```

### 3. THE BRAIN — AI SUPERVISOR + CODER

```python
# brain/supervisor.py

class AISupervisor:
    """
    The brain of ApplyLoop. Watches the coded applicators run and intervenes
    when they can't handle something. Has two capabilities:

    1. ANSWER — When a form field isn't in field_map.json, ask AI what to fill
    2. CODE — When a new ATS is encountered or code fails, write/patch Python code

    Uses two LLM tiers:
    - Fast (Groq/Llama): quick decisions, field answers, scoring
    - Smart (Claude/GPT-4o): code generation, complex reasoning
    """

    def __init__(self, fast_llm, smart_llm, knowledge_base):
        self.fast = fast_llm      # Groq — $0.001/call, 500ms latency
        self.smart = smart_llm    # Claude/GPT — $0.02/call, 2s latency
        self.kb = knowledge_base

    async def handle_unknown_field(self, field_label, field_type, page_context):
        """
        Called when the applicator encounters a field not in field_map.json.

        1. Ask fast LLM for the answer
        2. Fill the field
        3. Add to field_map.json so it's handled by code next time
        """
        answer = await self.fast.chat(f"""
Job application field I haven't seen before.
Label: "{field_label}"
Type: {field_type}

User profile summary: {self.kb.profile_summary}

What should this field be filled with? Reply with ONLY the value.""")

        # Learn this field for next time
        self.kb.add_field_mapping(field_label, answer, confidence=0.8)

        return answer

    async def handle_applicator_failure(self, ats, error, page_html_snippet):
        """
        Called when an applicator's code crashes or produces wrong results.

        1. Diagnose the issue with smart LLM
        2. Generate a code patch
        3. Apply the patch to the applicator file
        4. Retry the application
        """
        diagnosis = await self.smart.chat(f"""
The {ats} applicator failed with: {error}

Page HTML (relevant section):
{page_html_snippet[:3000]}

Current applicator code:
{self.kb.read_applicator(ats)}

What went wrong? Write a MINIMAL code patch (Python) to fix this specific issue.
Return the patch as a unified diff or a replacement function.""")

        # Apply the patch
        patched = self.kb.apply_code_patch(ats, diagnosis)
        return patched

    async def generate_new_applicator(self, ats_name, page_html, form_snapshot):
        """
        Called when we encounter a BRAND NEW ATS platform for the first time.

        The smart LLM analyzes the form structure and writes a complete
        Python applicator class from scratch.
        """
        code = await self.smart.chat(f"""
Write a Python applicator class for a new ATS platform: {ats_name}

The form HTML structure:
{page_html[:5000]}

Interactive elements found:
{form_snapshot}

Base class to inherit from:
```python
class BaseApplicator:
    def __init__(self, page, profile, resume_path): ...
    async def apply(self, job) -> ApplicationResult: ...
    async def fill_text(self, selector, value): ...
    async def upload_file(self, selector, path): ...
    async def select_dropdown(self, selector, value): ...
    async def click_button(self, selector): ...
    async def screenshot(self, path): ...
```

Profile data is available as self.profile (dict from profile.yaml).
Resume path is self.resume.

Write the complete class. Use Playwright async API.
Handle: text fields, dropdowns, file upload, checkboxes, submit.
Map field labels to profile values using the field_map.json pattern.

Return ONLY the Python code, no explanation.""")

        # Save the new applicator
        self.kb.save_applicator(ats_name, code)
        return code
```

### 4. THE LEARNER — Active Learning System

```python
# brain/learner.py

class ActiveLearner:
    """
    Watches every application and learns from it. Updates:
    - field_map.json — new field→answer mappings
    - playbooks/*.json — ATS-specific patterns and quirks
    - applicators/*.py — code patches for edge cases
    - known_failures.json — failure patterns + workarounds

    The goal: after 100 applications, the system should be 95% code-driven
    and need AI only for truly novel situations.
    """

    def __init__(self, knowledge_base, supervisor):
        self.kb = knowledge_base
        self.supervisor = supervisor

    async def learn_from_application(self, job, result, form_fields_encountered):
        """Called after every application attempt (success or failure)."""

        ats = job.get("ats", "unknown")
        playbook = self.kb.get_playbook(ats)

        # 1. Update field map with any new fields we successfully filled
        for field in form_fields_encountered:
            if field["source"] == "ai_answered":
                # AI had to answer this — add to field_map so code handles it next time
                self.kb.add_field_mapping(
                    field["label"],
                    field["answer"],
                    learned_from=f"{job['company']}_{job['job_id']}",
                    confidence=0.85 if result.status == "submitted" else 0.5
                )

        # 2. Update playbook stats
        playbook["applications_seen"] = playbook.get("applications_seen", 0) + 1
        if result.status == "submitted":
            playbook["successes"] = playbook.get("successes", 0) + 1
        playbook["success_rate"] = playbook["successes"] / playbook["applications_seen"]

        # 3. If failure, record the pattern
        if result.status == "failed":
            self.kb.add_known_failure(ats, {
                "error": result.error,
                "company": job["company"],
                "job_id": job["job_id"],
                "timestamp": datetime.utcnow().isoformat(),
                "resolution": "pending"  # AI will fill this if it fixes it
            })

        # 4. Discover new selectors
        for field in form_fields_encountered:
            if field.get("selector") and field["selector"] not in playbook.get("field_selectors", {}).get(field["label"], []):
                # New selector for a known field — add it as an alternative
                playbook.setdefault("field_selectors", {}).setdefault(field["label"], []).append(field["selector"])

        # 5. Track company-specific overrides
        if job.get("company_specific_fields"):
            playbook.setdefault("company_overrides", {})[job["company"]] = job["company_specific_fields"]

        # 6. Save updated playbook
        self.kb.save_playbook(ats, playbook)

        # 7. Log learning event
        self.kb.log_learning({
            "type": "application_completed",
            "ats": ats,
            "company": job["company"],
            "status": result.status,
            "new_fields_learned": len([f for f in form_fields_encountered if f["source"] == "ai_answered"]),
            "total_fields_in_map": self.kb.field_map_size(),
            "playbook_version": playbook.get("version", 0) + 1,
        })

    async def learn_from_new_ats(self, ats_name, page_html, form_snapshot):
        """Called when we encounter a completely new ATS platform."""
        # AI generates the initial applicator code
        code = await self.supervisor.generate_new_applicator(ats_name, page_html, form_snapshot)

        # Create initial playbook
        playbook = {
            "ats": ats_name,
            "version": 1,
            "last_updated": datetime.utcnow().isoformat(),
            "applications_seen": 0,
            "success_rate": 0,
            "auto_generated": True,
            "needs_testing": True,
        }
        self.kb.save_playbook(ats_name, playbook)

        return code

    def get_confidence(self, ats):
        """How confident are we in the applicator for this ATS?"""
        playbook = self.kb.get_playbook(ats)
        if not playbook:
            return 0.0  # Never seen — AI will drive everything
        apps = playbook.get("applications_seen", 0)
        rate = playbook.get("success_rate", 0)
        if apps < 3:
            return 0.3  # Low confidence — AI should supervise closely
        if apps < 10:
            return 0.6  # Medium — AI supervises on errors only
        if rate > 0.8:
            return 0.95  # High — code runs autonomously
        return 0.7
```

### 5. ATS DETECTION

```python
# knowledge/ats_detection.json
{
  "url_patterns": {
    "greenhouse": ["boards.greenhouse.io", "job-boards.greenhouse.io", "boards-api.greenhouse.io"],
    "lever": ["jobs.lever.co", "api.lever.co"],
    "ashby": ["jobs.ashbyhq.com"],
    "workday": ["myworkdayjobs.com", ".wd1.", ".wd5.", ".wd12."],
    "smartrecruiters": ["jobs.smartrecruiters.com"],
    "icims": ["careers-", ".icims.com"],
    "taleo": [".taleo.net"],
    "bamboohr": ["bamboohr.com/careers"],
    "jazz": ["app.jazz.co"]
  },
  "fallback": "unknown"
}

def detect_ats(url: str) -> str:
    """Detect ATS platform from URL. Returns platform name or 'unknown'."""
    url_lower = url.lower()
    for ats, patterns in ATS_PATTERNS.items():
        for pattern in patterns:
            if pattern in url_lower:
                return ats
    return "unknown"
```

### 6. THE UNKNOWN ATS HANDLER (AI-Driven Fallback)

```python
# applicators/unknown.py

class UnknownATSApplicator(BaseApplicator):
    """
    Fallback applicator for ATS platforms we haven't seen before.
    AI drives everything on the first encounter. The learner watches
    and generates a proper applicator class for next time.

    This is the SLOWEST path (~60s per app) but it's how the system
    learns new platforms autonomously.
    """

    def __init__(self, page, profile, resume_path, supervisor, learner):
        super().__init__(page, profile, resume_path)
        self.supervisor = supervisor
        self.learner = learner

    async def apply(self, job):
        start = time.time()

        # Navigate to form
        await self.page.goto(job["apply_url"], wait_until="networkidle", timeout=15000)

        # Get full page HTML and interactive elements
        html = await self.page.content()
        snapshot = await self._get_form_snapshot()

        # Ask AI to analyze the form and generate an applicator
        ats_name = detect_ats(job["apply_url"])
        if ats_name == "unknown":
            # Try to identify from page content
            ats_name = await self.supervisor.fast.chat(
                f"What ATS platform is this? URL: {job['apply_url']}\nPage title: {await self.page.title()}\nReply with just the name."
            )
            ats_name = ats_name.strip().lower().replace(" ", "_")

        # Generate applicator code for this new ATS
        code = await self.learner.learn_from_new_ats(ats_name, html, snapshot)

        # For this first application, use AI to guide through the form step by step
        result = await self._ai_guided_apply(job, html, snapshot)

        return result

    async def _ai_guided_apply(self, job, html, snapshot):
        """AI walks through the form field by field."""

        # Ask AI to plan the fill sequence
        plan = await self.supervisor.smart.chat(f"""
Analyze this job application form and create a step-by-step fill plan.

Form elements:
{snapshot}

User profile:
- Name: {self.profile['personal']['first_name']} {self.profile['personal']['last_name']}
- Email: {self.profile['personal']['email']}
- Phone: {self.profile['personal']['phone']}
[... abbreviated ...]

For each field, output JSON:
[
  {{"step": 1, "action": "fill", "selector": "CSS selector", "value": "text to fill"}},
  {{"step": 2, "action": "upload", "selector": "CSS selector", "file": "resume"}},
  {{"step": 3, "action": "select", "selector": "CSS selector", "value": "option text"}},
  {{"step": 4, "action": "click", "selector": "CSS selector", "purpose": "submit"}}
]""")

        steps = json.loads(plan)

        for step in steps:
            try:
                if step["action"] == "fill":
                    await self.page.fill(step["selector"], step["value"])
                elif step["action"] == "upload":
                    await self.page.set_input_files(step["selector"], self.resume)
                elif step["action"] == "select":
                    await self.page.select_option(step["selector"], label=step["value"])
                elif step["action"] == "click":
                    await self.page.click(step["selector"])
                    if step.get("purpose") == "submit":
                        await self.page.wait_for_timeout(5000)
            except Exception as e:
                # Ask AI to recover
                recovery = await self.supervisor.handle_applicator_failure(
                    "unknown", str(e), await self.page.content()
                )

        ss_path = f"/tmp/screenshots/{job['company']}_{job['job_id']}.png"
        await self.screenshot(ss_path)
        return ApplicationResult("submitted", ss_path, duration_seconds=time.time()-start)
```

### 7. ORCHESTRATOR — Main Pipeline

```python
# core/orchestrator.py

class Orchestrator:
    async def run_cycle(self):
        """One full scrape → filter → apply → learn cycle."""

        # ── SCRAPE (parallel, no AI, ~5 seconds) ──
        all_jobs = await asyncio.gather(
            self.scrapers["greenhouse"].scrape_all(),
            self.scrapers["lever"].scrape_all(),
            self.scrapers["linkedin"].scrape(),
            # ... more sources
        )
        all_jobs = [j for batch in all_jobs for j in batch]
        new_jobs = await self.db.dedup(all_jobs)

        # ── PRE-FILTER (rules, no AI, instant) ──
        passed = [j for j in new_jobs if pre_filter(j)[0]]

        # ── AI SCORE (batched, 1 call per 20 jobs) ──
        scored = await self.ai_filter.score_batch(passed)
        to_apply = sorted(
            [j for j in scored if j["ai_score"] >= 7],
            key=lambda j: j["ai_score"], reverse=True
        )

        # ── APPLY (fast code path, AI only on errors) ──
        for job in to_apply:
            ats = detect_ats(job["apply_url"])
            confidence = self.learner.get_confidence(ats)

            if confidence >= 0.8:
                # HIGH CONFIDENCE: Run code, AI only if it crashes
                applicator = self.applicators.get(ats, self.applicators["unknown"])
                result = await applicator.apply(job)

                if result.status == "failed" and confidence < 0.95:
                    # Let AI try to recover
                    result = await self.supervisor.handle_and_retry(job, result)
            else:
                # LOW CONFIDENCE: AI supervises every step
                result = await self.applicators["unknown"].apply(job)

            # ── LEARN from this application ──
            await self.learner.learn_from_application(job, result, ...)

            # ── NOTIFY ──
            if result.status == "submitted":
                await self.notifier.send_photo(result.screenshot_path,
                    f"✅ {job['title']} @ {job['company']} ({result.duration_seconds:.0f}s)")

        # ── CYCLE SUMMARY ──
        await self.notifier.send(
            f"📊 Cycle: {len(all_jobs)} scraped → {len(to_apply)} applied → "
            f"{submitted} submitted ({submitted/(elapsed/3600):.0f}/hr)"
        )
```

---

## THE LEARNING CURVE

```
Applications 1-5:     AI drives 90% of actions. Code handles basic HTTP scraping.
                       System is slow (~60s/app) but learning fast.
                       Playbooks and field_map start building.

Applications 5-20:    AI drives 50%. Code handles Greenhouse, Lever (most common).
                       AI still needed for dropdowns and custom questions.
                       ~30-40s/app.

Applications 20-50:   AI drives 20%. Code handles 4-5 ATS platforms confidently.
                       field_map.json has 100+ entries.
                       AI only called for truly new fields.
                       ~20-30s/app.

Applications 50-100:  AI drives 5%. Code handles everything on known platforms.
                       AI only called for: new ATS platforms, novel custom questions.
                       ~15-20s/app. 50+ apps/hour achieved.

Applications 100+:    PRODUCTION READY.
                       The codebase + knowledge base is a complete product.
                       Works for any user — just swap profile.yaml.
                       Ready to sell commercially.
```

---

## COMMERCIAL PRODUCT FEATURES (for selling)

1. **One-file setup** — User fills profile.yaml, system handles everything else
2. **Multi-ATS support** — Greenhouse, Lever, Ashby, Workday, SmartRecruiters, iCIMS, Taleo, and auto-learns new ones
3. **AI-powered scoring** — Ranks jobs by relevance before applying
4. **Active learning** — Gets smarter with every application
5. **Self-healing** — AI patches code when forms change
6. **Telegram dashboard** — Real-time notifications with screenshots
7. **Application analytics** — SQLite database with full history, success rates, platform stats
8. **Resume routing** — Different resumes for different role types
9. **Cover letter generation** — Tailored per company using AI
10. **Email verification** — Handles Greenhouse security codes, Workday OTPs automatically
11. **Rate limiting** — Smart throttling per platform to avoid blocks
12. **Dedup** — Never applies to the same job twice

---

## API COSTS (per 100 applications)

| AI Task | Calls | Model | Cost |
|---|---|---|---|
| Job scoring (batches of 20) | 5 calls | Groq Llama 4 | $0.01 |
| Cover letter generation | 50 calls | Groq Llama 4 | $0.05 |
| Unknown field answers | ~20 calls | Groq Llama 4 | $0.02 |
| Code generation (new ATS) | ~3 calls | Claude/GPT-4o | $0.30 |
| Error diagnosis + patches | ~10 calls | Claude/GPT-4o | $0.50 |
| **TOTAL for 100 apps** | | | **~$0.88** |

Less than $1 for 100 applications. At 50 apps/hour, that's $0.44/hour in AI costs.

---

## GETTING STARTED

1. `pip install playwright httpx aiosqlite pyyaml openai`
2. `playwright install chromium`
3. Fill out `config/profile.yaml` with your details
4. Add API keys to `config/settings.yaml` (OpenAI/Anthropic + Groq + Telegram)
5. `python main.py`
6. Watch it learn. After 100 applications, you have a production-ready product.

---

## IMPORTANT HARD-WON KNOWLEDGE (from 50+ real applications)

Bake ALL of this into the initial playbooks so the system doesn't have to re-learn it:

### Greenhouse (60% of tech jobs)
- Comboboxes are ARIA widgets, NOT `<select>`. Click to open → find option → click option. Options are dynamically created.
- "{city}, TX" returns zero autocomplete results. Always search "Dallas".
- `page.set_input_files()` for resume — NEVER click the Attach button (opens native dialog, hangs browser).
- Email verification: 8-char code from `no-reply@us.greenhouse-mail.io`. One char per input box.
- reCAPTCHA is invisible — usually passes, but blocks at high volume.
- Some companies (Stripe, Datadog) trigger email verification after submit.
- EEO section uses native `<select>` elements (unlike the rest of the form which uses ARIA).
- Country dropdown: always set to "United States" — forms fail validation without it.
- Phone country code: some forms need explicit "United States +1" selection first.

### Lever (simplest ATS)
- Single page, all fields visible, no comboboxes, no multi-step.
- "Full Name" is ONE field (not first/last separate). Fill with "{full_name}".
- Work authorization uses radio buttons, not dropdowns.
- No location autocomplete — plain text field.
- Apply URL: `https://jobs.lever.co/{company}/{job_id}/apply`
- Confirmation: "Application submitted!" text.

### Ashby
- Location: must press Enter after typing to commit. Just typing doesn't register.
- Resume upload: target `#_systemfield_resume` specifically (generic file input may be wrong).
- Silent anti-bot: submit does nothing (no error, no success). No workaround — skip and move on.
- "We're updating your application" warning after upload — wait and retry submit.

### Workday (most complex)
- 6-step wizard: Sign In → My Info → My Experience → Questions → Disclosures → Self ID → Review
- Accounts are GLOBAL — one email+password works across ALL Workday companies.
- HONEYPOT FIELD: "Enter website. This input is for robots only" — NEVER fill.
- "How did you hear" is a TWO-LEVEL multi-select: Level 1 = "Job Board", Level 2 = "LinkedIn Jobs".
- Date fields: use Calendar picker button, not the spinbutton inputs.
- Password requirements: uppercase, special char, number, lowercase, min 8 chars.
- Radio buttons may lose refs after DOM re-renders — use JS fallback.

### SmartRecruiters
- Has "Confirm your email" field — MUST fill email twice.
- City uses autocomplete combobox (same as Greenhouse location).
- May be multi-page: page 1 = personal info, page 2 = screening questions.
- Direct form URL: `https://jobs.smartrecruiters.com/oneclick-ui/company/{Company}/publication/{uuid}`

### General
- DOM changes after ANY interaction — always re-query selectors.
- `page.set_input_files()` is atomic and safe. `page.click()` on file inputs opens native dialogs.
- Post-submit: Greenhouse shows "Thank you" or blank (both = success). Lever shows "Application submitted!". Ashby may show nothing (anti-bot).
- Senior at FAANG = 5-8 years → skip. Senior at startups = 3-5 years → OK.
- Defense companies (Anduril, Palantir, Lockheed, etc.) require security clearance — international students can never qualify.
- Staffing companies (Wipro, Infosys, TCS, etc.) post spam listings — always skip.
