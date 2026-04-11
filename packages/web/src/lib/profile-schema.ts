/**
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
