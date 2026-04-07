"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const ROLE_PRESETS = [
  "AI Engineer", "ML Engineer", "Data Scientist", "Data Engineer",
  "GenAI Engineer", "NLP Engineer", "Applied Scientist", "Research Engineer",
  "MLOps Engineer", "Computer Vision Engineer", "Analytics Engineer",
  "ML Platform Engineer", "AI Infrastructure Engineer",
  "Research Scientist", "Deep Learning Engineer", "Data Analyst",
  "BI Engineer", "Search Relevance Engineer",
];

const AI_PROFILE_PROMPT = `I'm setting up ApplyLoop — an automated job application bot. I need my COMPLETE professional profile extracted as JSON. Use my resume (paste it below or reference from our past conversations).

IMPORTANT: Include ALL work experiences, ALL education entries, skills, and generate professional answers for common application questions.

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

Include ALL your work experiences (not just current). Include ALL education. Generate real professional answers for standard_answers based on your actual background.`;

type Step = 1 | 2 | 3 | 4 | 5;

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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

  // Step 4: Job Preferences
  const [targetTitles, setTargetTitles] = useState<string[]>([]);
  const [excludedCompanies, setExcludedCompanies] = useState("");
  const [minSalary, setMinSalary] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [autoApply, setAutoApply] = useState(true);

  // Step 5: Resume
  const [resumeFile, setResumeFile] = useState<File | null>(null);

  function copyPrompt() {
    navigator.clipboard.writeText(AI_PROFILE_PROMPT);
    setPromptCopied(true);
    setTimeout(() => setPromptCopied(false), 2000);
  }

  function parseAiResponse() {
    try {
      // Extract JSON from the response (handle markdown code blocks)
      let jsonStr = aiResponse.trim();
      const jsonMatch = jsonStr.match(/```(?:json)?\s*([\s\S]*?)```/);
      if (jsonMatch) jsonStr = jsonMatch[1].trim();

      const data = JSON.parse(jsonStr);

      // Populate all fields
      if (data.first_name) setFirstName(data.first_name);
      if (data.last_name) setLastName(data.last_name);
      if (data.phone) setPhone(data.phone);
      if (data.linkedin_url) setLinkedinUrl(data.linkedin_url);
      if (data.github_url) setGithubUrl(data.github_url);
      if (data.portfolio_url) setPortfolioUrl(data.portfolio_url);
      if (data.current_company) setCurrentCompany(data.current_company);
      if (data.current_title) setCurrentTitle(data.current_title);
      if (data.years_experience) setYearsExperience(String(data.years_experience));
      if (data.education_level) setEducationLevel(data.education_level);
      if (data.school_name) setSchoolName(data.school_name);
      if (data.degree) setDegree(data.degree);
      if (data.graduation_year) setGraduationYear(String(data.graduation_year));
      if (data.work_authorization) setWorkAuthorization(data.work_authorization);
      if (data.requires_sponsorship !== undefined) setRequiresSponsorship(data.requires_sponsorship);
      if (data.gender) setGender(data.gender);
      if (data.race_ethnicity) setRaceEthnicity(data.race_ethnicity);
      if (data.target_titles?.length) setTargetTitles(data.target_titles);
      if (data.excluded_companies?.length) setExcludedCompanies(data.excluded_companies.join(", "));
      if (data.salary_min) setMinSalary(String(data.salary_min));
      if (data.remote_only !== undefined) setRemoteOnly(data.remote_only);
      if (data.auto_apply !== undefined) setAutoApply(data.auto_apply);

      setError("");
      setStep(2); // Move to review step
    } catch {
      setError("Could not parse the response. Make sure you pasted valid JSON.");
    }
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
            <div className="grid grid-cols-2 gap-4">
              <input placeholder="Current Company" value={currentCompany} onChange={(e) => setCurrentCompany(e.target.value)} className="px-3 py-2 border rounded-lg" />
              <input placeholder="Current Title" value={currentTitle} onChange={(e) => setCurrentTitle(e.target.value)} className="px-3 py-2 border rounded-lg" />
            </div>
            <input placeholder="Years of Experience" type="number" value={yearsExperience} onChange={(e) => setYearsExperience(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
            <input placeholder="School Name" value={schoolName} onChange={(e) => setSchoolName(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
            <div className="grid grid-cols-2 gap-4">
              <input placeholder="Degree" value={degree} onChange={(e) => setDegree(e.target.value)} className="px-3 py-2 border rounded-lg" />
              <input placeholder="Graduation Year" type="number" value={graduationYear} onChange={(e) => setGraduationYear(e.target.value)} className="px-3 py-2 border rounded-lg" />
            </div>
            <select value={educationLevel} onChange={(e) => setEducationLevel(e.target.value)} className="w-full px-3 py-2 border rounded-lg">
              <option value="">Education Level</option>
              <option value="bachelors">Bachelor&apos;s</option>
              <option value="masters">Master&apos;s</option>
              <option value="phd">PhD</option>
              <option value="other">Other</option>
            </select>
            <select value={workAuthorization} onChange={(e) => setWorkAuthorization(e.target.value)} className="w-full px-3 py-2 border rounded-lg">
              <option value="">Work Authorization</option>
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
            <p className="text-sm text-gray-500 mt-4">EEO Information (optional)</p>
            <div className="grid grid-cols-2 gap-4">
              <select value={gender} onChange={(e) => setGender(e.target.value)} className="px-3 py-2 border rounded-lg">
                <option value="">Gender</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="non_binary">Non-binary</option>
                <option value="decline">Decline to self-identify</option>
              </select>
              <select value={raceEthnicity} onChange={(e) => setRaceEthnicity(e.target.value)} className="px-3 py-2 border rounded-lg">
                <option value="">Race/Ethnicity</option>
                <option value="asian">Asian</option>
                <option value="black">Black or African American</option>
                <option value="hispanic">Hispanic or Latino</option>
                <option value="white">White</option>
                <option value="native_american">Native American</option>
                <option value="pacific_islander">Pacific Islander</option>
                <option value="two_or_more">Two or More Races</option>
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
