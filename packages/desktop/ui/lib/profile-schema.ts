/**
 * KEEP IN SYNC with packages/web/src/lib/profile-schema.ts
 *
 * This file is a byte-identical copy of the web-side profile schema lib.
 * Desktop's Next.js app can't cross-package import from packages/web (no
 * shared monorepo path alias), so we copy and keep them in sync manually.
 * Any edit to one MUST be mirrored to the other.
 *
 * ---
 *
 * Shared profile-extraction contract.
 *
 * Used in two places:
 *   1. The web onboarding AI-paste step (`app/onboarding/page.tsx`) — the
 *      user pastes their resume text into a Claude chat, gets back JSON
 *      matching this schema, and pastes the JSON back into the form.
 *   2. The server-side resume parser (`app/api/profile/extract-resume`) —
 *      downloads the user's default resume PDF from Supabase Storage and
 *      sends it to OpenAI with this same prompt, so both paths produce
 *      structurally identical data and both land in the same columns on
 *      `user_profiles`.
 *
 * If you edit this prompt, every downstream reader/writer picks up the
 * change automatically. Do not fork it.
 */
export const AI_PROFILE_PROMPT = `I'm setting up ApplyLoop — an automated job application bot. I need my COMPLETE professional profile extracted as JSON. Use my resume (paste it below or reference from our past conversations).

CRITICAL — you MUST extract ALL of the following, not a summary:

  1. EVERY work experience, from most recent to oldest:
     - Full legal company name (e.g. "Modernizing Medicine, Inc.", not "ModMed")
     - Exact job title as written on the resume
     - City/state location, even if only one of the two is given
     - Start and end dates in "Mon YYYY" format ("Present" if current)
     - At minimum 3 achievement bullets per role, verbatim from the resume
       (use the exact phrasing — do NOT paraphrase or shorten)

  2. EVERY education entry, undergraduate AND graduate AND doctoral:
     - School name (full legal name, e.g. "University of Florida", not "UF")
     - Full degree (e.g. "Master of Science", "Bachelor of Engineering")
     - Field of study (e.g. "Computer & Information Science & Engineering")
     - Start and end months+years
     - GPA if present
     Do NOT drop the bachelor's just because I also have a master's —
     include ALL educations I have.

  3. EVERY technical and professional skill on the resume, as a flat list.
     Aim for 15-30 entries when the resume supports it. Deduplicate,
     but do not collapse categories (keep "PyTorch" and "TensorFlow"
     separately, keep both "SQL" and "PostgreSQL" if both are listed).

  4. EEO + work authorization fields as the resume implies them (or
     "decline" if not stated).

  5. "target_titles" — after parsing the above, GENERATE a list of
     10-15 job titles that are genuinely relevant to THIS person given
     their experience, skills, and education. Do not copy generic
     examples — these must be titles I could realistically apply to.
     E.g. if the resume shows strong NLP/LLM experience, include
     "NLP Engineer", "LLM Engineer", "Applied Scientist - NLP"; if the
     resume shows CV experience include "Computer Vision Engineer".
     Bias toward IC (individual contributor) titles at the same seniority
     level as the most recent role, plus one step up.

  6. "standard_answers" — generate real professional prose (not
     placeholders) based on my actual resume: why_interested tailored
     to my target_titles, strengths referencing my actual projects,
     career_goals consistent with my trajectory, and a cover_letter_template
     that opens with a specific achievement from my most recent role.

DEFAULT VALUES — fill these in if my resume doesn't explicitly state
otherwise (these are my standing assumptions, override only if the
resume contradicts them):

  - work_authorization:     "opt"              (STEM OPT, international student)
  - requires_sponsorship:   true               (I need H-1B / work visa sponsorship)
  - disability_status:      "no_disability"
  - veteran_status:         "not_veteran"
  - salary_min:             120000             (USD/year floor)
  - salary_max:             180000             (USD/year ceiling)
  - remote_only:            false              (open to onsite/hybrid in target metros)
  - auto_apply:             true               (this tool is doing the applying)
  - preferred_locations:    ["United States"]  (broaden if resume shows specific city preference)

Apply these automatically. Do NOT leave these fields blank, null, or
empty strings — use the defaults unless the resume explicitly contradicts
them. Override only when you have clear evidence from the resume (e.g.
resume says "US Citizen" → work_authorization: "us_citizen",
requires_sponsorship: false).

Respond with ONLY this JSON (fill everything you know, leave "" for unknown):

{
  "first_name": "",
  "last_name": "",
  "email": "",
  "phone": "",
  "pronouns": "he/him",
  "linkedin_url": "",
  "github_url": "",
  "portfolio_url": "",
  "city": "",
  "state": "",
  "zip_code": "",
  "street_address": "",

  "current_company": "",
  "current_title": "",
  "years_experience": 0,

  "work_experience": [
    {"company": "", "title": "", "location": "", "start_date": "Mon YYYY", "end_date": "Present", "achievements": ["bullet 1", "bullet 2", "bullet 3"]},
    {"company": "", "title": "", "location": "", "start_date": "Mon YYYY", "end_date": "Mon YYYY", "achievements": ["bullet 1", "bullet 2"]}
  ],

  "education": [
    {"school": "", "degree": "", "field": "", "start_date": "Mon YYYY", "end_date": "Mon YYYY", "gpa": ""},
    {"school": "", "degree": "", "field": "", "start_date": "Mon YYYY", "end_date": "Mon YYYY", "gpa": ""}
  ],

  "skills": ["Python", "PyTorch", "etc"],

  "education_level": "masters",
  "school_name": "",
  "degree": "",
  "graduation_year": 0,

  "work_authorization": "opt",
  "requires_sponsorship": true,
  "gender": "male",
  "race_ethnicity": "asian",
  "veteran_status": "not_veteran",
  "disability_status": "no_disability",
  "hispanic_latino": "no",

  "salary_min": 120000,
  "salary_max": 180000,
  "willing_to_relocate": true,

  "target_titles": ["AI Engineer", "ML Engineer", "Data Scientist"],
  "excluded_companies": [],
  "preferred_locations": ["United States"],
  "remote_only": false,
  "auto_apply": true,

  "standard_answers": {
    "why_interested": "3-4 sentence answer about why you're interested in AI/ML roles, referencing your background",
    "strengths": "3-4 sentence answer about your key technical strengths",
    "career_goals": "2-3 sentence answer about your career direction",
    "cover_letter_template": "4-5 sentence cover letter intro referencing your experience and what excites you about the role",
    "additional_info": "Any relevant info: visa status, publications, certifications, etc."
  }
}

Valid values:
- education_level: "bachelors", "masters", "phd", "other"
- work_authorization: "us_citizen", "green_card", "h1b", "opt", "tn", "other"
- gender: "male", "female", "non_binary", "decline"
- race_ethnicity: "asian", "black", "hispanic", "white", "native_american", "pacific_islander", "two_or_more", "decline"
- veteran_status: "not_veteran", "veteran", "decline"
- disability_status: "no_disability", "has_disability", "decline"

Final checks before returning the JSON:
  - work_experience has an entry for EVERY job on the resume
  - education has an entry for EVERY school (undergrad AND grad)
  - skills has 15+ entries when the resume supports it
  - target_titles are TAILORED to my actual background, not generic
  - standard_answers contain real prose, not placeholders`;

/**
 * Set of field names from the parse result that we persist to
 * `user_profiles`. Anything not in this set gets dropped even if the LLM
 * returned it — keeps the DB clean and is defense-in-depth against the
 * model hallucinating columns.
 *
 * Must stay aligned with the `allowedFields` whitelist in
 * `/api/settings/profile/route.ts` — same allowlist, different use.
 */
export const PERSISTABLE_PROFILE_FIELDS = [
  "first_name", "last_name", "phone", "linkedin_url", "github_url",
  "portfolio_url", "current_company", "current_title", "years_experience",
  "education_level", "school_name", "degree", "graduation_year",
  "work_authorization", "requires_sponsorship",
  "gender", "race_ethnicity", "veteran_status", "disability_status",
  "cover_letter_template",
  "work_experience", "skills", "education",
] as const;

export type ParsedProfile = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [k: string]: any;
};

/**
 * Filter an LLM parse result down to only fields we actually persist,
 * coerce types where the DB is strict, and drop nulls/empties.
 */
export function sanitizeParsedProfile(raw: ParsedProfile): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of PERSISTABLE_PROFILE_FIELDS) {
    const v = raw[f];
    if (v === undefined || v === null) continue;
    if (typeof v === "string" && v.trim() === "") continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[f] = v;
  }
  // years_experience + graduation_year must be integers in Postgres.
  if (typeof out.years_experience === "string") {
    const n = parseInt(out.years_experience as string, 10);
    if (Number.isFinite(n)) out.years_experience = n;
    else delete out.years_experience;
  }
  if (typeof out.graduation_year === "string") {
    const n = parseInt(out.graduation_year as string, 10);
    if (Number.isFinite(n)) out.graduation_year = n;
    else delete out.graduation_year;
  }
  // answer_key_json is the server-side name for the standard_answers object
  // in the prompt schema. The LLM returns `standard_answers`; remap.
  if (raw.standard_answers && typeof raw.standard_answers === "object") {
    out.answer_key_json = raw.standard_answers;
  }
  return out;
}

/**
 * Defaults applied when an LLM response is missing a field or the field is
 * empty/null. Matches the "DEFAULT VALUES" section in AI_PROFILE_PROMPT so
 * the parser enforces what the prompt already requested.
 *
 * These are the user's standing assumptions — override ONLY when the parsed
 * data contains a non-empty, non-contradictory value.
 */
export const PROFILE_DEFAULTS = {
  // user_profiles columns
  work_authorization: "opt",
  requires_sponsorship: true,
  disability_status: "no_disability",
  veteran_status: "not_veteran",
  // user_job_preferences columns (extracted separately by the caller)
  salary_min: 120000,
  salary_max: 180000,
  remote_only: false,
  auto_apply: true,
  preferred_locations: ["United States"],
} as const;

/** Field-name synonyms the LLM sometimes emits instead of canonical names. */
const FIELD_ALIASES: Record<string, string> = {
  // work_experience variants
  experience: "work_experience",
  experiences: "work_experience",
  work_experiences: "work_experience",
  jobs: "work_experience",
  work_history: "work_experience",
  employment: "work_experience",
  employment_history: "work_experience",
  // education variants
  education_history: "education",
  educations: "education",
  schools: "education",
  academic_history: "education",
  // skills variants
  technical_skills: "skills",
  skillset: "skills",
  tech_stack: "skills",
  // standard_answers variants
  answers: "standard_answers",
  application_answers: "standard_answers",
  standardAnswers: "standard_answers",
  // preferences variants
  target_roles: "target_titles",
  targetTitles: "target_titles",
  job_titles: "target_titles",
};

/**
 * Forgiving JSON parse that handles the shapes LLMs actually emit:
 *   - wrapped in markdown fences (```json ... ```)
 *   - trailing commas (,])
 *   - // line comments
 *   - prose before/after the JSON block
 *   - single-line // comments that real JSON doesn't allow
 *
 * Returns null on total failure. Never throws — callers should check for
 * null and show a generic "couldn't parse" message.
 */
export function tolerantJsonParse(raw: string): ParsedProfile | null {
  if (!raw || typeof raw !== "string") return null;
  let s = raw.trim();
  // 1. Strip markdown fences
  const fence = s.match(/```(?:json|javascript|js)?\s*([\s\S]*?)```/);
  if (fence) s = fence[1].trim();
  // 2. Find the first top-level {...} block
  const braceStart = s.indexOf("{");
  if (braceStart === -1) return null;
  // Try to find the matching closing brace by counting depth — handles the
  // case where the LLM added prose after the JSON block.
  let depth = 0;
  let end = -1;
  let inString = false;
  let escape = false;
  for (let i = braceStart; i < s.length; i++) {
    const c = s[i];
    if (escape) { escape = false; continue; }
    if (c === "\\") { escape = true; continue; }
    if (c === '"') { inString = !inString; continue; }
    if (inString) continue;
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) { end = i; break; }
    }
  }
  if (end === -1) return null;
  s = s.slice(braceStart, end + 1);
  // 3. Strip // line comments (JSON doesn't allow them but LLMs sometimes emit)
  s = s.replace(/(^|[^:])\/\/[^\n]*/g, "$1");
  // 4. Strip /* ... */ block comments
  s = s.replace(/\/\*[\s\S]*?\*\//g, "");
  // 5. Strip trailing commas before ] or }
  s = s.replace(/,(\s*[\]}])/g, "$1");
  // 6. Try parsing; if it still fails, try once more with unquoted-key coercion
  try {
    return JSON.parse(s) as ParsedProfile;
  } catch {
    try {
      const coerced = s.replace(/([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)/g, '$1"$2"$3');
      return JSON.parse(coerced) as ParsedProfile;
    } catch {
      return null;
    }
  }
}

/**
 * Normalize an LLM parse result into the canonical profile shape.
 * This is the "be liberal in what you accept" stage:
 *
 *   - Coerces alias field names to canonical names (experience → work_experience).
 *   - Extracts salary_min/salary_max from a nested `salary: {min, max}` object.
 *   - Applies PROFILE_DEFAULTS for any missing/empty field.
 *   - Drops unknown fields without error.
 *   - Returns a tuple: [canonical, summary of what was inferred/defaulted]
 */
export function normalizeAndApplyDefaults(
  raw: ParsedProfile | null | undefined
): { profile: Record<string, unknown>; prefs: Record<string, unknown>; defaulted: string[] } {
  const out: Record<string, unknown> = {};
  const prefs: Record<string, unknown> = {};
  const defaulted: string[] = [];

  if (!raw || typeof raw !== "object") {
    // Entirely empty input — still fill defaults so the user gets a
    // usable row rather than an error.
    Object.assign(out, {
      work_authorization: PROFILE_DEFAULTS.work_authorization,
      requires_sponsorship: PROFILE_DEFAULTS.requires_sponsorship,
      disability_status: PROFILE_DEFAULTS.disability_status,
      veteran_status: PROFILE_DEFAULTS.veteran_status,
    });
    Object.assign(prefs, {
      min_salary: PROFILE_DEFAULTS.salary_min,
      max_salary: PROFILE_DEFAULTS.salary_max,
      remote_only: PROFILE_DEFAULTS.remote_only,
      auto_apply: PROFILE_DEFAULTS.auto_apply,
      preferred_locations: [...PROFILE_DEFAULTS.preferred_locations],
    });
    defaulted.push("ALL (input was empty/invalid)");
    return { profile: out, prefs, defaulted };
  }

  // Step 1: coerce alias field names to canonical names.
  const normalized: ParsedProfile = {};
  for (const [k, v] of Object.entries(raw)) {
    const canonical = FIELD_ALIASES[k] || FIELD_ALIASES[k.toLowerCase()] || k;
    if (!(canonical in normalized) || normalized[canonical] === "" || normalized[canonical] == null) {
      normalized[canonical] = v;
    }
  }

  // Step 2: extract nested salary object if present.
  if (normalized.salary && typeof normalized.salary === "object" && !Array.isArray(normalized.salary)) {
    const sal = normalized.salary as Record<string, unknown>;
    if (normalized.salary_min == null && sal.min != null) normalized.salary_min = sal.min;
    if (normalized.salary_max == null && sal.max != null) normalized.salary_max = sal.max;
  }

  const nonEmpty = (v: unknown): boolean => {
    if (v === null || v === undefined) return false;
    if (typeof v === "string") return v.trim().length > 0;
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === "object") return Object.keys(v as object).length > 0;
    return true;
  };
  const toInt = (v: unknown): number | null => {
    if (typeof v === "number" && Number.isFinite(v)) return Math.round(v);
    if (typeof v === "string") {
      const n = parseInt(v.replace(/[^\d-]/g, ""), 10);
      return Number.isFinite(n) ? n : null;
    }
    return null;
  };

  // Step 3: passthrough fields that live on user_profiles.
  const profileScalars = [
    "first_name", "last_name", "phone", "linkedin_url", "github_url", "portfolio_url",
    "current_company", "current_title",
    "education_level", "school_name", "degree",
    "gender", "race_ethnicity", "cover_letter_template",
  ];
  for (const k of profileScalars) {
    if (nonEmpty(normalized[k])) out[k] = normalized[k];
  }
  // Integer-coerced scalars
  if (nonEmpty(normalized.years_experience)) {
    const n = toInt(normalized.years_experience);
    if (n !== null) out.years_experience = n;
  }
  if (nonEmpty(normalized.graduation_year)) {
    const n = toInt(normalized.graduation_year);
    if (n !== null) out.graduation_year = n;
  }
  // Arrays
  if (Array.isArray(normalized.work_experience) && normalized.work_experience.length > 0) {
    out.work_experience = normalized.work_experience;
  }
  if (Array.isArray(normalized.skills) && normalized.skills.length > 0) {
    out.skills = normalized.skills;
  }
  if (Array.isArray(normalized.education) && normalized.education.length > 0) {
    out.education = normalized.education;
  }
  // standard_answers → answer_key_json rename
  if (normalized.standard_answers && typeof normalized.standard_answers === "object") {
    out.answer_key_json = normalized.standard_answers;
  }

  // Step 4: apply DEFAULTS for empty/missing fields.
  if (!nonEmpty(normalized.work_authorization)) {
    out.work_authorization = PROFILE_DEFAULTS.work_authorization;
    defaulted.push("work_authorization");
  } else {
    out.work_authorization = normalized.work_authorization;
  }
  if (normalized.requires_sponsorship == null) {
    out.requires_sponsorship = PROFILE_DEFAULTS.requires_sponsorship;
    defaulted.push("requires_sponsorship");
  } else {
    out.requires_sponsorship = Boolean(normalized.requires_sponsorship);
  }
  if (!nonEmpty(normalized.disability_status)) {
    out.disability_status = PROFILE_DEFAULTS.disability_status;
    defaulted.push("disability_status");
  } else {
    out.disability_status = normalized.disability_status;
  }
  if (!nonEmpty(normalized.veteran_status)) {
    out.veteran_status = PROFILE_DEFAULTS.veteran_status;
    defaulted.push("veteran_status");
  } else {
    out.veteran_status = normalized.veteran_status;
  }

  // Step 5: user_job_preferences — separate table.
  if (Array.isArray(normalized.target_titles) && normalized.target_titles.length > 0) {
    prefs.target_titles = normalized.target_titles;
  }
  if (Array.isArray(normalized.excluded_companies)) {
    prefs.excluded_companies = normalized.excluded_companies;
  }
  if (Array.isArray(normalized.preferred_locations) && normalized.preferred_locations.length > 0) {
    prefs.preferred_locations = normalized.preferred_locations;
  } else {
    prefs.preferred_locations = [...PROFILE_DEFAULTS.preferred_locations];
    defaulted.push("preferred_locations");
  }
  // Salary — handles both top-level and nested salary.min/max
  const sMin = toInt(normalized.salary_min) ?? toInt((normalized as Record<string, unknown>).min_salary);
  const sMax = toInt(normalized.salary_max) ?? toInt((normalized as Record<string, unknown>).max_salary);
  if (sMin !== null) {
    prefs.min_salary = sMin;
  } else {
    prefs.min_salary = PROFILE_DEFAULTS.salary_min;
    defaulted.push("min_salary");
  }
  if (sMax !== null) {
    prefs.max_salary = sMax;
  } else {
    prefs.max_salary = PROFILE_DEFAULTS.salary_max;
    defaulted.push("max_salary");
  }
  // remote_only / auto_apply — booleans
  if (typeof normalized.remote_only === "boolean") {
    prefs.remote_only = normalized.remote_only;
  } else {
    prefs.remote_only = PROFILE_DEFAULTS.remote_only;
    defaulted.push("remote_only");
  }
  if (typeof normalized.auto_apply === "boolean") {
    prefs.auto_apply = normalized.auto_apply;
  } else {
    prefs.auto_apply = PROFILE_DEFAULTS.auto_apply;
    defaulted.push("auto_apply");
  }

  return { profile: out, prefs, defaulted };
}

/**
 * One-call helper for the UI sites: take a raw pasted string, produce
 * canonical profile + prefs objects ready to PUT, and a list of any
 * fields that were defaulted (for user feedback). Never throws.
 */
export function parseAiResponseSafe(raw: string): {
  ok: boolean;
  profile: Record<string, unknown>;
  prefs: Record<string, unknown>;
  defaulted: string[];
  error?: string;
} {
  const parsed = tolerantJsonParse(raw);
  if (parsed === null) {
    // Still run defaults so the user's row gets the baseline fields even
    // if the parse was entirely unrecognizable.
    const fallback = normalizeAndApplyDefaults(null);
    return {
      ok: false,
      profile: fallback.profile,
      prefs: fallback.prefs,
      defaulted: fallback.defaulted,
      error:
        "Could not parse JSON — check that you pasted a JSON object between curly braces. " +
        "Defaults will be applied if you save anyway.",
    };
  }
  const result = normalizeAndApplyDefaults(parsed);
  return { ok: true, ...result };
}
