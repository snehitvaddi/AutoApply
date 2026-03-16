# Learnings - Job Bot

This file is updated after every application session. Read it BEFORE each application.

**Related guides:**
- [LinkedIn Voyager API](./linkedin-voyager-api.md) — endpoints, headers, 3-stage pipeline
- [Email Services](./email-services.md) — AgentMail, Gmail/Himalaya, Gmail OAuth, ATS API scouting

---

## SPEED OPTIMIZATION (CRITICAL — read first)

### Efficient Snapshots
- ALWAYS: `browser snapshot --efficient --interactive` (60-90% fewer tokens, only interactive elements)
- NEVER: bare `browser snapshot` (returns 500+ nodes, wastes tokens and time)
- Max 2 snapshots per application: one after load, one before submit

### Fast Page Waits
- Use `browser wait --load networkidle --timeout-ms 5000` instead of fixed delays
- Faster on fast pages, still safe on slow ones

### JS Evaluate for Dropdowns (skip click→snapshot→click)
- Situation: Each dropdown required 3 browser calls (click→snapshot→click) = 6-10 seconds each
- Action: Use `browser evaluate --fn '...'` to set dropdown values via JavaScript in ONE call
- Result: ALL EEO dropdowns filled in 1 command instead of 12+ commands. Saves ~30 seconds per app.
- For native `<select>`: use `browser select <ref> "value"` (also ONE command)
- Only fall back to click→snapshot→click for ARIA comboboxes that resist JS

### Greenhouse Phone Country Dropdown (MUST FIX BEFORE PHONE FIELD)
- Situation: Greenhouse has a country code dropdown BEFORE the phone number field. If you don't select "United States" first, phone number won't save and submit fails.
- Action: BEFORE filling the phone textbox, select "United States" in the country code dropdown. Try `browser select` or `browser click` → snapshot → click "United States" option. JS fallback: query for `select[name*="country"]` and set value.
- Result: Phone number saves correctly, submit succeeds.
- **This is a MANDATORY step on ALL Greenhouse forms with a phone field.**

### Pre-Filter Before Browser (saves minutes per session)
- Situation: Agent was opening every scraped job in browser, then filtering — wasting 5-10s per irrelevant job
- Action: Filter on scraped data FIRST (title, company, seniority, location, applicants) before opening browser
- Result: Only relevant jobs get opened. If 50 scraped → 12 pass filter, saves ~3 minutes of browser loading

---

## Temporary Company Pause (CRITICAL)

- **DO NOT apply to Stripe for one month**: from **2026-02-25** through **2026-03-25**.
- While paused, skip Stripe jobs during both scout ranking and apply execution.
- Resume Stripe applications only after 2026-03-25 unless user overrides.
- **DO NOT apply to Ramp for 100 days**: from **2026-03-01** through **2026-06-09**.
- While paused, skip Ramp jobs during both scout ranking and apply execution.
- Resume Ramp applications only after 2026-06-09 unless user overrides.

## Shady / Low-Quality Sites — SKIP ENTIRELY

- **Wiraa** — shady job aggregator, fake-looking listings
- **BestJobTool** — low-quality redirector
- **Jobright.ai** — aggregator, not a real employer
- **Hirenza** — staffing spam
- If a job's `apply_url` goes to any of these domains, SKIP. Don't waste time.

## Defense / Security Clearance Exclusion (CRITICAL)

Owner is an international student on H-1B visa. NEVER apply to:
- **Anduril** — defense/military, requires US citizenship for most roles
- **Palantir** — many roles require security clearance
- **Lockheed Martin, Raytheon, Northrop Grumman, General Dynamics, L3Harris** — defense contractors
- Any role mentioning "security clearance", "TS/SCI", "Secret clearance", "US citizen only"
- Any role at defense/intelligence companies (DoD, NSA, CIA contractors)
- Government-only roles (e.g., "Public Sector" at defense companies)

**At scout time:** Skip these companies entirely — do NOT even queue them for apply.
**At apply time:** If JD mentions clearance or citizenship requirement, SKIP immediately.

## Seniority Filter (CRITICAL)

Owner has ~3 years experience. NEVER apply to:
- Staff, Staff+, Lead, Principal, Distinguished, Fellow
- Director, VP, Head of, Chief, Manager
- Any role requiring 5+ years
- Senior roles at FAANG/big tech (Google, Meta, Amazon, Apple, Microsoft, Netflix, NVIDIA, Uber, Airbnb, Stripe, etc.)

Senior roles: ONLY at startups/small companies if JD says 2-4 years required.
At FAANG/big tech, "Senior" = 5-8 years → ALWAYS SKIP.

## Location Filter (CRITICAL)

- US-targeted pipeline only: apply to roles in `United States` / `US` / `USA` / `Remote (US)`.
- Skip non-US roles at scout time (e.g., Paris, Seoul, London, Zurich) to avoid wasting apply cycles.
- For ambiguous location text, open JD and confirm country before queueing.

## Role Relevance Filter (UPDATED 2026-02-27 — AI/ML/DATA FOCUSED)

APPLY to these role families:
- AI Engineer, ML Engineer, MLOps Engineer, Applied Scientist, GenAI Engineer, LLM Engineer
- Data Scientist, Data Engineer, Analytics Engineer
- Research Engineer (AI/ML), NLP Engineer, Computer Vision Engineer
- Software Engineer — ONLY if title or JD mentions AI, ML, data, or Python-heavy work
- Platform Engineer (ML infra only)

DO NOT APPLY to:
- Generic "Backend Engineer" or "Software Engineer" with no AI/ML/data signal
- Frontend-only (React/CSS/UI), Mobile-only (iOS/Android), QA/SDET
- Crypto/blockchain, Tax/finance/accounting software
- Sales Engineer, Solutions Architect, TAM (customer-facing)
- DevOps/SRE (unless ML infrastructure), Cloud Engineer (unless ML-adjacent)
- Recruiter, PM, Marketing

---

## ⚠️ MANDATORY: Batch Fill — `browser fill --fields` (NEVER fill one at a time)

**YOU MUST USE `browser fill --fields` FOR ALL TEXT FIELDS. NO EXCEPTIONS.**

❌ NEVER use `browser type` per field — wastes 10x the time and tokens
❌ NEVER use JS `evaluate` / `document.querySelector` to set input values
❌ NEVER use `browser act` with individual field-setting JS

✅ ONE snapshot → ONE `browser fill --fields '[...]'` → ALL text fields filled instantly

**CRITICAL: Each field object MUST include `"type":"textbox"` — without it, fill errors with "must include ref and type".**

```
browser fill --fields '[
  {"ref":"<first_name_ref>","type":"textbox","value":"{first_name}"},
  {"ref":"<last_name_ref>","type":"textbox","value":"{last_name}"},
  {"ref":"<preferred_name_ref>","type":"textbox","value":"{first_name}"},
  {"ref":"<email_ref>","type":"textbox","value":"{email}"},
  {"ref":"<phone_ref>","type":"textbox","value":"{phone}"},
  {"ref":"<linkedin_ref>","type":"textbox","value":"{linkedin_url}"},
  {"ref":"<github_ref>","type":"textbox","value":"{github_url}"},
  {"ref":"<website_ref>","type":"textbox","value":"{github_url}"},
  {"ref":"<company_ref>","type":"textbox","value":"{current_company}"},
  {"ref":"<title_ref>","type":"textbox","value":"AI Engineer"}
]'
```
**Verified working on Greenhouse form 2026-02-26: filled 7 fields in 1 command.**

**Field values (memorize these — don't re-read PROFILE.md each time):**
- First Name: `{first_name}`
- Last Name: `{last_name}`
- Preferred Name: `{first_name}`
- Email: `{email}`
- Phone: `{phone}`
- LinkedIn: `{linkedin_url}`
- GitHub: `{github_url}`
- Website/Portfolio: `{github_url}`
- Current Company: `{current_company}`
- Current Title: `AI Engineer`

**Workflow:**
1. ONE `browser snapshot` → read ALL field refs
2. Map refs to values (see list above — these are FIXED, no LLM reasoning needed)
3. ONE `browser fill --fields '[...]'` → fills everything instantly
4. Then handle dropdowns/comboboxes individually (click→snapshot→click)
5. Then upload resume with `browser upload`

---

## Resume Upload (CRITICAL — NEVER BREAK)

**Problem:** Clicking "Attach" opens a native file dialog that OpenClaw browser cannot interact with.
**Solution:** Use the ONE-STEP upload command:
```
browser upload /tmp/openclaw/uploads/resume.pdf --ref <attach_button_ref>
```
- ✅ This arms the file interceptor AND clicks the button in one atomic operation
- ❌ NEVER `browser click <attach_ref>` — opens Finder dialog, HANGS the browser
- ❌ NEVER click then upload separately — race condition
- MUST pre-stage resume: `exec cp "{HOME}/Downloads/MS_All_Docs/{full_name} GenAI Resume.pdf" /tmp/openclaw/uploads/resume.pdf`
- After upload, snapshot will show `resume.pdf` text and a "Remove file" button
- If TWO Attach buttons exist (Resume + Cover Letter), use the FIRST one for resume

**NEVER DO:**
- `browser click <attach_ref>` without arming upload first — opens native dialog, hangs
- `browser upload <path>` then separately `browser click <ref>` — race condition, unreliable

---

## Greenhouse Combobox (SOLVED)

**Problem:** Typing into a combobox doesn't select the value. The form still sees it as empty.
**Solution:** click → snapshot → click pattern:
1. `browser click <combobox_ref>` — opens dropdown
2. `browser snapshot` — find option refs (they are DYNAMIC, change every open)
3. `browser click <option_ref>` — actually selects the value
- Wait 0.3-1s between steps
- After selecting, the combobox input may LOOK empty — this is normal Greenhouse behavior
- To verify: look for log text like "X selected" or check the option has aria-selected

---

## Location Autocomplete (SOLVED)

**Problem:** "{city}, TX" returns no autocomplete results on Greenhouse.
**Solution:** Type "Dallas" instead → select "Dallas, Texas, United States" from dropdown.
- Click the location combobox first
- Clear any existing text: `press Control+a` then `press Backspace`
- Type "Dallas"
- Wait 2 seconds for autocomplete
- Snapshot, find "Dallas, Texas" option, click it

---

## Country Dropdown (LEARNED)

Some Greenhouse forms have a separate "Country" dropdown (not combobox).
- Look for `combobox "Country"` or `select "Country"` in snapshot
- If combobox: click → snapshot → click "United States"
- If native select: `browser select <ref> "United States"`
- ALWAYS fill this — forms fail validation without it

---

## Anthropic Forms (KNOWN ISSUE)

Anthropic's Greenhouse board at `boards.greenhouse.io/anthropic/` does NOT load the embedded form properly.
- All 4 attempts resulted in "no fields found" and "no submit button"
- Status: SKIP Anthropic jobs until we find the correct embed URL structure
- Their career page may require authentication or use a custom application flow

---

## Post-Submit Behavior

- **Airbnb:** Shows "Thank you for applying" confirmation page with Airbnb logo
- **Stripe:** Page redirects to blank white page (same as successful submit)
- **Scale AI, Brex:** Page goes blank after submit (likely successful)
- **General pattern:** Greenhouse forms either show a "Thank you" page OR redirect to blank
- Take screenshot IMMEDIATELY after submit (within 3-5 seconds) before redirect

---

## Screenshot Quality

- ALWAYS use `--type png` for crisp screenshots (default jpg is blurry)
- Use `--full-page` to capture the entire form, not just viewport
- Command: `browser screenshot --full-page --type png`

---

## Website Field

- Fill with: `{github_url}` (NOT resume2portfolio.com)
- This was a bug in early PROFILE.md — now fixed

---

## Cloudflare Greenhouse Variant (NEW)

- Some Cloudflare Greenhouse forms (example: `gh_jid=6885717`) may show selected values in dropdown UI but still fail validation with `This field is required`.
- In this variant, required comboboxes for:
  - `Are you interested in working to increase user adoption...` 
  - `Do you now or will you in the future require immigration sponsorship...`
  can appear selected yet remain invalid until exact option click is registered from the open listbox.
- Resume upload can also fail silently (`Resume/CV is required`) even when `#resume` file input is set. If this happens, retry using the exact resume attach control with atomic upload and verify visible filename before submit.

## Platform-Specific Notes

### Greenhouse
- Most common ATS for tech companies
- Embed URL: `https://job-boards.greenhouse.io/embed/job_app?for={company}&token={job_id}`
- Has invisible reCAPTCHA Enterprise — usually passes silently, but may block
- Comboboxes are ARIA widgets, not native selects
- Resume upload via file input interceptor

### Lever (DOCUMENTED)

**URL patterns:**
- Job listing: `https://jobs.lever.co/{company}/{job_id}`
- Apply form: `https://jobs.lever.co/{company}/{job_id}/apply` ← use this directly
- Many companies have migrated OFF Lever (OpenAI, Anyscale → Ashby). Always check if board is live first.

**Form structure (single page, simple):**
Lever forms are the SIMPLEST of all ATS platforms. All fields on one page, no comboboxes, no multi-step.

- **Resume/CV** ✱ — "ATTACH RESUME/CV" button
  - Upload: `browser upload /tmp/openclaw/uploads/resume.pdf --ref <attach_button_ref>`
  - The attach button has a nested structure: `link > button`. Target the **button** ref.
- **Full name** ✱ (textbox) — NOT first/last separate! Type "{full_name}" as one string
- **Email** ✱ (textbox)
- **Phone** (textbox)
- **Current location** (textbox) — plain text, no autocomplete. Type "{city}, TX" or "Dallas, TX"
- **Current company** (textbox) — Type "{current_company}"

**Links section:**
- LinkedIn URL (textbox)
- Twitter URL (textbox)
- GitHub URL (textbox)
- Portfolio URL (textbox)
- Other website (textbox)

**Custom questions (vary per company):**
- Work authorization: **radio buttons** (Yes/No), NOT comboboxes
  - "Legally authorized to work in US?" → click "Yes" radio ref
  - "Require sponsorship?" → click "Yes" radio ref
  - Free-text follow up for visa details
- May have file upload fields (transcripts, etc.)
- May have text fields (graduation date, etc.)

**Additional information:**
- Large textbox for cover letter ("Add a cover letter or anything else you want to share")

**Submit:** "Submit application" button — single click, no multi-page

**Key differences from Greenhouse:**
1. **Full name is ONE field** — not separate first/last. Type "{full_name}"
2. **No comboboxes** — all dropdowns are radio buttons or plain textboxes
3. **No EEO section** on the apply page (may come via email after)
4. **No location autocomplete** — just a plain text field
5. **Simpler resume upload** — same `browser upload --ref` pattern works
6. **Single page** — everything visible, no "Next" button, straight to "Submit application"
7. **Custom questions use radio buttons** — click the radio ref directly, no dropdown dance

**How to apply:**
1. Upload resume: `browser upload /tmp/openclaw/uploads/resume.pdf --ref <attach_button_ref>`
2. Type full name: "{full_name}" (one field)
3. Type email, phone, location ("Dallas, TX"), current company ("{current_company}")
4. Fill links: LinkedIn, GitHub
5. Handle custom questions (radio buttons for work auth, text fields for details)
6. Fill additional info (cover letter text)
7. Screenshot → Click "Submit application" → Screenshot

**Live validation (2026-02-25):**
- Successfully submitted on Lever for Voleon `Data Scientist (USA-Remote)`.
- Confirmation text: `Application submitted!`
- Resume upload succeeded via attach control ref (`Resume/CV ✱`).

**Companies still on Lever (as of Feb 2026):**
Voleon Group, Nominal, Level AI, FieldAI, NimbleRx, WeRide.ai — mostly smaller companies/startups

### Ashby
- URL pattern: `https://jobs.ashbyhq.com/{company}/{job_id}`
- Application tab URL often becomes: `/{company}/{job_id}/application`

**Ashby required-field pitfalls (SOLVED):**
1. **Location can look filled but still fail validation**
   - Problem: Typing location text is not enough; Ashby may not accept it as a selected value.
   - Fix: click location combobox -> type full location -> press Enter to commit selection.

2. **Resume upload can target wrong file input**
   - Problem: Generic `input[type='file']` may upload to non-required autofill input, while required Resume remains empty.
   - Fix: Upload to the required resume field directly:
   `selector: input#_systemfield_resume`
   Then verify with evaluate/files check before submit.

3. **Always verify required upload binding before submit**
   - Use evaluate check:
   - `document.querySelector('#_systemfield_resume').files.length === 1`
   - and filename exists (e.g., `resume.pdf`)

4. **If submit fails, read top alert and correct exactly those fields**
   - Ashby shows an alert like "Your form needs corrections" with explicit missing fields.
   - Refill only missing required fields, then resubmit.

5. **Possible silent anti-bot block (no-op submit)**
   - Symptom: Submit button remains clickable, but clicking it does nothing (no confirmation page, no field errors).
   - Usually appears with reCAPTCHA/anti-bot checks on some Ashby forms.
   - Verify all required inputs are complete and resume is attached; if still no-op after retries, classify as `blocked` and send Telegram escalation with screenshots.

6. **Ashby transient upload-lock warning**
   - Warning text: "We're updating your application (e.g. uploading files), please try again when they're finished."
   - If this appears after upload, wait and re-attempt submit only after upload settles.
   - **CRITICAL FIX**: Wait **45+ seconds** after resume upload before clicking submit. Shorter waits (10-20s) cause the warning to reappear on submit.
   - If warning appears, dismiss it (click the close button via JS), delete the file, wait for warning to clear, re-upload, wait 45s, then submit.
   - **Use `type` instead of `fill`** for Ashby text fields — `fill` sets DOM values without triggering React events, causing all fields to show as `aria-invalid=true` on submit.
   - If warning disappears but submit still no-ops with no validation errors, treat as anti-bot/reCAPTCHA block.

### SmartRecruiters (DOCUMENTED)

**Two URL formats:**
1. Job listing page: `https://jobs.smartrecruiters.com/{Company}/{job_id}-{slug}`
   - Shows job description with an "Apply" button
   - Some companies redirect to their own career portal (e.g., Bosch → jobs.bosch.com)
   - NOTE: `jobs.smartrecruiters.com` may show maintenance page even when status page says operational
2. One-click apply form: `https://jobs.smartrecruiters.com/oneclick-ui/company/{Company}/publication/{uuid}?dcr_ci={Company}`
   - This is the DIRECT application form — use this for auto-filling
   - **This URL format bypasses maintenance pages and custom portals**

**Form structure (one-click apply):**
- **Auto-fill options at top:** "Apply With LinkedIn", "Apply With Indeed", "Apply with SEEK"
  - Also has a resume drop zone at top that can auto-parse profile
- **Personal Information section:**
  - First name* (textbox)
  - Last name* (textbox)
  - Email* (textbox)
  - Confirm your email* (textbox) ← UNIQUE TO SMARTRECRUITERS — must type email twice
  - City (combobox with autocomplete)
  - Phone number (textbox, with country code button defaulting to +1 US)
- **Experience section:**
  - "Add" button to add work experience entries (optional usually)
- **Education section:**
  - "Add" button to add education entries (optional usually)
- **Your Profiles section:**
  - LinkedIn (textbox)
  - Facebook (textbox)
  - X/Twitter (textbox)
  - Website (textbox)
- **Resume section:**
  - "Choose a file or drop it here" button (10MB limit)
  - Upload uses same file-chooser interceptor pattern
  - Command: `browser upload /tmp/openclaw/uploads/resume.pdf --ref <choose_file_ref>`
- **Message to Hiring Team:**
  - Large textbox for cover letter / intro message
- **Submit:** "Next" button (may lead to additional screening questions on page 2)

**Key differences from Greenhouse:**
1. Has "Confirm your email" field — MUST fill both email fields
2. City uses autocomplete combobox (similar to Greenhouse location)
3. Resume upload is a separate section at bottom (not inline with personal info)
4. May have multi-page flow (page 1 = personal info, page 2 = screening questions)
5. No EEO section on page 1 — may appear on page 2
6. Experience/Education are expandable sections with "Add" buttons, not pre-filled fields

**How to apply:**
1. Fill personal info: First name → Last name → Email → Confirm email → City → Phone
2. Fill profiles: LinkedIn → Website (GitHub)
3. Upload resume: `browser upload /tmp/openclaw/uploads/resume.pdf --ref <choose_file_ref>`
4. Fill message to hiring team (use cover letter template)
5. Click "Next" → handle page 2 screening questions if any
6. Screenshot → Submit → Screenshot

### Workday (DOCUMENTED — NO LONGER SKIP)

**URL pattern:** `https://{company}.wd{N}.myworkdayjobs.com/{site}/job/{location}/{title}_{job_id}`
- N is usually 1-5 (e.g., `wd5` for NVIDIA)
- Apply URL: append `/apply/applyManually` to job URL

**Application is a 7-step wizard:**
1. **Create Account/Sign In** — requires email + password account
2. **My Information** — personal details
3. **My Experience** — work history
4. **Application Questions** — custom questions
5. **Voluntary Disclosures** — EEO
6. **Self Identify** — disability/veteran
7. **Review** — final review + submit

**Step 1: Account Creation / Sign In (MULTI-USER SaaS FLOW):**
- "Sign in with Google" button (easiest if Google is logged in on browser)
- "Sign in with email" → shows Email + Password login
- "Create Account" → Email + Password (with requirements) + Verify Password + "I agree" checkbox
- Password requirements: uppercase, special char, number, lowercase, min 8 chars, alphabetic
- Has honeypot field ("Enter website. This input is for robots only") — NEVER fill this
- Workday accounts are GLOBAL — one account works across ALL Workday companies

**CRITICAL: Account-Already-Exists Flow (common for returning users):**
1. Try "Create Account" with user's email + generated password
2. If error "account already exists" appears → click "Forgot your password?"
3. Workday sends reset email from `{company}@otp.workday.com` within 10 seconds
4. Read reset email via Gmail OAuth (user must have Gmail connected)
5. Extract reset link: `https://{company}.wd{N}.myworkdayjobs.com/{site}/passwordreset/{token}/?redirect=...&username=...`
6. Navigate to reset link → set new password → sign in
7. After sign-in → goes directly to "My Information" (account step is skipped)

**Password generation for each user:**
- Generate per-user Workday password: `{FirstInitial}{LastInitial}{RandomDigits}@{Year}App!`
- Store encrypted in `user_profiles.workday_password_encrypted` (same AES-256-CBC as Gmail tokens)
- Reuse across ALL Workday companies (global account)

**Gmail email reading for verification (via Gmail OAuth API):**
- Search: `from:otp.workday.com newer_than:5m`
- Extract reset link from email body
- Navigate to link in browser, complete reset
- Then sign in and continue application

**After sign-in, the wizard has 6 steps (account step is removed):**
1. My Information — "How Did You Hear About Us?", "Previously worked here?", etc.
2. My Experience — work history
3. Application Questions — company-specific
4. Voluntary Disclosures — EEO
5. Self Identify — disability/veteran
6. Review — final submit

**Companies on Workday:** NVIDIA, Google, Amazon, Meta, Apple, Microsoft, Uber, Netflix, Salesforce, Adobe, Intel, Qualcomm, AMD, IBM, Oracle, SAP, Cisco, VMware, Dell, HP

**Key differences from Greenhouse:**
1. **Requires account creation** — email + password, one-time per company
2. **Multi-step wizard** (6 steps after login) vs Greenhouse's single-page
3. **Has "Autofill with Resume" option** on some — may parse resume automatically
4. **Resume upload** uses "Select files" button with `browser upload --ref` pattern (same as Greenhouse)
5. **Standard Attach button** also exists — use same `browser upload --ref` pattern

**WORKDAY FORM-FILLING SPECIFICS (PROVEN 2026-02-24 on NVIDIA):**

**"How Did You Hear About Us?" — TWO-LEVEL MULTI-SELECT:**
1. Click the combobox (the `generic` container, NOT the textbox)
2. Options appear: Associations, Event/Conference, Job Board, Social Media, University, Website
3. Click "Job Board" option → it gets selected as a chip/tag
4. A SUB-DROPDOWN appears with specific job boards: 104 Job Bank, Indeed, Glassdoor, LinkedIn Jobs, etc.
5. Click "Linkedin Jobs" in the sub-dropdown
6. Click outside to close → should show "1 item selected, Linkedin Jobs"
- **KEY GOTCHA:** Clicking the option's inner `generic` element doesn't register! Must use keyboard (ArrowDown + Enter) or click the `option` element directly
- If first click doesn't register, use: click combobox → ArrowDown to navigate → Enter to select

**Date fields (Self Identify step):**
- Spinbutton elements (Month/Day/Year) are NOT directly clickable
- Use the Calendar button → opens calendar popup → click today's date
- Today button has text like "Selected Today Tuesday 24 February 2026"

**Radio buttons:**
- May lose refs after page interactions (DOM re-render)
- If `browser click <ref>` fails, use `browser evaluate` with JS: `document.querySelectorAll('input[type=radio]')[index].click()`

**Veteran status options (Self Identify):**
- "I IDENTIFY AS ONE OR MORE OF THE CLASSIFICATIONS OF PROTECTED VETERANS LISTED ABOVE"
- "I IDENTIFY AS A VETERAN, JUST NOT A PROTECTED VETERAN"
- "I AM NOT A VETERAN"
- "I DO NOT WISH TO SELF-IDENTIFY"
→ Select "I AM NOT A VETERAN"

**Disability options (Self Identify):**
- Checkboxes (not radio): "Yes, I have a disability", "No, I do not have a disability", "I do not want to answer"
→ Select "No, I do not have a disability and have not had one in the past"

**Terms and Conditions (Voluntary Disclosures):**
- Checkbox: "By selecting the checkbox, you agree to our Terms and Conditions and Applicant Privacy Policy."
→ Click to check

**Ethnicity options:** Asian (Not Hispanic or Latino), Black or African American, etc.
**Gender options:** Male, Female, Decline to Self Identify

**Resume upload on Step 2 (My Experience):**
- "Select files" button under Resume/CV section
- `browser upload /tmp/openclaw/uploads/resume.pdf --ref <select_files_ref>`
- Shows "Successfully Uploaded!" after 2-3 seconds

**Websites section on Step 2:**
- Click "Add" → URL field appears → type GitHub URL
- LinkedIn profile has its own dedicated field: "Please provide a link to your LinkedIn profile:"

---

## Platform Migration Tracking (IMPORTANT)

**File:** `memory/platform-migrations.json`

When scouting, companies frequently move between ATS platforms. Track ALL migrations:
- **Anyscale:** Lever → Ashby (`jobs.ashbyhq.com/anyscale`) — discovered 2026-02-24
- **OpenAI:** Lever → unknown (404, no redirect) — discovered 2026-02-24

**How to detect migrations:**
1. Page shows "We have moved our Careers Page to: {url}" → record the new URL and platform
2. Page returns 404 → record as migrated to "unknown"
3. Page redirects to a different domain → record the new platform
4. Google search reveals new career page → update with the correct URL

**What to do:**
1. Update `memory/platform-migrations.json` with the migration
2. Add company to the new platform's search list in SOUL.md
3. Remove company from the old platform's list
4. Search the new platform immediately in the same session

This is how we expand coverage automatically — every dead link is a lead to the right place.

---

## Gmail / Email Verification (SETUP COMPLETE)

**Gmail IMAP is connected via `himalaya` CLI.**
- Account: `{email}`
- Config: `{HOME}/Library/Application Support/himalaya/config.toml`

**Read recent emails:**
```
exec himalaya envelope list --account gmail --folder INBOX --page-size 5 -o json
```

**Read email body by ID:**
```
exec himalaya message read --account gmail --folder INBOX {id}
```

**Check spam folder:**
```
exec himalaya envelope list --account gmail --folder "[Gmail]/Spam" --page-size 5
```

**Use case:** When Workday/iCIMS/Taleo requires account creation + email verification:
1. Create account on ATS → they send verification email
2. Wait 10-15s → list recent emails → find the one from the ATS
3. Read the email body → extract OTP code or verification link
4. Enter OTP or open verification link in browser
5. Continue application

---

## Gateway/Browser Drop Recovery (CRITICAL)

- Symptom: browser actions time out / "Can't reach browser control service" mid-application.
- Immediate fix sequence:
  1. `openclaw gateway status`
  2. `openclaw gateway start` (or `openclaw gateway restart`)
  3. Re-open the same application URL and resume from last completed step
  4. Send Telegram delay/recovery update
- Do this automatically without asking.

## Ref Instability

- DOM refs (e1, e2, etc.) change whenever the page updates
- ALWAYS re-snapshot before interacting with a new element
- Never cache refs across interactions — they go stale
- After filling a combobox, all subsequent refs may shift

---

## Rate Target

- **TARGET: 50+ apps/hour. No artificial delays between applications.**
- Move to next job IMMEDIATELY after submit — zero idle time
- 0.3s pause between individual form interactions is fine (DOM needs time to react)
- If Greenhouse starts blocking (reCAPTCHA fails), back off to 1 app/minute on that platform only, then switch to another ATS

---

## Brex Greenhouse Specifics (2026-02-24)

- Brex application for job_id `8434385002` required **Phone Country** explicitly; submit failed until `Country = United States +1` was selected.
- This role's country question offered only `{Brazil, Canada, USA, Netherlands, United Kingdom, Other}`; used `USA` from profile.
- Brex confirmation page showed explicit success message: **"Thank you for applying."** (not blank redirect).
- CLI note: `openclaw browser screenshot --type png` still produced `.jpg` output path in this environment; keep using `--full-page` and verify returned media path.
- Brex role `8318331002` (Software Engineer II, Product) adds required skill-gate dropdowns: **3+ years professional experience** and **backend programming language experience**. Both must be explicitly set to `Yes` along with in-office acknowledgement + relocation dropdowns.
- Brex role `8318332002` reuses the same Software Engineer II form template; prior ref map/answer pattern is reusable across location variants (still re-snapshot each dropdown because option refs are dynamic).
- Brex role `8318333002` also uses this exact template; fill sequence is identical (`LinkedIn`, `Yes/Consent/Yes/Yes`, `USA`, in-office `relocate` + `plan to relocate`, then EEO selections).

---

## Stripe Greenhouse Specifics (2026-02-24)

- Stripe form (job_id `7369543`) includes **many required structured questions** beyond basics:
  - Current residence country (dropdown)
  - Anticipated working countries (checkbox list)
  - Work authorization (dropdown)
  - Sponsorship need (dropdown)
  - Remote intention (dropdown)
  - Prior Stripe employment (dropdown)
  - WhatsApp opt-in (dropdown)
  - BrightHire consent (dropdown)
- For anticipated working countries, explicitly checking **US** is required.
- On submit, button may become temporarily disabled while processing/reCAPTCHA runs; wait ~5-10s before deciding failure.
- This Stripe application showed a full **"Thank you for applying."** confirmation page (not blank redirect).
- Stripe has multiple Greenhouse form variants by role. For job_id `7646513` (AI Solutions Developer, Finance), required fields were simpler than the earlier engineering variant and included:
  - Current/previous employer (text)
  - Current/previous title (text)
  - Most recent degree (text)
  - Voluntary demographic dropdowns (Gender, Hispanic/Latino, Veteran, Disability)
  - No Stripe-specific work authorization/sponsorship custom question block on this variant.
- Stripe job_id `7550154` (Android Engineer, Terminal Developer Productivity) used the **full** variant: country of residence + anticipated working countries (checkbox), authorization/sponsorship/remote/prior-employment dropdowns, employer/title/school/degree text fields, WhatsApp opt-in, plus voluntary demographic fields. Using `US` checkbox + `No, office location` for remote question submitted successfully.
- Stripe job_id `6176758` (Backend/API Engineer, Money as a Service) adds a required free-text question: **"If located in the US, in what city and state do you reside?"** (filled with `Dallas, TX`) and a required years-of-experience dropdown. Successful selection used `1 - 4 years of experience as a software engineer`.
- Stripe job_id `6176763` (Backend/API Engineer, Money as a Service - Canada) uses a close variant but includes a required **remote-intent dropdown** and required **BrightHire consent** dropdown (`Yes/No`) instead of the long EEO section in-form. Successful path used `No, I intend to work from an office location.` + `BrightHire = Yes`.

---

## Brex Intern Form Specifics (2026-02-24)

- Brex intern form (job_id `8434389002`) adds two required in-office eligibility dropdowns:
  - Acknowledge in-office policy (2 days → 3 days/week)
  - Current location vs relocation plan
- Valid successful path used: **"Yes, I’d relocate prior to the start of the role"** and **"Yes, I plan to relocate"**.
- "How did you hear about us?" supports `LinkedIn` and works normally with click→snapshot→click.
- Post-submit shows explicit success confirmation: **"Thank you for applying."**

---

## Zscaler Greenhouse Specifics (2026-02-24)

- Zscaler form (job_id `5020707007`) includes multiple required compliance checkboxes in addition to dropdowns:
  - **Zscaler Confidential Information** (I Agree)
  - **Zscaler Privacy Policy** (I Agree)
  - **Demographic data processing consent** checkbox
- Required text fields beyond basics: `Current Company*`, `Current Title*`, and `Primary residence city/state*`.
- "How did you learn about this job?" options include `Linkedin` (lowercase "i" in label); selecting it works with standard click→snapshot→click.
- Post-submit page showed explicit success message: **"Thank you for applying."**

---

## Cloudflare Greenhouse Specifics (2026-02-24)

- Cloudflare form for job_id `7547145` uses a mix of field types:
  - `How did you hear about this job?*` is a **plain text box** (not a dropdown)
  - Sponsorship question is a **combobox** (`Yes/No`)
  - Candidate Privacy Policy uses a required **Acknowledge/Confirm** checkbox
- Location field uses autocomplete; selecting `Dallas, Texas, United States` works reliably via click→snapshot→click.
- Submission lands on explicit confirmation page: **"Thank you for applying!"** with links to Cloudflare blog/jobs.
- Cloudflare role `7542471` (Fullstack Software Engineer) adds a required relocation dropdown with long option labels. Successful selection: **"I am willing to relocate to this job's location."**; sponsorship = `Yes`; submit confirms with the same **"Thank you for applying!"** page.

- Stripe job_id `4921361` required an additional Greenhouse **email security code** step after first submit click (8 single-character boxes). Pull latest email from `no-reply@us.greenhouse-mail.io`, enter code one character per box, then submit again.
- Stripe job_id `6692166` uses the same email security-code gate; important detail: boxes are `e1005..e1012` (8 total). If code is shifted/mistyped, page shows `Incorrect security code`; re-enter all 8 chars in order and resubmit.

- Stripe job_id `7217048` (Backend Engineer, Billing / Tax) follows the same full-variant flow and also triggers post-submit email security verification; after entering the 8-char code, confirmation renders normally with "Thank you for applying."

## Datadog Greenhouse Email Verification (LEARNED - 2026-02-25)

- Some Datadog Greenhouse forms trigger a human verification step **after first submit**.
- A Greenhouse email arrives with subject: `Security code for your application to Datadog` from `no-reply@us.greenhouse-mail.io`.
- The form shows 8 separate security-code boxes.
- **Important:** typing all 8 characters into the first box only fills the first character. Enter one character per box.
- After code entry + resubmit, confirmation page shows: `Thank you for applying.`


## Stripe Greenhouse Variant (gh_jid=6567253) - 2026-02-25

- Form includes a long set of required fields beyond basics: residence country, anticipated work countries (checkbox), authorization, sponsorship, remote preference, prior Stripe employment, prior employer/title, school/degree, WhatsApp opt-in, and BrightHire consent.
- After first submit, Stripe triggered Greenhouse human verification with an **8-character email security code** and disabled submit until all 8 boxes were filled.
- Reliable pattern remains: enter verification code **one character per box**, then submit again.


## Stripe Greenhouse Follow-up (gh_jid=6042172) - 2026-02-25

- For this Stripe posting, clicking **Submit application** can reveal the 8-box email verification section at the bottom (instead of immediate confirmation).
- Verification email subject remains: `Security code for your application to Stripe` from `no-reply@us.greenhouse-mail.io`.
- Enter code one character per box, then submit again.
- Confirmed successful state is the page header: `Thank you for applying.`

- Cloudflare role `7343760` (Software Engineer - Network Services) uses a simpler required set than the problematic variant `6885717`: one required relocate-to-city dropdown (`Yes/No`) plus standard resume upload. Selecting `Yes` and using atomic resume upload submitted cleanly and reached `Thank you for applying!`.

---

## NEW LEARNINGS (March 2026)

### Figma Greenhouse — Combobox Persistence Bug

- Figma's Greenhouse form has combobox values that do NOT persist in form state after click→snapshot→click
- Required comboboxes (Country, Location, Authorization, Prior Employment, Years Experience) appear selected but submit fails
- **Terminal blocker** — mark Figma Greenhouse as high-risk for combobox issues
- Workaround: Try JS-based value injection as fallback if click→snapshot→click doesn't persist

### Ashby Resume Upload — Autofill Recovery Pattern

- Ashby resume upload can fail silently: "Resume/CV is required" even after file input binding
- **Recovery pattern:** Upload via autofill uploader widget (not just `input#_systemfield_resume`)
- Must verify binding with JS: `document.querySelector('#_systemfield_resume').files.length === 1`
- If first upload fails, delete file, re-upload via autofill, wait 45s, then submit

### Ashby Radio Button Validation Timing

- Ashby radio buttons may fail validation on first submit due to timing/state flush issues
- **Fix:** Allow one retry — radio values usually register on second submit attempt
- Seen on Character.AI Research Engineer form

### Rippling Custom ATS — Not Automatable

- Rippling (used by ApexAnalytix, others) has a custom ATS with resume upload binding issues
- Required CV upload field does NOT bind to hidden Rippling file input via standard `browser upload`
- Apply button stays disabled until resume binds
- **Terminal blocker** — add Rippling to known-hard-ATS exclusion list

### Anthropic Greenhouse — High Timeout Risk

- Anthropic Greenhouse forms frequently trigger browser control service timeouts during fill
- Multiple roles (Research Engineer Agents/Tokens, Alignment Science) timed out on attempt 1
- **Learning:** Anthropic forms may be especially heavy/slow or have anti-bot protections
- Consider longer timeouts (15s vs default 10s) when applying to Anthropic

### Country Dropdown — Always Verify Pre-Submit

- Even if country dropdown appears pre-selected as "United States", it may not be in form state
- **Always snapshot and explicitly verify/select country before submit**
- Confirmed on Anthropic Research Engineer Pre-training (5135168008): first submit failed, retry with explicit country selection succeeded

### OpenAI Seniority Mismatch

- OpenAI "Data Scientist" roles actually require 10+ years of experience
- **Skip all OpenAI Data Scientist roles** — title is misleading
- Focus on OpenAI Research/Applied Scientist titles if they match experience level

### New Aggregators / Login Walls to Block

- **myGwork** — jobs aggregator, "Apply Now" redirects externally, not automatable
- **Haystack** (haystackapp.io) — account-gated ATS, Apply CTA requires login, not automatable
- Add both to aggregator/login-wall skip list

### Gateway Recovery (Reinforced)

On browser control timeout mid-application:
1. `openclaw gateway status`
2. `openclaw gateway start` (or `restart`)
3. Re-open same application URL, resume from last completed step
4. Send Telegram delay/recovery update
5. Continue autonomously — do NOT ask user

### reCAPTCHA False Positive Bug (CRITICAL)

The fast-apply script was **falsely reporting "submitted" when reCAPTCHA was actually blocking**:
- Form fills completely, submit button clicked
- reCAPTCHA silently blocks — no confirmation page appears
- Script marks job as "applied" in dedup log (false positive)
- Actual success rate: ~56% (242/549 confirmed vs logged)
- **Fix:** MUST verify post-submit confirmation before marking as submitted
- Check for: "Thank you for applying", "Application submitted", confirmation page URL change
- If none found after 5 seconds → mark as `failed` with error `recaptcha_blocked`
- Companies with high reCAPTCHA block rates: SoFi, Tenstorrent, Scopely, Abnormal Security, Databricks, Coinbase, CoreWeave (~37% of attempts blocked)

### React Select Dropdown — Keyboard Navigation Required (CRITICAL)

ARIA click on React Select dropdowns selects visually but **does NOT trigger React's onChange**:
- Standard click→snapshot→click pattern makes the option look selected
- But React state is unchanged → submit fails validation
- **Fix:** Use keyboard navigation instead:
  1. Focus the combobox (click it)
  2. ArrowDown to navigate to desired option
  3. Enter to select
- This triggers React's internal event handling properly
- Applies to: Greenhouse comboboxes, some Ashby dropdowns

### Greenhouse Security Code — React nativeSetter Required

The 8-character security code inputs (Stripe, Datadog, Roblox) are React controlled inputs:
- Regular `type` or `fill` only sets the first character
- **Fix:** Use React's internal `nativeSetter` to set each input value:
  ```js
  const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  nativeSetter.call(input, char);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  ```
- Each box auto-advances focus to the next after value is set
- Companies confirmed: Stripe, Datadog, Roblox

### DS Resume Selection Logic

Use different resumes based on role type:
- **Data Scientist / Data Analyst / Analytics** roles → DS resume
- **AI Engineer / ML Engineer / GenAI / NLP / Applied Scientist** → GenAI resume (default)
- Worker should check job title against `target_keywords` on each resume
- If multiple resumes match, prefer the one with the most specific keyword match
- If no match, use the `is_default` resume

### Worker Idle Queue Backoff

The cron worker ran hundreds of empty queue scans over 6 days with zero submissions:
- When queue is empty, use **exponential backoff** instead of fixed POLL_INTERVAL
- Start at 10s, double each empty scan, cap at 5 minutes
- Reset to 10s when a job is found
- Log queue-exhaustion events but don't spam Telegram

### Indeed — HTTP 403 Blocked

Indeed returns HTTP 403, completely blocked for automated scraping:
- Do NOT attempt to scrape Indeed job listings
- Add `indeed.com` to blocked domains for apply URLs
- LinkedIn Voyager API is the primary discovery source instead

### Jobright Sign-Up Wall Mechanism

Jobright blocks employer redirects with a **sign-up modal**:
- Even if the underlying job is real, Jobright intercepts the apply URL
- Modal requires account creation before showing the real employer page
- **Not automatable** — already in blocked domains, but this documents WHY

### Gusto Greenhouse — Submit No-Confirmation

Gusto job `7557049` reached submit-no-confirmation cap:
- Submit button clicked, no confirmation page appeared
- Distinct from reCAPTCHA — form accepted submit but gave no feedback
- Treat as `failed` if no confirmation within 5 seconds post-submit

### Additional Companies by ATS Platform (March 2026)

**Ashby:** Character.AI, Harvey, Ramp, PostHog, Notion
**Greenhouse:** xAI, CoreWeave, Collibra, Tenstorrent, Scopely, DeepMind, SoFi, Perpay, Fluidstack, Rillet, Cohere, Chainlink Labs, Sumo Logic, Roblox
**Lever:** Voleon (confirmed still active Feb 2026)

### Unsupported ATS Platforms (No Learnings Yet)

**iCIMS:** Mentioned in product roadmap as target ATS. No applier, no scanner, no learnings. Many enterprise companies (Amazon, Target, UnitedHealth) use iCIMS. URL pattern: `*.icims.com/jobs/*/job` or `careers-*.icims.com`. Status: Not yet supported.

**Taleo (Oracle):** Legacy ATS still used by some large enterprises. URL pattern: `*.taleo.net`. Known for extremely complex multi-page forms. Status: Not yet supported, low priority (most companies migrating away).
