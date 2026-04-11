"use client";

import { useEffect, useState, useCallback } from "react";
import { AI_PROFILE_PROMPT, parseAiResponseSafe } from "@/lib/profile-schema";

const ROLE_PRESETS = [
  "AI Engineer", "ML Engineer", "Data Scientist", "Data Engineer",
  "GenAI Engineer", "NLP Engineer", "Applied Scientist", "Research Engineer",
  "MLOps Engineer", "Computer Vision Engineer", "Analytics Engineer",
  "ML Platform Engineer", "AI Infrastructure Engineer",
];

type Tab = "ai-import" | "personal" | "work" | "preferences" | "resumes" | "integrations" | "telegram" | "email" | "worker" | "billing";

// Integrations tab — Telegram bot token + chat ID, Gmail email + app
// password, AgentMail API key, Finetune Resume API key. All stored
// encrypted in user_profiles.integrations_encrypted via /api/settings/
// integrations. Same fields are readable by the desktop session-start
// sync loop, so changes here propagate to the running ApplyLoop app
// within 5 minutes (or at next restart, whichever comes first).
interface IntegrationFieldDef {
  key: "telegram_bot_token" | "telegram_chat_id" | "gmail_email" | "gmail_app_password" | "agentmail_api_key" | "finetune_resume_api_key";
  label: string;
  sample: string;
  help: string;
  secret: boolean;
}
const INTEGRATION_FIELD_DEFS: IntegrationFieldDef[] = [
  {
    key: "telegram_bot_token",
    label: "Telegram Bot Token",
    sample: "1234567890:ABCdef-GhIJklMn-oPqRsTUv_WxYz",
    help: "From @BotFather: Telegram → /newbot → paste the full <bot_id>:<secret> line.",
    secret: true,
  },
  {
    key: "telegram_chat_id",
    label: "Telegram Chat ID",
    sample: "123456789  (or -1001234567890 for a group)",
    help: "Start a chat with your bot, send any message, visit https://api.telegram.org/bot<token>/getUpdates, look for 'chat':{'id': NUMBER.",
    secret: false,
  },
  {
    key: "gmail_email",
    label: "Gmail Address",
    sample: "your.name@gmail.com",
    help: "The Gmail address ApplyLoop will read job-reply emails from.",
    secret: false,
  },
  {
    key: "gmail_app_password",
    label: "Gmail App Password",
    sample: "abcd efgh ijkl mnop",
    help: "16-char Google App Password (NOT your regular Gmail password). Generate at https://myaccount.google.com/apppasswords after enabling 2FA.",
    secret: true,
  },
  {
    key: "agentmail_api_key",
    label: "AgentMail API Key",
    sample: "am_live_xxxxxxxxxxxxxxxxxxxx",
    help: "For disposable inboxes used during application verification. Sign up at https://agentmail.to/dashboard.",
    secret: true,
  },
  {
    key: "finetune_resume_api_key",
    label: "Finetune Resume API Key",
    sample: "fr_live_xxxxxxxxxxxxxxxxxxxx",
    help: "For per-job tailored resume generation. The service already has your base resume from signup.",
    secret: true,
  },
];
// AI_PROFILE_PROMPT now imported from @/lib/profile-schema above so there's
// one source of truth. Previously this file had its own local copy that
// drifted significantly from the onboarding copy — the settings one lacked
// the "extract ALL work_experience / education / skills" rules entirely,
// so even when users pasted a rich AI response here, the importer dropped
// the arrays on the floor.

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

  // Integrations (Telegram bot + chat, Gmail email+app_password, AgentMail, Finetune)
  // Two maps: `integrationsState` is what the server told us (masked + set flag),
  // and `integrationsDraft` is what the user has typed but not yet saved.
  const [integrationsState, setIntegrationsState] = useState<Record<string, { set: boolean; mask: string }>>({});
  const [integrationsDraft, setIntegrationsDraft] = useState<Record<string, string>>({});
  const [integrationsLoading, setIntegrationsLoading] = useState(false);
  const [integrationsSaving, setIntegrationsSaving] = useState(false);

  // Telegram
  const [telegramChatId, setTelegramChatId] = useState("");
  const [telegramTesting, setTelegramTesting] = useState(false);

  // Gmail
  const [gmailConnected, setGmailConnected] = useState(false);

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
      setGmailConnected(profileData.data?.gmail_connected || false);

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

    // Load integrations (masked) separately so the failure of this specific
    // endpoint doesn't block the whole page from rendering. If the user's
    // Supabase project hasn't run the 010_user_integrations migration, this
    // returns a 500 with a helpful message — we surface it in the tab.
    setIntegrationsLoading(true);
    fetch("/api/settings/integrations")
      .then((r) => r.json())
      .then((body) => {
        if (body?.data?.integrations) {
          setIntegrationsState(body.data.integrations);
        }
      })
      .catch(() => {
        // silent — the tab renders with "(not set)" for everything
      })
      .finally(() => setIntegrationsLoading(false));
  }, []);

  async function saveIntegrations() {
    const dirty = Object.entries(integrationsDraft).filter(([, v]) => v && v.trim() !== "");
    if (dirty.length === 0) {
      showMessage("No changes to save.", "error");
      return;
    }
    setIntegrationsSaving(true);
    try {
      const res = await fetch("/api/settings/integrations", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(dirty)),
      });
      const body = await res.json();
      if (!res.ok) {
        showMessage(body?.message || "Failed to save integrations", "error");
      } else {
        setIntegrationsState(body.data.integrations || {});
        setIntegrationsDraft({});
        showMessage(`Saved: ${(body.data.updated || []).join(", ")}`);
      }
    } catch (e) {
      showMessage(e instanceof Error ? e.message : "Failed to save integrations", "error");
    } finally {
      setIntegrationsSaving(false);
    }
  }

  async function clearIntegrationField(key: string) {
    setIntegrationsSaving(true);
    try {
      const res = await fetch("/api/settings/integrations", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: "" }),
      });
      const body = await res.json();
      if (!res.ok) {
        showMessage(body?.message || "Failed to clear", "error");
      } else {
        setIntegrationsState(body.data.integrations || {});
        setIntegrationsDraft((d) => { const next = { ...d }; delete next[key]; return next; });
        showMessage(`${key} cleared`);
      }
    } catch (e) {
      showMessage(e instanceof Error ? e.message : "Failed to clear", "error");
    } finally {
      setIntegrationsSaving(false);
    }
  }

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

  async function testTelegram() {
    setTelegramTesting(true);
    try {
      const res = await fetch("/api/settings/telegram/test", { method: "POST" });
      if (res.ok) showMessage("Test notification sent! Check your Telegram.");
      else {
        const json = await res.json();
        showMessage(json.message || "Failed to send test notification", "error");
      }
    } catch {
      showMessage("Failed to send test notification", "error");
    }
    setTelegramTesting(false);
  }

  async function disconnectGmail() {
    setSaving(true);
    const res = await fetch("/api/settings/gmail/disconnect", { method: "DELETE" });
    setSaving(false);
    if (res.ok) {
      setGmailConnected(false);
      showMessage("Gmail disconnected");
    } else {
      showMessage("Failed to disconnect Gmail", "error");
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
      // Tolerant parse: strips markdown fences, line/block comments, trailing
      // commas, prose wrapping. Applies our default values (work_auth,
      // sponsorship, disability, salary range, etc.) for missing/empty fields.
      // Never throws — on a totally-unparseable input it still returns an
      // object with defaults so the user can save and edit.
      const result = parseAiResponseSafe(aiResponse);
      const data = result.profile as Record<string, unknown>;
      const pf = result.prefs as Record<string, unknown>;
      const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));

      if (!result.ok && result.error) {
        showMessage(result.error, "error");
        // Still apply defaults below.
      }

      // Populate form state
      if (str(data.first_name)) setFirstName(str(data.first_name));
      if (str(data.last_name)) setLastName(str(data.last_name));
      if (str(data.phone)) setPhone(str(data.phone));
      if (str(data.linkedin_url)) setLinkedinUrl(str(data.linkedin_url));
      if (str(data.github_url)) setGithubUrl(str(data.github_url));
      if (str(data.portfolio_url)) setPortfolioUrl(str(data.portfolio_url));
      if (str(data.current_company)) setCurrentCompany(str(data.current_company));
      if (str(data.current_title)) setCurrentTitle(str(data.current_title));
      if (data.years_experience != null) setYearsExperience(str(data.years_experience));
      if (str(data.education_level)) setEducationLevel(str(data.education_level));
      if (str(data.school_name)) setSchoolName(str(data.school_name));
      if (str(data.degree)) setDegree(str(data.degree));
      if (data.graduation_year != null) setGraduationYear(str(data.graduation_year));
      if (str(data.work_authorization)) setWorkAuthorization(str(data.work_authorization));
      if (typeof data.requires_sponsorship === "boolean") setRequiresSponsorship(data.requires_sponsorship);
      if (str(data.gender)) setGender(str(data.gender));
      if (str(data.race_ethnicity)) setRaceEthnicity(str(data.race_ethnicity));
      if (Array.isArray(pf.target_titles) && pf.target_titles.length) setTargetTitles(pf.target_titles as string[]);
      if (Array.isArray(pf.excluded_companies)) setExcludedCompanies((pf.excluded_companies as string[]).join(", "));
      if (pf.min_salary != null) setMinSalary(str(pf.min_salary));
      if (typeof pf.remote_only === "boolean") setRemoteOnly(pf.remote_only);
      if (typeof pf.auto_apply === "boolean") setAutoApply(pf.auto_apply);

      if (result.defaulted.length > 0) {
        console.info(`[settings] Applied defaults for: ${result.defaulted.join(", ")}`);
      }

      // Save profile + preferences to backend. This includes the array
      // fields (work_experience, skills, education, answer_key_json) that
      // the old whitelist silently dropped — they're now accepted by the
      // /api/settings/profile PUT handler.
      setSaving(true);
      const profileBody: Record<string, unknown> = {
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
      };
      // The shared parser splits parsed data into result.profile (user_profiles
      // columns) and result.prefs (user_job_preferences columns). PUT each
      // to its respective endpoint. Only include array fields when non-empty
      // so we never overwrite existing cloud data with []s.
      if (Array.isArray(data.work_experience) && (data.work_experience as unknown[]).length > 0) {
        profileBody.work_experience = data.work_experience;
      }
      if (Array.isArray(data.skills) && (data.skills as unknown[]).length > 0) {
        profileBody.skills = data.skills;
      }
      if (Array.isArray(data.education) && (data.education as unknown[]).length > 0) {
        profileBody.education = data.education;
      }
      if (data.answer_key_json && typeof data.answer_key_json === "object") {
        profileBody.answer_key_json = data.answer_key_json;
      }
      // EEO: defaults are already applied by parseAiResponseSafe, so these
      // are always set — use the normalized values.
      if (data.veteran_status) profileBody.veteran_status = data.veteran_status;
      if (data.disability_status) profileBody.disability_status = data.disability_status;
      // The parser ALSO fills default work_authorization / requires_sponsorship
      // / disability_status when missing. Make sure the PUT body reflects
      // those (not the form state) so the user's first save locks in defaults.
      if (data.work_authorization) profileBody.work_authorization = data.work_authorization;
      if (typeof data.requires_sponsorship === "boolean") {
        profileBody.requires_sponsorship = data.requires_sponsorship;
      }

      const prefsBody: Record<string, unknown> = {
        target_titles: Array.isArray(pf.target_titles) && (pf.target_titles as unknown[]).length > 0
          ? pf.target_titles
          : targetTitles,
        excluded_companies: Array.isArray(pf.excluded_companies)
          ? pf.excluded_companies
          : excludedCompanies.split(",").map((s: string) => s.trim()).filter(Boolean),
        min_salary: pf.min_salary != null ? parseInt(str(pf.min_salary)) : null,
        remote_only: typeof pf.remote_only === "boolean" ? pf.remote_only : remoteOnly,
        auto_apply: typeof pf.auto_apply === "boolean" ? pf.auto_apply : autoApply,
      };
      if (pf.max_salary != null) prefsBody.max_salary = parseInt(str(pf.max_salary));
      if (Array.isArray(pf.preferred_locations)) prefsBody.preferred_locations = pf.preferred_locations;

      const [profileRes, prefsRes] = await Promise.all([
        fetch("/api/settings/profile", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(profileBody),
        }),
        fetch("/api/settings/preferences", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(prefsBody),
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
    { key: "integrations", label: "API Keys" },
    { key: "telegram", label: "Telegram" },
    { key: "email", label: "Email" },
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

      {/* Integrations Tab — API keys for Telegram bot, Gmail app password, AgentMail, Finetune Resume */}
      {activeTab === "integrations" && (
        <section className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold mb-2">API Keys & Credentials</h2>
          <p className="text-sm text-gray-600 mb-4">
            These are stored encrypted in your profile and synced down to the desktop app automatically.
            Edit any field to update; leave blank to skip. Changes propagate to your running desktop session within 5 minutes.
          </p>

          {integrationsLoading && (
            <p className="text-sm text-gray-500 mb-4">Loading current values...</p>
          )}

          <div className="space-y-5">
            {INTEGRATION_FIELD_DEFS.map((def) => {
              const state = integrationsState[def.key];
              const draft = integrationsDraft[def.key] ?? "";
              const isSet = state?.set;
              return (
                <div key={def.key}>
                  <label className="block text-sm font-medium text-gray-900 mb-1">
                    {def.label}
                    {isSet && (
                      <span className="ml-2 text-xs font-normal text-green-700">
                        ✓ saved ({state?.mask})
                      </span>
                    )}
                    {!isSet && (
                      <span className="ml-2 text-xs font-normal text-gray-400">(not set)</span>
                    )}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type={def.secret ? "password" : "text"}
                      placeholder={def.sample}
                      value={draft}
                      onChange={(e) =>
                        setIntegrationsDraft((d) => ({ ...d, [def.key]: e.target.value }))
                      }
                      className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
                    />
                    {isSet && (
                      <button
                        type="button"
                        onClick={() => clearIntegrationField(def.key)}
                        disabled={integrationsSaving}
                        className="px-3 py-2 text-sm border border-red-300 text-red-700 rounded-lg hover:bg-red-50 disabled:opacity-50"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-gray-500">{def.help}</p>
                </div>
              );
            })}
          </div>

          <div className="mt-6 flex items-center gap-3 border-t pt-4">
            <button
              onClick={saveIntegrations}
              disabled={integrationsSaving || Object.keys(integrationsDraft).filter((k) => (integrationsDraft[k] || "").trim() !== "").length === 0}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {integrationsSaving ? "Saving..." : "Save changes"}
            </button>
            <span className="text-xs text-gray-500">
              {Object.keys(integrationsDraft).filter((k) => (integrationsDraft[k] || "").trim() !== "").length} pending update(s)
            </span>
          </div>
        </section>
      )}

      {/* Telegram Tab */}
      {activeTab === "telegram" && (
        <section className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold mb-4">Telegram Notifications</h2>

          <a
            href="https://t.me/ApplyLoopBot"
            target="_blank"
            rel="noopener"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 mb-4"
          >
            Open @ApplyLoopBot in Telegram
          </a>

          <div className="bg-gray-50 border rounded-lg p-4 mb-4">
            <p className="text-sm font-medium text-gray-700 mb-2">Setup steps:</p>
            <ol className="text-sm text-gray-600 space-y-1 list-decimal list-inside">
              <li>
                Click the link above or search <span className="font-mono">@ApplyLoopBot</span> in Telegram
              </li>
              <li>Send <span className="font-mono">/start</span> to the bot</li>
              <li>The bot replies with your <strong>Chat ID</strong> — copy it</li>
              <li>Paste the Chat ID below and click <strong>Connect</strong></li>
            </ol>
          </div>

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
            <div className="mt-3 flex items-center gap-4">
              <button
                onClick={testTelegram}
                disabled={telegramTesting}
                className="px-4 py-2 border border-brand-600 text-brand-600 rounded-lg text-sm font-medium hover:bg-brand-50 disabled:opacity-50"
              >
                {telegramTesting ? "Sending..." : "Send Test Notification"}
              </button>
              <button
                onClick={disconnectTelegram}
                disabled={saving}
                className="text-sm text-red-600 hover:text-red-700"
              >
                Disconnect Telegram
              </button>
            </div>
          )}
        </section>
      )}

      {/* Email Tab */}
      {activeTab === "email" && (
        <section className="space-y-6">
          <div className="bg-white rounded-xl border p-6">
            <h2 className="font-semibold mb-4">Gmail Connection</h2>
            <p className="text-sm text-gray-500 mb-4">
              Connect Gmail so ApplyLoop can read email verification codes that some companies send
              after you submit an application (e.g., Stripe, Datadog on Greenhouse).
            </p>

            {gmailConnected ? (
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="w-2.5 h-2.5 bg-green-500 rounded-full" />
                  <span className="text-sm font-medium text-green-700">Gmail connected</span>
                </div>
                <button
                  onClick={disconnectGmail}
                  disabled={saving}
                  className="px-4 py-2 border border-red-300 text-red-600 rounded-lg text-sm font-medium hover:bg-red-50 disabled:opacity-50"
                >
                  {saving ? "Disconnecting..." : "Disconnect Gmail"}
                </button>
              </div>
            ) : (
              <a
                href="/api/settings/gmail/connect"
                className="inline-flex items-center gap-2 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                Connect Gmail
              </a>
            )}
          </div>

          <details className="bg-white rounded-xl border">
            <summary className="p-6 cursor-pointer font-semibold text-sm text-gray-700 hover:text-gray-900">
              Self-Hosted: Himalaya CLI (advanced)
            </summary>
            <div className="px-6 pb-6">
              <p className="text-sm text-gray-500 mb-3">
                If you prefer a self-hosted solution instead of Gmail OAuth, you can use the Himalaya CLI
                to read verification emails locally.
              </p>
              <div className="space-y-3">
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-1">1. Install Himalaya</p>
                  <pre className="bg-gray-900 text-green-400 text-sm rounded-lg p-3 overflow-x-auto">
{`# macOS
brew install himalaya

# Linux
curl -sSL https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh | bash`}
                  </pre>
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-1">2. Configure Gmail App Password</p>
                  <p className="text-xs text-gray-500 mb-1">
                    Enable 2FA on your Google account, then generate an App Password at{" "}
                    <a
                      href="https://myaccount.google.com/apppasswords"
                      target="_blank"
                      rel="noopener"
                      className="underline"
                    >
                      myaccount.google.com/apppasswords
                    </a>
                  </p>
                  <pre className="bg-gray-900 text-green-400 text-sm rounded-lg p-3 overflow-x-auto">
{`# ~/Library/Application Support/himalaya/config.toml (macOS)
# ~/.config/himalaya/config.toml (Linux)

[accounts.gmail]
email = "you@gmail.com"
backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.login = "you@gmail.com"
backend.passwd.type = "raw"
backend.passwd.raw = "your-app-password"`}
                  </pre>
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-1">3. Verify</p>
                  <pre className="bg-gray-900 text-green-400 text-sm rounded-lg p-3 overflow-x-auto">
{`himalaya envelope list`}
                  </pre>
                </div>
              </div>
            </div>
          </details>
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
