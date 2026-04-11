"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createSupabaseBrowserClient } from "@/lib/supabase-browser";
import { AI_PROFILE_PROMPT, parseAiResponseSafe } from "@/lib/profile-schema";

// Persistent onboarding draft. We key by user id so switching Google accounts
// on the same machine doesn't show a stranger's data. The draft is a single
// JSON blob in localStorage, re-read on mount and re-saved after every form
// state mutation. Only serializable form state goes in — no File objects.
const DRAFT_VERSION = 1;
type OnboardingDraft = {
  v: number;
  step?: number;
  firstName?: string;
  lastName?: string;
  phone?: string;
  linkedinUrl?: string;
  githubUrl?: string;
  portfolioUrl?: string;
  currentCompany?: string;
  currentTitle?: string;
  yearsExperience?: string;
  educationLevel?: string;
  schoolName?: string;
  degree?: string;
  graduationYear?: string;
  workAuthorization?: string;
  requiresSponsorship?: boolean;
  gender?: string;
  raceEthnicity?: string;
  veteranStatus?: string;
  disabilityStatus?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  parsedWorkExperience?: any[];
  parsedSkills?: string[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  parsedStandardAnswers?: Record<string, any>;
  targetTitles?: string[];
  excludedCompanies?: string;
  minSalary?: string;
  remoteOnly?: boolean;
  autoApply?: boolean;
};

function draftKey(userId: string) {
  return `applyloop.onboarding.draft.${userId}`;
}

const ROLE_PRESETS = [
  "AI Engineer", "ML Engineer", "Data Scientist", "Data Engineer",
  "GenAI Engineer", "NLP Engineer", "Applied Scientist", "Research Engineer",
  "MLOps Engineer", "Computer Vision Engineer", "Analytics Engineer",
  "ML Platform Engineer", "AI Infrastructure Engineer",
  "Research Scientist", "Deep Learning Engineer", "Data Analyst",
  "BI Engineer", "Search Relevance Engineer",
];

type Step = 1 | 2 | 3 | 4 | 5;

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [userId, setUserId] = useState<string | null>(null);
  const [draftRestored, setDraftRestored] = useState(false);

  // Step 1: AI prompt paste
  const [aiResponse, setAiResponse] = useState("");
  const [promptCopied, setPromptCopied] = useState(false);

  // Step 2: Personal info (populated from AI response or manual)
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [githubUrl, setGithubUrl] = useState("");
  const [portfolioUrl, setPortfolioUrl] = useState("");

  // Step 3: Work & Education
  const [currentCompany, setCurrentCompany] = useState("");
  const [currentTitle, setCurrentTitle] = useState("");
  const [yearsExperience, setYearsExperience] = useState("");
  const [educationLevel, setEducationLevel] = useState("");
  const [schoolName, setSchoolName] = useState("");
  const [degree, setDegree] = useState("");
  const [graduationYear, setGraduationYear] = useState("");
  const [workAuthorization, setWorkAuthorization] = useState("");
  const [requiresSponsorship, setRequiresSponsorship] = useState(true);
  const [gender, setGender] = useState("");
  const [raceEthnicity, setRaceEthnicity] = useState("");
  const [veteranStatus, setVeteranStatus] = useState("");
  const [disabilityStatus, setDisabilityStatus] = useState("");

  // Parsed arrays from AI step — these are never shown in the form, just
  // round-tripped from step 1 into the POST in step 2/3. Without this the
  // onboarding flow persists empty work_experience/skills even though the
  // AI step extracted them from the user's resume.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [parsedWorkExperience, setParsedWorkExperience] = useState<any[]>([]);
  const [parsedSkills, setParsedSkills] = useState<string[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [parsedStandardAnswers, setParsedStandardAnswers] = useState<Record<string, any>>({});

  // Step 4: Job Preferences
  const [targetTitles, setTargetTitles] = useState<string[]>([]);
  const [excludedCompanies, setExcludedCompanies] = useState("");
  const [minSalary, setMinSalary] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [autoApply, setAutoApply] = useState(true);

  // Step 5: Resume
  const [resumeFile, setResumeFile] = useState<File | null>(null);

  // Resolve current user id once on mount and restore any existing draft.
  // Runs only in the browser (useEffect) so SSR is not affected.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const supabase = createSupabaseBrowserClient();
        const { data } = await supabase.auth.getUser();
        const uid = data.user?.id || null;
        if (cancelled) return;
        setUserId(uid);
        if (!uid) return;
        const raw = localStorage.getItem(draftKey(uid));
        if (!raw) return;
        const parsed = JSON.parse(raw) as OnboardingDraft;
        if (!parsed || parsed.v !== DRAFT_VERSION) return;
        if (parsed.firstName) setFirstName(parsed.firstName);
        if (parsed.lastName) setLastName(parsed.lastName);
        if (parsed.phone) setPhone(parsed.phone);
        if (parsed.linkedinUrl) setLinkedinUrl(parsed.linkedinUrl);
        if (parsed.githubUrl) setGithubUrl(parsed.githubUrl);
        if (parsed.portfolioUrl) setPortfolioUrl(parsed.portfolioUrl);
        if (parsed.currentCompany) setCurrentCompany(parsed.currentCompany);
        if (parsed.currentTitle) setCurrentTitle(parsed.currentTitle);
        if (parsed.yearsExperience) setYearsExperience(parsed.yearsExperience);
        if (parsed.educationLevel) setEducationLevel(parsed.educationLevel);
        if (parsed.schoolName) setSchoolName(parsed.schoolName);
        if (parsed.degree) setDegree(parsed.degree);
        if (parsed.graduationYear) setGraduationYear(parsed.graduationYear);
        if (parsed.workAuthorization) setWorkAuthorization(parsed.workAuthorization);
        if (parsed.requiresSponsorship !== undefined) setRequiresSponsorship(parsed.requiresSponsorship);
        if (parsed.gender) setGender(parsed.gender);
        if (parsed.raceEthnicity) setRaceEthnicity(parsed.raceEthnicity);
        if (parsed.veteranStatus) setVeteranStatus(parsed.veteranStatus);
        if (parsed.disabilityStatus) setDisabilityStatus(parsed.disabilityStatus);
        if (Array.isArray(parsed.parsedWorkExperience)) setParsedWorkExperience(parsed.parsedWorkExperience);
        if (Array.isArray(parsed.parsedSkills)) setParsedSkills(parsed.parsedSkills);
        if (parsed.parsedStandardAnswers && typeof parsed.parsedStandardAnswers === "object") {
          setParsedStandardAnswers(parsed.parsedStandardAnswers);
        }
        if (parsed.targetTitles?.length) setTargetTitles(parsed.targetTitles);
        if (parsed.excludedCompanies) setExcludedCompanies(parsed.excludedCompanies);
        if (parsed.minSalary) setMinSalary(parsed.minSalary);
        if (parsed.remoteOnly !== undefined) setRemoteOnly(parsed.remoteOnly);
        if (parsed.autoApply !== undefined) setAutoApply(parsed.autoApply);
        if (parsed.step && parsed.step >= 1 && parsed.step <= 5) setStep(parsed.step as Step);
        setDraftRestored(true);
      } catch {
        // Corrupt draft — drop it silently.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist draft after every relevant field change. localStorage writes are
  // synchronous and cheap (< 2KB payload), so we don't bother debouncing.
  useEffect(() => {
    if (!userId) return;
    const draft: OnboardingDraft = {
      v: DRAFT_VERSION,
      step,
      firstName, lastName, phone, linkedinUrl, githubUrl, portfolioUrl,
      currentCompany, currentTitle, yearsExperience,
      educationLevel, schoolName, degree, graduationYear,
      workAuthorization, requiresSponsorship, gender, raceEthnicity,
      veteranStatus, disabilityStatus,
      parsedWorkExperience, parsedSkills, parsedStandardAnswers,
      targetTitles, excludedCompanies, minSalary, remoteOnly, autoApply,
    };
    try {
      localStorage.setItem(draftKey(userId), JSON.stringify(draft));
    } catch {
      // Quota exceeded or disabled — not fatal, just skip persistence.
    }
  }, [
    userId, step, firstName, lastName, phone, linkedinUrl, githubUrl, portfolioUrl,
    currentCompany, currentTitle, yearsExperience, educationLevel, schoolName, degree,
    graduationYear, workAuthorization, requiresSponsorship, gender, raceEthnicity,
    veteranStatus, disabilityStatus,
    parsedWorkExperience, parsedSkills, parsedStandardAnswers,
    targetTitles, excludedCompanies, minSalary, remoteOnly, autoApply,
  ]);

  function copyPrompt() {
    navigator.clipboard.writeText(AI_PROFILE_PROMPT);
    setPromptCopied(true);
    setTimeout(() => setPromptCopied(false), 2000);
  }

  function parseAiResponse() {
    // Extract JSON from the response (handle markdown code blocks). We try
    // a few recovery strategies before giving up so the user doesn't have
    // to hand-edit the AI's output: strip ``` fences, trim leading/trailing
    // prose, fall back to the first { ... } block.
    let jsonStr = aiResponse.trim();
    if (!jsonStr) {
      setError("Please paste the AI response first.");
      return;
    }

    // Use the shared tolerant parser: strips markdown fences, line/block
    // comments, trailing commas, prose wrapping, and applies our default
    // values for any missing/empty fields (work_auth, sponsorship, disability,
    // salary range, etc.). Never throws — on a totally-unparseable input it
    // still returns an object with defaults applied so the form can proceed.
    const result = parseAiResponseSafe(jsonStr);
    const p = result.profile as Record<string, unknown>;
    const pf = result.prefs as Record<string, unknown>;
    const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));

    if (!result.ok && result.error) {
      setError(result.error);
      // NOTE: we still apply defaults below — the user can edit and save.
    }

    // user_profiles / onboarding fields
    if (str(p.first_name)) setFirstName(str(p.first_name));
    if (str(p.last_name)) setLastName(str(p.last_name));
    if (str(p.phone)) setPhone(str(p.phone));
    if (str(p.linkedin_url)) setLinkedinUrl(str(p.linkedin_url));
    if (str(p.github_url)) setGithubUrl(str(p.github_url));
    if (str(p.portfolio_url)) setPortfolioUrl(str(p.portfolio_url));
    if (str(p.current_company)) setCurrentCompany(str(p.current_company));
    if (str(p.current_title)) setCurrentTitle(str(p.current_title));
    if (p.years_experience != null) setYearsExperience(str(p.years_experience));
    if (str(p.education_level)) setEducationLevel(str(p.education_level));
    if (str(p.school_name)) setSchoolName(str(p.school_name));
    if (str(p.degree)) setDegree(str(p.degree));
    if (p.graduation_year != null) setGraduationYear(str(p.graduation_year));
    if (str(p.work_authorization)) setWorkAuthorization(str(p.work_authorization));
    if (typeof p.requires_sponsorship === "boolean") setRequiresSponsorship(p.requires_sponsorship);
    if (str(p.gender)) setGender(str(p.gender));
    if (str(p.race_ethnicity)) setRaceEthnicity(str(p.race_ethnicity));
    if (str(p.veteran_status)) setVeteranStatus(str(p.veteran_status));
    if (str(p.disability_status)) setDisabilityStatus(str(p.disability_status));
    if (Array.isArray(p.work_experience)) setParsedWorkExperience(p.work_experience);
    if (Array.isArray(p.skills)) setParsedSkills(p.skills as string[]);
    if (p.answer_key_json && typeof p.answer_key_json === "object") {
      setParsedStandardAnswers(p.answer_key_json as Record<string, unknown>);
    }

    // user_job_preferences fields
    if (Array.isArray(pf.target_titles) && pf.target_titles.length) setTargetTitles(pf.target_titles as string[]);
    if (Array.isArray(pf.excluded_companies)) {
      setExcludedCompanies((pf.excluded_companies as string[]).join(", "));
    }
    if (pf.min_salary != null) setMinSalary(str(pf.min_salary));
    if (typeof pf.remote_only === "boolean") setRemoteOnly(pf.remote_only);
    if (typeof pf.auto_apply === "boolean") setAutoApply(pf.auto_apply);

    if (result.defaulted.length > 0) {
      console.info(
        `[onboarding] Applied defaults for missing/empty fields: ${result.defaulted.join(", ")}`
      );
    }

    if (result.ok) setError("");
    setStep(2); // Move to review step regardless of parse result — defaults are in place.
  }

  function toggleTitle(title: string) {
    setTargetTitles((prev) =>
      prev.includes(title) ? prev.filter((t) => t !== title) : [...prev, title]
    );
  }

  async function saveStep(stepNum: Step) {
    setLoading(true);
    setError("");

    try {
      if (stepNum === 1) {
        // AI prompt step — just parse and advance
        parseAiResponse();
        setLoading(false);
        return;
      }

      if (stepNum === 2 || stepNum === 3) {
        const res = await fetch("/api/onboarding/profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            first_name: firstName, last_name: lastName, phone,
            linkedin_url: linkedinUrl, github_url: githubUrl, portfolio_url: portfolioUrl,
            current_company: currentCompany, current_title: currentTitle,
            years_experience: yearsExperience ? parseInt(yearsExperience) : null,
            education_level: educationLevel, school_name: schoolName,
            degree, graduation_year: graduationYear ? parseInt(graduationYear) : null,
            work_authorization: workAuthorization,
            requires_sponsorship: requiresSponsorship,
            gender, race_ethnicity: raceEthnicity,
            veteran_status: veteranStatus, disability_status: disabilityStatus,
            work_experience: parsedWorkExperience,
            skills: parsedSkills,
            answer_key_json: parsedStandardAnswers,
          }),
        });
        if (!res.ok) throw new Error((await res.json()).message);
      }

      if (stepNum === 4) {
        const res = await fetch("/api/onboarding/preferences", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_titles: targetTitles,
            excluded_companies: excludedCompanies.split(",").map((s) => s.trim()).filter(Boolean),
            min_salary: minSalary ? parseInt(minSalary) : null,
            remote_only: remoteOnly,
            auto_apply: autoApply,
          }),
        });
        if (!res.ok) throw new Error((await res.json()).message);
      }

      if (stepNum === 5) {
        if (!resumeFile) { setError("Please upload a resume"); setLoading(false); return; }
        const formData = new FormData();
        formData.append("resume", resumeFile);
        const res = await fetch("/api/onboarding/resume", { method: "POST", body: formData });
        if (!res.ok) throw new Error((await res.json()).message);
        // Wipe the draft on successful finish so reopening /onboarding after
        // completion doesn't surface stale data (this happens if a user ever
        // circles back to the page for re-uploads, etc).
        if (userId) {
          try { localStorage.removeItem(draftKey(userId)); } catch { /* ignore */ }
        }
        router.push("/setup-complete");
        return;
      }

      setStep((stepNum + 1) as Step);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const stepLabels = ["AI Import", "Personal", "Work", "Preferences", "Resume"];

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full bg-white rounded-xl shadow-sm border p-8">
        {/* Progress */}
        <div className="flex items-center justify-between mb-8">
          {[1, 2, 3, 4, 5].map((s) => (
            <div key={s} className="flex items-center">
              <div className="flex flex-col items-center">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                  s <= step ? "bg-brand-600 text-white" : "bg-gray-200 text-gray-500"
                }`}>
                  {s}
                </div>
                <span className="text-xs text-gray-500 mt-1">{stepLabels[s - 1]}</span>
              </div>
              {s < 5 && <div className={`w-10 h-0.5 mx-1 ${s < step ? "bg-brand-600" : "bg-gray-200"}`} />}
            </div>
          ))}
        </div>

        {/* Step 1: AI Prompt Import */}
        {step === 1 && (
          <div className="space-y-4">
            <h2 className="text-xl font-bold">Quick Import from AI</h2>
            <p className="text-sm text-gray-500">
              Copy the prompt below, paste it into ChatGPT or Claude (they already know your details
              from past conversations), then paste their JSON response here.
            </p>

            <div className="relative">
              <pre className="bg-gray-50 border rounded-lg p-4 text-xs overflow-auto max-h-48 whitespace-pre-wrap">
                {AI_PROFILE_PROMPT}
              </pre>
              <button
                onClick={copyPrompt}
                className="absolute top-2 right-2 px-3 py-1 bg-white border rounded text-xs hover:bg-gray-50"
              >
                {promptCopied ? "Copied!" : "Copy"}
              </button>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Paste the AI response here
              </label>
              <textarea
                value={aiResponse}
                onChange={(e) => setAiResponse(e.target.value)}
                placeholder='Paste the JSON response from ChatGPT/Claude here...'
                rows={8}
                className="w-full px-3 py-2 border rounded-lg text-sm font-mono"
              />
            </div>

            <div className="flex items-center justify-between">
              <button
                onClick={() => setStep(2)}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Skip — fill manually instead
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Personal Info */}
        {step === 2 && (
          <div className="space-y-4">
            <h2 className="text-xl font-bold">Personal Information</h2>
            <p className="text-sm text-gray-500">Review and edit your details.</p>
            <div className="grid grid-cols-2 gap-4">
              <input placeholder="First Name *" value={firstName} onChange={(e) => setFirstName(e.target.value)} required className="px-3 py-2 border rounded-lg" />
              <input placeholder="Last Name *" value={lastName} onChange={(e) => setLastName(e.target.value)} required className="px-3 py-2 border rounded-lg" />
            </div>
            <input placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
            <input placeholder="LinkedIn URL" value={linkedinUrl} onChange={(e) => setLinkedinUrl(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
            <input placeholder="GitHub URL" value={githubUrl} onChange={(e) => setGithubUrl(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
            <input placeholder="Portfolio URL" value={portfolioUrl} onChange={(e) => setPortfolioUrl(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
          </div>
        )}

        {/* Step 3: Work & Education */}
        {step === 3 && (
          <div className="space-y-4">
            <h2 className="text-xl font-bold">Work & Education</h2>
            <p className="text-xs text-gray-500">All fields required — ATS forms need these to auto-apply.</p>
            <div className="grid grid-cols-2 gap-4">
              <input placeholder="Current Company *" value={currentCompany} onChange={(e) => setCurrentCompany(e.target.value)} required className="px-3 py-2 border rounded-lg" />
              <input placeholder="Current Title *" value={currentTitle} onChange={(e) => setCurrentTitle(e.target.value)} required className="px-3 py-2 border rounded-lg" />
            </div>
            <input placeholder="Years of Experience *" type="number" value={yearsExperience} onChange={(e) => setYearsExperience(e.target.value)} required className="w-full px-3 py-2 border rounded-lg" />
            <input placeholder="School Name *" value={schoolName} onChange={(e) => setSchoolName(e.target.value)} required className="w-full px-3 py-2 border rounded-lg" />
            <div className="grid grid-cols-2 gap-4">
              <input placeholder="Degree *" value={degree} onChange={(e) => setDegree(e.target.value)} required className="px-3 py-2 border rounded-lg" />
              <input placeholder="Graduation Year *" type="number" value={graduationYear} onChange={(e) => setGraduationYear(e.target.value)} required className="px-3 py-2 border rounded-lg" />
            </div>
            <select value={educationLevel} onChange={(e) => setEducationLevel(e.target.value)} required className="w-full px-3 py-2 border rounded-lg">
              <option value="">Education Level *</option>
              <option value="bachelors">Bachelor&apos;s</option>
              <option value="masters">Master&apos;s</option>
              <option value="phd">PhD</option>
              <option value="other">Other</option>
            </select>
            <select value={workAuthorization} onChange={(e) => setWorkAuthorization(e.target.value)} required className="w-full px-3 py-2 border rounded-lg">
              <option value="">Work Authorization *</option>
              <option value="us_citizen">US Citizen</option>
              <option value="green_card">Green Card</option>
              <option value="h1b">H-1B</option>
              <option value="opt">OPT/OPT STEM</option>
              <option value="tn">TN Visa</option>
              <option value="other">Other</option>
            </select>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={requiresSponsorship} onChange={(e) => setRequiresSponsorship(e.target.checked)} />
              <span className="text-sm">Will require visa sponsorship</span>
            </label>
            <p className="text-sm text-gray-500 mt-4">EEO information (required — ATS forms ask; choose &ldquo;Decline&rdquo; if you prefer not to say).</p>
            <div className="grid grid-cols-2 gap-4">
              <select value={gender} onChange={(e) => setGender(e.target.value)} required className="px-3 py-2 border rounded-lg">
                <option value="">Gender *</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="non_binary">Non-binary</option>
                <option value="decline">Decline to self-identify</option>
              </select>
              <select value={raceEthnicity} onChange={(e) => setRaceEthnicity(e.target.value)} required className="px-3 py-2 border rounded-lg">
                <option value="">Race/Ethnicity *</option>
                <option value="asian">Asian</option>
                <option value="black">Black or African American</option>
                <option value="hispanic">Hispanic or Latino</option>
                <option value="white">White</option>
                <option value="native_american">Native American</option>
                <option value="pacific_islander">Pacific Islander</option>
                <option value="two_or_more">Two or More Races</option>
                <option value="decline">Decline to self-identify</option>
              </select>
              <select value={veteranStatus} onChange={(e) => setVeteranStatus(e.target.value)} required className="px-3 py-2 border rounded-lg">
                <option value="">Veteran Status *</option>
                <option value="not_veteran">Not a veteran</option>
                <option value="veteran">Veteran</option>
                <option value="decline">Decline to self-identify</option>
              </select>
              <select value={disabilityStatus} onChange={(e) => setDisabilityStatus(e.target.value)} required className="px-3 py-2 border rounded-lg">
                <option value="">Disability Status *</option>
                <option value="no_disability">No disability</option>
                <option value="has_disability">Has disability</option>
                <option value="decline">Decline to self-identify</option>
              </select>
            </div>
          </div>
        )}

        {/* Step 4: Job Preferences */}
        {step === 4 && (
          <div className="space-y-4">
            <h2 className="text-xl font-bold">Job Preferences</h2>
            <p className="text-sm text-gray-500">Select target roles (click to toggle). AI-suggested roles are pre-selected.</p>
            <div className="flex flex-wrap gap-2">
              {/* Show preset roles + any AI-suggested roles not in presets */}
              {[...new Set([...ROLE_PRESETS, ...targetTitles])].map((title) => {
                const isSelected = targetTitles.includes(title);
                const isCustom = !ROLE_PRESETS.includes(title);
                return (
                  <button
                    key={title}
                    onClick={() => toggleTitle(title)}
                    className={`px-3 py-1 rounded-full text-sm border ${
                      isSelected
                        ? isCustom
                          ? "bg-purple-600 text-white border-purple-600"
                          : "bg-brand-600 text-white border-brand-600"
                        : "bg-white text-gray-700 border-gray-300 hover:border-brand-500"
                    }`}
                  >
                    {title}{isCustom && isSelected ? " ✨" : ""}
                  </button>
                );
              })}
            </div>
            <input placeholder="Excluded companies (comma separated)" value={excludedCompanies} onChange={(e) => setExcludedCompanies(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
            <input placeholder="Minimum salary (USD)" type="number" value={minSalary} onChange={(e) => setMinSalary(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={remoteOnly} onChange={(e) => setRemoteOnly(e.target.checked)} />
              <span className="text-sm">Remote only</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={autoApply} onChange={(e) => setAutoApply(e.target.checked)} />
              <span className="text-sm">Auto-apply to matching jobs (recommended)</span>
            </label>
          </div>
        )}

        {/* Step 5: Resume Upload */}
        {step === 5 && (
          <div className="space-y-4">
            <h2 className="text-xl font-bold">Upload Your Resume</h2>
            <p className="text-sm text-gray-500">
              Upload a PDF resume. This will be submitted with your applications.
            </p>
            <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
              <input
                type="file"
                accept=".pdf"
                onChange={(e) => setResumeFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-brand-50 file:text-brand-600 hover:file:bg-brand-100"
              />
              {resumeFile && (
                <p className="mt-2 text-sm text-green-600">{resumeFile.name}</p>
              )}
            </div>
          </div>
        )}

        {draftRestored && !error && (
          <p className="mt-4 text-xs text-gray-500">Restored your in-progress setup from this browser.</p>
        )}
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

        <div className="flex justify-between mt-8">
          {step > 1 ? (
            <button onClick={() => setStep((step - 1) as Step)} className="px-4 py-2 text-gray-600 hover:text-gray-800">
              Back
            </button>
          ) : <div />}
          <button
            onClick={() => saveStep(step)}
            disabled={loading || (step === 1 && !aiResponse.trim())}
            className="px-6 py-2 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {loading ? "Saving..." : step === 1 ? "Import & Continue" : step === 5 ? "Finish Setup" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
