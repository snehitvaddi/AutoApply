# ATS Playbook

Operational notes for the Claude brain driving the apply loop. Each
section calls out the quirks that will trip a naive "snapshot → fill →
submit" flow. The brain loads the section for the current ATS on demand
via `knowledge.get_ats_playbook(name)` so the static system prompt stays
small.

Conventions used below:
- **Snapshot** = `browser.snapshot()` accessibility tree.
- **Ref** = element id like `e42` inside the snapshot.
- `type_into` vs `fill` matters on React SPAs (see Ashby).

---

## Greenhouse (`boards.greenhouse.io/<slug>`)

- **Embed URL conversion.** A career page link of the form
  `boards.greenhouse.io/<slug>/jobs/<id>` is the human-readable view.
  The actual apply form lives at the `embed/job_app?for=<slug>&token=<id>`
  URL. If the brain sees `boards.greenhouse.io/<slug>/jobs/<id>` and
  no form fields in the snapshot, navigate to the embed form URL.
- **Dropdown order.** Phone-country dropdown should be set BEFORE any
  other dropdowns — Greenhouse re-renders the phone number field when
  country changes and clobbers whatever was filled. Fill text fields
  first, then country, then the rest of the dropdowns.
- **Email security code.** Some Greenhouse postings gate submission
  behind an emailed 6-digit code. If the post-submit snapshot shows an
  input labeled "Enter security code," fetch the most recent Greenhouse
  code from the configured Gmail account (via the worker's IMAP helper)
  and fill it.
- **reCAPTCHA.** When the snapshot has an `iframe[title*="reCAPTCHA"]`,
  set `page_state=captcha` and skip — Greenhouse reCAPTCHA is enterprise
  and cannot be solved client-side.

## Lever (`jobs.lever.co/<slug>`)

- **Single "Full name" field.** Unlike Greenhouse (first + last), Lever
  uses one field. The answer-key has `"full name" -> "First Last"`.
- **Radios, not comboboxes.** Work-auth, sponsorship, EEO are all radio
  buttons. There are no native `<select>` dropdowns on a Lever apply
  page. Do not call `browser.select` — click the matching radio ref.
- **Submit backup.** Clicking the Submit button alone sometimes does
  nothing (race with Lever's JS). After clicking, call
  `browser.evaluate_js("() => { const f = document.querySelector('form');
  if (f) f.requestSubmit(); }")` as a belt-and-braces fire.
- **No EEO on apply page.** If the snapshot has "Demographic questions"
  but they are not required, skip them.

## Ashby (`jobs.ashbyhq.com/<slug>`)

- **`type_into`, not `fill`.** Ashby is a React SPA with controlled
  inputs. `fill_fields` sets the DOM value directly and does NOT fire
  React's synthetic events, so every field gets `aria-invalid=true` at
  submit. Always use `browser.type` per field.
- **Location = autocomplete combobox.** After typing the location, wait
  ~1s and press Enter (`browser.press_key("Enter")`) to commit the
  first suggestion. Without Enter, the field looks filled but fails
  validation.
- **45s wait after resume upload.** Ashby puts a transient lock on the
  submit button while the resume is processed server-side. If you click
  Submit sooner, you get a silent validation error with no visible
  message. Always sleep 45 seconds after `browser.upload`.
- **Combobox refs are unstable.** Any interaction with an Ashby
  combobox re-renders the form and invalidates every `ref` in the
  previous snapshot. Call `browser.snapshot` + `browser.parse_snapshot`
  again before the next click.
- **System resume field fallback.** If no "Resume" button is found in
  the snapshot, target `input#_systemfield_resume` directly via
  `evaluate_js("() => { const i = document.querySelector('input#_systemfield_resume'); if (i) i.click(); }")`.

## SmartRecruiters (`smartrecruiters.com/<slug>`)

- **Confirm email field.** There are TWO email fields — `Email` and
  `Confirm your email`. Fill both with the same address.
- **City autocomplete.** The City field is a combobox: click → type
  → wait → click the matching suggestion in the refreshed snapshot.
- **Multi-page flow.** Page 1 (personal info) has a "Next" button, not
  "Submit." Click Next, wait, take a new snapshot; page 2 (screening +
  EEO) has the real Submit.
- **Resume is a separate section.** The resume upload button sits at
  the bottom of page 1, below the text fields. Upload before hitting
  Next.

## Workday (`*.myworkdayjobs.com`)

The most complex ATS. Plan for up to **8 steps per apply**.

- **Account gate.** Every Workday tenant requires an account. First
  navigation lands on a "Sign In / Create Account" screen. If the
  snapshot shows only email + password + "Create Account," drive the
  account-creation flow with the tenant's configured Workday password
  (fallback: generated + stored in the secure store). If the snapshot
  says "Email already registered," pivot to the Sign-In path. For lost
  password, the worker exposes an IMAP-driven forgot-password tool.
- **`promptOption` dropdowns, not native `<select>`.** Workday renders
  dropdowns as a clickable button that opens a flyout `<ul>`. Do NOT
  call `browser.select`. Click the button ref, wait, snapshot, click
  the `menuitem` matching your answer.
- **Date spinbuttons.** Date fields are three separate `role=spinbutton`
  elements (month/day/year), NOT a textbox. Set each via JS:
  ```js
  () => { const el = document.querySelector('[aria-label="Month"]');
          el.value = "01"; el.dispatchEvent(new Event('change', {bubbles:true})); }
  ```
- **Multi-page wizard.** Steps typically go: Personal Info → My
  Experience → Resume Upload → Application Questions → Voluntary
  Disclosures → Self Identify → Review → Submit. Each "Next" / "Save
  and Continue" click reveals a new form. After each click, snapshot +
  decide which page you're on from the heading text.
- **"Add" repeaters.** Work history + education are repeaters — click
  "Add" to spawn a new entry block, fill, repeat. The answer key has
  a list under `work_experience` and `education`.

## LinkedIn (`linkedin.com/jobs/view/...`)

- **Sign-in wall is the default.** Guest LinkedIn shows a "Sign in to
  apply" modal on 95% of job pages. Do NOT try to apply there.
- **Resolution path:** set `page_state=needs_direct_url`, action =
  `search_direct_url`, and query
  `"<company>" "<role>" careers apply`. The driver navigates to Google
  Search. In the next iteration, pick the first result whose domain
  matches a known ATS (greenhouse.io, lever.co, ashbyhq.com,
  myworkdayjobs.com, smartrecruiters.com) and emit `action=navigate_to`
  with that URL.
- **Aggregator results.** Skip Dice, Indeed, LinkedIn re-posts,
  simplify.jobs, builtin.com in the Google results — go straight to
  the real ATS page.
- **If no ATS result.** Emit `skip_non_retriable` with
  `reason="no ATS careers page found for <company>"`. The queue row
  gets marked failed, no retries.

## Universal / unknown ATS

When the apply URL domain doesn't match any of the above:
1. Snapshot the page, look for a `<form>` and a Submit button.
2. Run the same fill/select/click/upload sequence as Greenhouse.
3. If you see unfamiliar UI (e.g. Taleo, iCIMS 2023, Phenom), emit
   `skip_non_retriable` with a short reason — don't burn budget on a
   template we haven't taught the brain yet. Log it in the session log
   so the admin can teach the brain later.
