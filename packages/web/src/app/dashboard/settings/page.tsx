"use client";

import { useEffect, useState, useCallback } from "react";

const ROLE_PRESETS = [
  "AI Engineer", "ML Engineer", "Data Scientist", "Data Engineer",
  "GenAI Engineer", "NLP Engineer", "Applied Scientist", "Research Engineer",
  "MLOps Engineer", "Computer Vision Engineer", "Analytics Engineer",
  "ML Platform Engineer", "AI Infrastructure Engineer",
];

type Tab = "ai-import" | "personal" | "work" | "preferences" | "resumes" | "telegram" | "worker" | "billing";

const AI_PROFILE_PROMPT = `I'm updating my automated job application profile. I need you to extract my professional details in JSON format. Use everything you know about me from our past conversations, my resume, or anything I've shared before.

Please respond with ONLY this JSON (fill in what you know, leave empty string "" for unknown):

{
  "first_name": "",
  "last_name": "",
  "phone": "",
  "linkedin_url": "",
  "github_url": "",
  "portfolio_url": "",
  "current_company": "",
  "current_title": "",
  "years_experience": 0,
  "education_level": "bachelors",
  "school_name": "",
  "degree": "",
  "graduation_year": 0,
  "work_authorization": "",
  "requires_sponsorship": false,
  "gender": "",
  "race_ethnicity": "",
  "target_titles": ["AI Engineer", "ML Engineer"],
  "excluded_companies": [],
  "salary_min": 120000,
  "remote_only": false,
  "auto_apply": true
}

Valid values:
- education_level: "bachelors", "masters", "phd", "other"
- work_authorization: "us_citizen", "green_card", "h1b", "opt", "tn", "other"
- gender: "male", "female", "non_binary", "decline"
- race_ethnicity: "asian", "black", "hispanic", "white", "native_american", "pacific_islander", "two_or_more", "decline"`;

interface Resume {
  id: string;
  file_name: string;
  storage_path: string;
  is_default: boolean;
  target_keywords: string[] | null;
  created_at: string;
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("ai-import");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<"success" | "error">("success");

  // Profile fields
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [githubUrl, setGithubUrl] = useState("");
  const [portfolioUrl, setPortfolioUrl] = useState("");

  // Work & Education fields
  const [currentCompany, setCurrentCompany] = useState("");
  const [currentTitle, setCurrentTitle] = useState("");
  const [yearsExperience, setYearsExperience] = useState("");
  const [educationLevel, setEducationLevel] = useState("");
  const [schoolName, setSchoolName] = useState("");
  const [degree, setDegree] = useState("");
  const [graduationYear, setGraduationYear] = useState("");
  const [workAuthorization, setWorkAuthorization] = useState("");
  const [requiresSponsorship, setRequiresSponsorship] = useState(false);
  const [gender, setGender] = useState("");
  const [raceEthnicity, setRaceEthnicity] = useState("");

  // Job Preferences
  const [targetTitles, setTargetTitles] = useState<string[]>([]);
  const [excludedCompanies, setExcludedCompanies] = useState("");
  const [minSalary, setMinSalary] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [autoApply, setAutoApply] = useState(true);

  // Resumes
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [resumeTargetRoles, setResumeTargetRoles] = useState("");
  const [resumeIsDefault, setResumeIsDefault] = useState(false);
  const [uploading, setUploading] = useState(false);

  // AI Import
  const [aiResponse, setAiResponse] = useState("");
  const [promptCopied, setPromptCopied] = useState(false);

  // Telegram
  const [telegramChatId, setTelegramChatId] = useState("");

  // Worker & LLM Config
  const [workerConfig, setWorkerConfig] = useState({
    llm_provider: "none",
    llm_model: "",
    llm_api_key_preview: "",
    llm_backend_provider: "none",
    llm_backend_model: "",
    llm_backend_api_key_preview: "",
    ollama_base_url: "http://localhost:11434",
    resume_tailoring: false,
    cover_letters: false,
    smart_answers: false,
    monthly_limit: 50,
    worker_id: "worker-1",
    poll_interval: 10,
    apply_cooldown: 30,
    auto_apply: true,
    max_daily_apps: 20,
  });
  const [newLlmApiKey, setNewLlmApiKey] = useState("");
  const [newBackendApiKey, setNewBackendApiKey] = useState("");

  // Billing
  const [tier, setTier] = useState("free");

  const showMessage = useCallback((msg: string, type: "success" | "error" = "success") => {
    setMessage(msg);
    setMessageType(type);
    setTimeout(() => setMessage(""), 4000);
  }, []);

  const fetchResumes = useCallback(async () => {
    const res = await fetch("/api/settings/resumes");
    const json = await res.json();
    setResumes(json.data || []);
  }, []);

  useEffect(() => {
    Promise.all([
      fetch("/api/settings/profile").then((r) => r.json()),
      fetch("/api/settings/preferences").then((r) => r.json()),
      fetch("/api/settings/resumes").then((r) => r.json()),
      fetch("/api/settings/worker-config").then((r) => r.json()),
    ]).then(([profileData, prefsData, resumesData, workerData]) => {
      if (workerData.data?.config) {
        setWorkerConfig(workerData.data.config);
      }
      const p = profileData.data?.profile || {};
      setFirstName(p.first_name || "");
      setLastName(p.last_name || "");
      setPhone(p.phone || "");
      setLinkedinUrl(p.linkedin_url || "");
      setGithubUrl(p.github_url || "");
      setPortfolioUrl(p.portfolio_url || "");
      setCurrentCompany(p.current_company || "");
      setCurrentTitle(p.current_title || "");
      setYearsExperience(p.years_experience ? String(p.years_experience) : "");
      setEducationLevel(p.education_level || "");
      setSchoolName(p.school_name || "");
      setDegree(p.degree || "");
      setGraduationYear(p.graduation_year ? String(p.graduation_year) : "");
      setWorkAuthorization(p.work_authorization || "");
      setRequiresSponsorship(p.requires_sponsorship || false);
      setGender(p.gender || "");
      setRaceEthnicity(p.race_ethnicity || "");
      setTelegramChatId(profileData.data?.telegram_chat_id || "");

      const prefs = prefsData.data?.preferences || {};
      setTargetTitles(prefs.target_titles || []);
      setExcludedCompanies(
        Array.isArray(prefs.excluded_companies)
          ? prefs.excluded_companies.join(", ")
          : ""
      );
      setMinSalary(prefs.min_salary ? String(prefs.min_salary) : "");
      setRemoteOnly(prefs.remote_only || false);
      setAutoApply(prefs.auto_apply !== undefined ? prefs.auto_apply : true);
      setTier(prefsData.data?.tier || "free");

      setResumes(resumesData.data || []);
      setLoading(false);
    });
  }, []);

  async function saveProfile() {
    setSaving(true);
    const res = await fetch("/api/settings/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        first_name: firstName,
        last_name: lastName,
        phone,
        linkedin_url: linkedinUrl,
        github_url: githubUrl,
        portfolio_url: portfolioUrl,
      }),
    });
    setSaving(false);
    if (res.ok) showMessage("Profile saved!");
    else showMessage("Failed to save profile", "error");
  }

  async function saveWorkEducation() {
    setSaving(true);
    const res = await fetch("/api/settings/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_company: currentCompany,
        current_title: currentTitle,
        years_experience: yearsExperience ? parseInt(yearsExperience) : null,
        education_level: educationLevel,
        school_name: schoolName,
        degree,
        graduation_year: graduationYear ? parseInt(graduationYear) : null,
        work_authorization: workAuthorization,
        requires_sponsorship: requiresSponsorship,
        gender,
        race_ethnicity: raceEthnicity,
      }),
    });
    setSaving(false);
    if (res.ok) showMessage("Work & education saved!");
    else showMessage("Failed to save", "error");
  }

  async function savePreferences() {
    setSaving(true);
    const res = await fetch("/api/settings/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_titles: targetTitles,
        excluded_companies: excludedCompanies.split(",").map((s) => s.trim()).filter(Boolean),
        min_salary: minSalary ? parseInt(minSalary) : null,
        remote_only: remoteOnly,
        auto_apply: autoApply,
      }),
    });
    setSaving(false);
    if (res.ok) showMessage("Preferences saved!");
    else showMessage("Failed to save preferences", "error");
  }

  async function saveTelegram() {
    setSaving(true);
    const res = await fetch("/api/settings/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: telegramChatId }),
    });
    setSaving(false);
    if (res.ok) showMessage("Telegram connected!");
    else showMessage("Failed to connect Telegram", "error");
  }

  async function disconnectTelegram() {
    setSaving(true);
    const res = await fetch("/api/settings/telegram", { method: "DELETE" });
    setSaving(false);
    if (res.ok) {
      setTelegramChatId("");
      showMessage("Telegram disconnected");
    } else {
      showMessage("Failed to disconnect", "error");
    }
  }

  async function uploadResume() {
    if (!resumeFile) return;
    setUploading(true);
    const formData = new FormData();
    formData.append("resume", resumeFile);
    formData.append("target_roles", resumeTargetRoles);
    formData.append("is_default", String(resumeIsDefault));

    const res = await fetch("/api/settings/resumes", { method: "POST", body: formData });
    setUploading(false);

    if (res.ok) {
      showMessage("Resume uploaded!");
      setResumeFile(null);
      setResumeTargetRoles("");
      setResumeIsDefault(false);
      fetchResumes();
    } else {
      const json = await res.json();
      showMessage(json.message || "Upload failed", "error");
    }
  }

  async function deleteResume(id: string) {
    if (!confirm("Delete this resume?")) return;
    const res = await fetch(`/api/settings/resumes/${id}`, { method: "DELETE" });
    if (res.ok) {
      showMessage("Resume deleted");
      fetchResumes();
    } else {
      showMessage("Failed to delete resume", "error");
    }
  }

  async function setDefaultResume(id: string) {
    const res = await fetch(`/api/settings/resumes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_default: true }),
    });
    if (res.ok) {
      showMessage("Default resume updated");
      fetchResumes();
    } else {
      showMessage("Failed to update default", "error");
    }
  }

  function copyPrompt() {
    navigator.clipboard.writeText(AI_PROFILE_PROMPT);
    setPromptCopied(true);
    setTimeout(() => setPromptCopied(false), 2000);
  }

  async function importFromAi() {
    try {
      let jsonStr = aiResponse.trim();
      const jsonMatch = jsonStr.match(/```(?:json)?\s*([\s\S]*?)```/);
      if (jsonMatch) jsonStr = jsonMatch[1].trim();

      const data = JSON.parse(jsonStr);

      // Populate all fields from AI response
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

      // Save profile + preferences to backend
      setSaving(true);
      const [profileRes, prefsRes] = await Promise.all([
        fetch("/api/settings/profile", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            first_name: data.first_name || firstName,
            last_name: data.last_name || lastName,
            phone: data.phone || phone,
            linkedin_url: data.linkedin_url || linkedinUrl,
            github_url: data.github_url || githubUrl,
            portfolio_url: data.portfolio_url || portfolioUrl,
            current_company: data.current_company || currentCompany,
            current_title: data.current_title || currentTitle,
            years_experience: data.years_experience ? parseInt(String(data.years_experience)) : null,
            education_level: data.education_level || educationLevel,
            school_name: data.school_name || schoolName,
            degree: data.degree || degree,
            graduation_year: data.graduation_year ? parseInt(String(data.graduation_year)) : null,
            work_authorization: data.work_authorization || workAuthorization,
            requires_sponsorship: data.requires_sponsorship ?? requiresSponsorship,
            gender: data.gender || gender,
            race_ethnicity: data.race_ethnicity || raceEthnicity,
          }),
        }),
        fetch("/api/settings/preferences", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_titles: data.target_titles?.length ? data.target_titles : targetTitles,
            excluded_companies: data.excluded_companies?.length ? data.excluded_companies : excludedCompanies.split(",").map((s: string) => s.trim()).filter(Boolean),
            min_salary: data.salary_min ? parseInt(String(data.salary_min)) : null,
            remote_only: data.remote_only ?? remoteOnly,
            auto_apply: data.auto_apply ?? autoApply,
          }),
        }),
      ]);
      setSaving(false);

      if (profileRes.ok && prefsRes.ok) {
        showMessage("All fields imported and saved! Review each tab to confirm.");
        setAiResponse("");
      } else {
        showMessage("Imported fields locally but some failed to save. Review each tab.", "error");
      }
    } catch {
      showMessage("Could not parse the response. Make sure you pasted valid JSON.", "error");
    }
  }

  function toggleTitle(title: string) {
    setTargetTitles((prev) =>
      prev.includes(title) ? prev.filter((t) => t !== title) : [...prev, title]
    );
  }

  if (loading) {
    return (
      <div className="p-8 text-gray-500">Loading settings...</div>
    );
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "ai-import", label: "AI Import" },
    { key: "personal", label: "Personal Info" },
    { key: "work", label: "Work & Education" },
    { key: "preferences", label: "Job Preferences" },
    { key: "resumes", label: "Resumes" },
    { key: "telegram", label: "Telegram" },
    { key: "worker", label: "Worker & LLM" },
    { key: "billing", label: "Billing" },
  ];

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      {message && (
        <div
          className={`mb-4 p-3 rounded-lg text-sm ${
            messageType === "success"
              ? "bg-green-50 text-green-700"
              : "bg-red-50 text-red-700"
          }`}
        >
          {message}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
              activeTab === tab.key
                ? "border-brand-600 text-brand-600"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* AI Import Tab */}
      {activeTab === "ai-import" && (
        <section className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold mb-2">Quick Import from AI</h2>
          <p className="text-sm text-gray-500 mb-4">
            Copy the prompt below, paste it into ChatGPT or Claude (they already know your details
            from past conversations), then paste their JSON response here. This will auto-fill all your profile fields.
          </p>

          <div className="relative">
            <pre className="bg-gray-50 border rounded-lg p-4 text-xs overflow-auto max-h-48 whitespace-pre-wrap">
              {AI_PROFILE_PROMPT}
            </pre>
            <button
              onClick={copyPrompt}
              className="absolute top-2 right-2 px-3 py-1 bg-white border rounded text-xs hover:bg-gray-50"
            >
              {promptCopied ? "Copied!" : "Copy Prompt"}
            </button>
          </div>

          <div className="mt-4">
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

          <button
            onClick={importFromAi}
            disabled={saving || !aiResponse.trim()}
            className="mt-4 px-6 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? "Importing & Saving..." : "Import & Save All Fields"}
          </button>
        </section>
      )}

      {/* Personal Info Tab */}
      {activeTab === "personal" && (
        <section className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold mb-4">Personal Information</h2>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">First Name</label>
                <input
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Last Name</label>
                <input
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">LinkedIn URL</label>
              <input
                value={linkedinUrl}
                onChange={(e) => setLinkedinUrl(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">GitHub URL</label>
              <input
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Portfolio URL</label>
              <input
                value={portfolioUrl}
                onChange={(e) => setPortfolioUrl(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
          </div>
          <button
            onClick={saveProfile}
            disabled={saving}
            className="mt-6 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Personal Info"}
          </button>
        </section>
      )}

      {/* Work & Education Tab */}
      {activeTab === "work" && (
        <section className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold mb-4">Work & Education</h2>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Current Company</label>
                <input
                  value={currentCompany}
                  onChange={(e) => setCurrentCompany(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Current Title</label>
                <input
                  value={currentTitle}
                  onChange={(e) => setCurrentTitle(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Years of Experience</label>
              <input
                type="number"
                value={yearsExperience}
                onChange={(e) => setYearsExperience(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Education Level</label>
              <select
                value={educationLevel}
                onChange={(e) => setEducationLevel(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
              >
                <option value="">Select...</option>
                <option value="bachelors">Bachelor&apos;s</option>
                <option value="masters">Master&apos;s</option>
                <option value="phd">PhD</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">School Name</label>
              <input
                value={schoolName}
                onChange={(e) => setSchoolName(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Degree</label>
                <input
                  value={degree}
                  onChange={(e) => setDegree(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Graduation Year</label>
                <input
                  type="number"
                  value={graduationYear}
                  onChange={(e) => setGraduationYear(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Work Authorization</label>
              <select
                value={workAuthorization}
                onChange={(e) => setWorkAuthorization(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
              >
                <option value="">Select...</option>
                <option value="us_citizen">US Citizen</option>
                <option value="green_card">Green Card</option>
                <option value="h1b">H-1B</option>
                <option value="opt">OPT/OPT STEM</option>
                <option value="tn">TN Visa</option>
                <option value="other">Other</option>
              </select>
            </div>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={requiresSponsorship}
                onChange={(e) => setRequiresSponsorship(e.target.checked)}
                className="rounded"
              />
              <span className="text-sm">Will require visa sponsorship</span>
            </label>

            <hr className="my-2" />
            <p className="text-sm text-gray-500">EEO Information (optional)</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Gender</label>
                <select
                  value={gender}
                  onChange={(e) => setGender(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg"
                >
                  <option value="">Select...</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                  <option value="non_binary">Non-binary</option>
                  <option value="decline">Decline to self-identify</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Race/Ethnicity</label>
                <select
                  value={raceEthnicity}
                  onChange={(e) => setRaceEthnicity(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg"
                >
                  <option value="">Select...</option>
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
          </div>
          <button
            onClick={saveWorkEducation}
            disabled={saving}
            className="mt-6 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Work & Education"}
          </button>
        </section>
      )}

      {/* Job Preferences Tab */}
      {activeTab === "preferences" && (
        <section className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold mb-4">Job Preferences</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Target Roles</label>
              <div className="flex flex-wrap gap-2">
                {ROLE_PRESETS.map((title) => (
                  <button
                    key={title}
                    onClick={() => toggleTitle(title)}
                    className={`px-3 py-1 rounded-full text-sm border transition-colors ${
                      targetTitles.includes(title)
                        ? "bg-brand-600 text-white border-brand-600"
                        : "bg-white text-gray-700 border-gray-300 hover:border-brand-500"
                    }`}
                  >
                    {title}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Excluded Companies (comma separated)
              </label>
              <input
                value={excludedCompanies}
                onChange={(e) => setExcludedCompanies(e.target.value)}
                placeholder="e.g. Cisco, Palantir"
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Minimum Salary (USD)
              </label>
              <input
                type="number"
                value={minSalary}
                onChange={(e) => setMinSalary(e.target.value)}
                placeholder="e.g. 120000"
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={remoteOnly}
                onChange={(e) => setRemoteOnly(e.target.checked)}
                className="rounded"
              />
              <span className="text-sm">Remote only</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={autoApply}
                onChange={(e) => setAutoApply(e.target.checked)}
                className="rounded"
              />
              <span className="text-sm">Auto-apply to matching jobs (recommended)</span>
            </label>
          </div>
          <button
            onClick={savePreferences}
            disabled={saving}
            className="mt-6 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Preferences"}
          </button>
        </section>
      )}

      {/* Resumes Tab */}
      {activeTab === "resumes" && (
        <section className="space-y-6">
          {/* Existing resumes */}
          <div className="bg-white rounded-xl border p-6">
            <h2 className="font-semibold mb-4">Your Resumes</h2>
            {resumes.length === 0 ? (
              <p className="text-sm text-gray-500">No resumes uploaded yet.</p>
            ) : (
              <div className="space-y-3">
                {resumes.map((resume) => (
                  <div
                    key={resume.id}
                    className="flex items-center justify-between p-3 border rounded-lg"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium truncate">
                          {resume.file_name}
                        </span>
                        {resume.is_default && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-brand-50 text-brand-700 rounded-full">
                            Default
                          </span>
                        )}
                      </div>
                      {resume.target_keywords && resume.target_keywords.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {resume.target_keywords.map((kw) => (
                            <span
                              key={kw}
                              className="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full"
                            >
                              {kw}
                            </span>
                          ))}
                        </div>
                      )}
                      <p className="text-xs text-gray-400 mt-1">
                        Uploaded {new Date(resume.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 ml-4">
                      {!resume.is_default && (
                        <button
                          onClick={() => setDefaultResume(resume.id)}
                          className="px-3 py-1 text-xs border border-brand-600 text-brand-600 rounded-lg hover:bg-brand-50"
                        >
                          Set Default
                        </button>
                      )}
                      <button
                        onClick={() => deleteResume(resume.id)}
                        className="px-3 py-1 text-xs border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Upload new resume */}
          <div className="bg-white rounded-xl border p-6">
            <h2 className="font-semibold mb-4">Upload New Resume</h2>
            <div className="space-y-4">
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center">
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
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Target Roles (comma separated)
                </label>
                <input
                  value={resumeTargetRoles}
                  onChange={(e) => setResumeTargetRoles(e.target.value)}
                  placeholder="e.g. AI Engineer, ML Engineer"
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={resumeIsDefault}
                  onChange={(e) => setResumeIsDefault(e.target.checked)}
                  className="rounded"
                />
                <span className="text-sm">Set as default resume</span>
              </label>
              <button
                onClick={uploadResume}
                disabled={uploading || !resumeFile}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
              >
                {uploading ? "Uploading..." : "Upload Resume"}
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Telegram Tab */}
      {activeTab === "telegram" && (
        <section className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold mb-4">Telegram Notifications</h2>
          <p className="text-sm text-gray-500 mb-4">
            Message <span className="font-mono">@AutoApplyBot</span> with{" "}
            <span className="font-mono">/start</span>, then enter your chat ID below to receive
            notifications when applications are submitted.
          </p>
          <div className="flex gap-4">
            <input
              placeholder="Telegram Chat ID"
              value={telegramChatId}
              onChange={(e) => setTelegramChatId(e.target.value)}
              className="flex-1 px-3 py-2 border rounded-lg"
            />
            <button
              onClick={saveTelegram}
              disabled={saving || !telegramChatId}
              className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Connect"}
            </button>
          </div>
          {telegramChatId && (
            <button
              onClick={disconnectTelegram}
              disabled={saving}
              className="mt-3 text-sm text-red-600 hover:text-red-700"
            >
              Disconnect Telegram
            </button>
          )}
        </section>
      )}

      {/* Worker & LLM Tab */}
      {activeTab === "worker" && (
        <section className="bg-white rounded-xl border p-6 space-y-6">
          <h2 className="font-semibold">Worker & LLM Configuration</h2>
          <p className="text-sm text-gray-500">
            These settings sync automatically with your worker. Changes take effect on the next poll cycle.
          </p>

          {/* Level 1: User-Facing LLM */}
          <div className="border rounded-lg p-4">
            <h3 className="font-medium mb-3">Level 1: User-Facing LLM</h3>
            <p className="text-xs text-gray-500 mb-3">Powers chat and AI profile import</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">Provider</label>
                <select
                  value={workerConfig.llm_provider}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, llm_provider: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                >
                  <option value="none">None (manual)</option>
                  <option value="anthropic">Claude (Anthropic)</option>
                  <option value="openai">GPT (OpenAI)</option>
                  <option value="google">Gemini (Google)</option>
                  <option value="ollama">Local (Ollama)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Model</label>
                <select
                  value={workerConfig.llm_model}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, llm_model: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                >
                  {workerConfig.llm_provider === "anthropic" && (
                    <>
                      <option value="claude-sonnet-4-6">Claude Sonnet 4.6 (recommended)</option>
                      <option value="claude-opus-4-6">Claude Opus 4.6</option>
                      <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5</option>
                    </>
                  )}
                  {workerConfig.llm_provider === "openai" && (
                    <>
                      <option value="gpt-4.1">GPT-4.1 (recommended)</option>
                      <option value="gpt-4.1-mini">GPT-4.1 Mini</option>
                      <option value="gpt-4.1-nano">GPT-4.1 Nano</option>
                      <option value="o3">o3</option>
                    </>
                  )}
                  {workerConfig.llm_provider === "google" && (
                    <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                  )}
                  {workerConfig.llm_provider === "ollama" && (
                    <>
                      <option value="llama3.1:8b">Llama 3.1 8B</option>
                      <option value="llama3.1:70b">Llama 3.1 70B</option>
                      <option value="mistral:7b">Mistral 7B</option>
                    </>
                  )}
                  {workerConfig.llm_provider === "none" && (
                    <option value="">N/A</option>
                  )}
                </select>
              </div>
            </div>
            {workerConfig.llm_provider !== "none" && workerConfig.llm_provider !== "ollama" && (
              <div className="mt-3">
                <label className="block text-sm font-medium mb-1">
                  API Key {workerConfig.llm_api_key_preview && (
                    <span className="text-xs text-gray-400 font-normal">
                      (current: {workerConfig.llm_api_key_preview})
                    </span>
                  )}
                </label>
                <input
                  type="password"
                  value={newLlmApiKey}
                  onChange={(e) => setNewLlmApiKey(e.target.value)}
                  placeholder="Enter new key to update (leave blank to keep current)"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
            )}
          </div>

          {/* Level 2: Backend LLM */}
          <div className="border rounded-lg p-4">
            <h3 className="font-medium mb-3">Level 2: Backend LLM</h3>
            <p className="text-xs text-gray-500 mb-3">Powers form filling, resume tailoring, cover letters</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">Provider</label>
                <select
                  value={workerConfig.llm_backend_provider}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, llm_backend_provider: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                >
                  <option value="none">None</option>
                  <option value="anthropic">Claude (Anthropic)</option>
                  <option value="openai">GPT (OpenAI)</option>
                  <option value="google">Gemini (Google)</option>
                  <option value="ollama">Local (Ollama)</option>
                  <option value="same">Same as Level 1</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Model</label>
                <select
                  value={workerConfig.llm_backend_model}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, llm_backend_model: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                >
                  {workerConfig.llm_backend_provider === "anthropic" && (
                    <>
                      <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
                      <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5 (cheaper)</option>
                    </>
                  )}
                  {workerConfig.llm_backend_provider === "openai" && (
                    <>
                      <option value="gpt-4.1-mini">GPT-4.1 Mini (recommended)</option>
                      <option value="gpt-4.1-nano">GPT-4.1 Nano (cheapest)</option>
                    </>
                  )}
                  {workerConfig.llm_backend_provider === "google" && (
                    <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
                  )}
                  {workerConfig.llm_backend_provider === "ollama" && (
                    <option value="llama3.1:8b">Llama 3.1 8B</option>
                  )}
                  {(workerConfig.llm_backend_provider === "none" || workerConfig.llm_backend_provider === "same") && (
                    <option value="">N/A</option>
                  )}
                </select>
              </div>
            </div>
            {workerConfig.llm_backend_provider !== "none" && workerConfig.llm_backend_provider !== "same" && workerConfig.llm_backend_provider !== "ollama" && (
              <div className="mt-3">
                <label className="block text-sm font-medium mb-1">
                  API Key {workerConfig.llm_backend_api_key_preview && (
                    <span className="text-xs text-gray-400 font-normal">
                      (current: {workerConfig.llm_backend_api_key_preview})
                    </span>
                  )}
                </label>
                <input
                  type="password"
                  value={newBackendApiKey}
                  onChange={(e) => setNewBackendApiKey(e.target.value)}
                  placeholder="Enter new key to update (leave blank to keep current)"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
            )}
          </div>

          {/* LLM Features */}
          <div className="border rounded-lg p-4">
            <h3 className="font-medium mb-3">LLM Features</h3>
            <div className="space-y-3">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={workerConfig.resume_tailoring}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, resume_tailoring: e.target.checked })}
                  className="rounded"
                />
                <div>
                  <span className="text-sm font-medium">Resume Tailoring</span>
                  <p className="text-xs text-gray-500">LLM customizes resume for each job</p>
                </div>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={workerConfig.cover_letters}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, cover_letters: e.target.checked })}
                  className="rounded"
                />
                <div>
                  <span className="text-sm font-medium">Auto Cover Letters</span>
                  <p className="text-xs text-gray-500">Generate cover letters per application</p>
                </div>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={workerConfig.smart_answers}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, smart_answers: e.target.checked })}
                  className="rounded"
                />
                <div>
                  <span className="text-sm font-medium">Smart Form Answers</span>
                  <p className="text-xs text-gray-500">LLM answers &quot;Why do you want to work here?&quot; etc.</p>
                </div>
              </label>
              <div>
                <label className="block text-sm font-medium mb-1">Monthly LLM Spend Limit ($)</label>
                <input
                  type="number"
                  value={workerConfig.monthly_limit}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, monthly_limit: parseInt(e.target.value) || 0 })}
                  className="w-32 px-3 py-2 border rounded-lg text-sm"
                />
                <span className="text-xs text-gray-500 ml-2">0 = unlimited</span>
              </div>
            </div>
          </div>

          {/* Worker Settings */}
          <div className="border rounded-lg p-4">
            <h3 className="font-medium mb-3">Worker Settings</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">Worker ID</label>
                <input
                  type="text"
                  value={workerConfig.worker_id}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, worker_id: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Max Daily Applications</label>
                <input
                  type="number"
                  value={workerConfig.max_daily_apps}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, max_daily_apps: parseInt(e.target.value) || 5 })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Poll Interval (seconds)</label>
                <input
                  type="number"
                  value={workerConfig.poll_interval}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, poll_interval: parseInt(e.target.value) || 10 })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Apply Cooldown (seconds)</label>
                <input
                  type="number"
                  value={workerConfig.apply_cooldown}
                  onChange={(e) => setWorkerConfig({ ...workerConfig, apply_cooldown: parseInt(e.target.value) || 30 })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
            </div>
            <label className="flex items-center gap-3 mt-3 cursor-pointer">
              <input
                type="checkbox"
                checked={workerConfig.auto_apply}
                onChange={(e) => setWorkerConfig({ ...workerConfig, auto_apply: e.target.checked })}
                className="rounded"
              />
              <span className="text-sm font-medium">Auto-apply enabled</span>
            </label>
          </div>

          <button
            onClick={async () => {
              setSaving(true);
              const payload: Record<string, unknown> = { ...workerConfig };
              // Only send API keys if user entered new ones
              if (newLlmApiKey) payload.llm_api_key = newLlmApiKey;
              if (newBackendApiKey) payload.llm_backend_api_key = newBackendApiKey;
              // Remove preview fields
              delete payload.llm_api_key_preview;
              delete payload.llm_backend_api_key_preview;

              const res = await fetch("/api/settings/worker-config", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
              });
              const json = await res.json();
              if (res.ok) {
                setWorkerConfig(json.data.config);
                setNewLlmApiKey("");
                setNewBackendApiKey("");
                showMessage("Worker config saved! Changes will sync on next poll.");
              } else {
                showMessage(json.error || "Failed to save", "error");
              }
              setSaving(false);
            }}
            disabled={saving}
            className="w-full py-2.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Worker & LLM Config"}
          </button>
        </section>
      )}

      {/* Billing Tab */}
      {activeTab === "billing" && (
        <section className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold mb-4">Billing</h2>
          <p className="text-sm text-gray-500 mb-6">
            Current plan:{" "}
            <span className="font-medium capitalize text-gray-900">{tier}</span>
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className={`border rounded-xl p-4 ${tier === "free" ? "border-brand-600 bg-brand-50" : ""}`}>
              <h3 className="font-semibold">Free</h3>
              <p className="text-2xl font-bold mt-1">$0<span className="text-sm font-normal text-gray-500">/mo</span></p>
              <p className="text-xs text-gray-500 mt-2">5 applications/day</p>
              {tier === "free" && (
                <p className="mt-3 text-xs font-medium text-brand-600">Current Plan</p>
              )}
            </div>
            <div className={`border rounded-xl p-4 ${tier === "starter" ? "border-brand-600 bg-brand-50" : ""}`}>
              <h3 className="font-semibold">Starter</h3>
              <p className="text-2xl font-bold mt-1">$15<span className="text-sm font-normal text-gray-500">/mo</span></p>
              <p className="text-xs text-gray-500 mt-2">25 applications/day</p>
              {tier === "starter" ? (
                <p className="mt-3 text-xs font-medium text-brand-600">Current Plan</p>
              ) : (
                <a
                  href="/api/stripe/checkout?tier=starter"
                  className="mt-3 block text-center px-3 py-1.5 border border-brand-600 text-brand-600 rounded-lg text-sm font-medium hover:bg-brand-50"
                >
                  {tier === "pro" ? "Downgrade" : "Upgrade"}
                </a>
              )}
            </div>
            <div className={`border rounded-xl p-4 ${tier === "pro" ? "border-brand-600 bg-brand-50" : ""}`}>
              <h3 className="font-semibold">Pro</h3>
              <p className="text-2xl font-bold mt-1">$29<span className="text-sm font-normal text-gray-500">/mo</span></p>
              <p className="text-xs text-gray-500 mt-2">Unlimited applications</p>
              {tier === "pro" ? (
                <p className="mt-3 text-xs font-medium text-brand-600">Current Plan</p>
              ) : (
                <a
                  href="/api/stripe/checkout?tier=pro"
                  className="mt-3 block text-center px-3 py-1.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
                >
                  Upgrade
                </a>
              )}
            </div>
          </div>
          {tier !== "free" && (
            <a
              href="/api/stripe/portal"
              className="mt-4 inline-block text-sm text-gray-500 hover:text-gray-700 underline"
            >
              Manage subscription in Stripe
            </a>
          )}
        </section>
      )}
    </div>
  );
}
