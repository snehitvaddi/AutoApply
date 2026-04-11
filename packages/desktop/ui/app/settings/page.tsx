"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { AppShell } from "@/components/app-shell"
import {
  getProfile, updateProfile, getPreferences, updatePreferences,
  listResumes, uploadResume, type ResumeRow,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  Save, Loader2, Check, User, Briefcase, Target, Key,
  AlertTriangle, Sparkles, FileText, Copy, Upload, Download,
} from "lucide-react"

type Tab = "ai" | "personal" | "work" | "preferences" | "resume" | "auth"

const tabs: { id: Tab; label: string; icon: typeof User }[] = [
  { id: "ai", label: "AI Import", icon: Sparkles },
  { id: "personal", label: "Personal", icon: User },
  { id: "work", label: "Work & Education", icon: Briefcase },
  { id: "preferences", label: "Job Preferences", icon: Target },
  { id: "resume", label: "Resume", icon: FileText },
  { id: "auth", label: "API Token", icon: Key },
]

// The same prompt the web /onboarding uses. Ports verbatim so users who
// have already cached a response in their AI chat history can reuse it.
const AI_PROFILE_PROMPT = `I'm setting up ApplyLoop — an automated job application bot. I need my COMPLETE professional profile extracted as JSON. Use my resume (paste it below or reference from our past conversations).

IMPORTANT: Include ALL work experiences, ALL education entries, skills, and generate professional answers for common application questions.

Respond with ONLY this JSON (fill everything you know, leave "" for unknown):

{
  "first_name": "",
  "last_name": "",
  "email": "",
  "phone": "",
  "linkedin_url": "",
  "github_url": "",
  "portfolio_url": "",
  "current_company": "",
  "current_title": "",
  "years_experience": 0,
  "work_experience": [
    {"company": "", "title": "", "location": "", "start_date": "Mon YYYY", "end_date": "Present", "achievements": ["bullet 1", "bullet 2"]}
  ],
  "education": [
    {"school": "", "degree": "", "field": "", "start_date": "Mon YYYY", "end_date": "Mon YYYY", "gpa": ""}
  ],
  "skills": ["Python", "PyTorch"],
  "education_level": "masters",
  "school_name": "",
  "degree": "",
  "graduation_year": 0,
  "work_authorization": "us_citizen",
  "requires_sponsorship": false,
  "salary_min": 120000,
  "target_titles": ["AI Engineer", "ML Engineer"],
  "excluded_companies": [],
  "remote_only": false,
  "auto_apply": true
}

Valid values:
- education_level: "bachelors", "masters", "phd", "other"
- work_authorization: "us_citizen", "green_card", "h1b", "opt", "tn", "other"

Include ALL your work experiences (not just current). Include ALL education.`

function Input({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
}) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium text-card-foreground">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      />
    </div>
  )
}

function TextArea({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  rows?: number
}) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium text-card-foreground">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      />
    </div>
  )
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("ai")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [profile, setProfile] = useState<Record<string, string>>({})
  const [prefs, setPrefs] = useState<Record<string, string>>({})
  const [token, setToken] = useState("")
  const [maskedToken, setMaskedToken] = useState("")

  // AI Import state
  const [aiResponse, setAiResponse] = useState("")
  const [aiError, setAiError] = useState<string | null>(null)
  const [aiParsed, setAiParsed] = useState(false)
  const [promptCopied, setPromptCopied] = useState(false)

  // Resume state
  const [resumes, setResumes] = useState<ResumeRow[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadOk, setUploadOk] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadData = useCallback(async () => {
    try {
      const [profileRes, prefsRes, resumeRes] = await Promise.allSettled([
        getProfile(),
        getPreferences(),
        listResumes(),
      ])
      if (profileRes.status === "fulfilled") {
        const raw = profileRes.value?.data as Record<string, unknown> ?? {}
        const nested = raw?.data as Record<string, unknown> ?? raw
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const p = (nested?.profile ?? nested) as any
        setProfile({
          first_name: String(p?.first_name ?? ""),
          last_name: String(p?.last_name ?? ""),
          email: String(p?.email ?? ""),
          phone: String(p?.phone ?? ""),
          linkedin_url: String(p?.linkedin_url ?? ""),
          github_url: String(p?.github_url ?? ""),
          portfolio_url: String(p?.portfolio_url ?? ""),
          location: String(p?.location ?? ""),
          current_company: String(p?.current_company ?? ""),
          current_title: String(p?.current_title ?? ""),
          years_experience: String(p?.years_experience ?? ""),
          education_level: String(p?.education_level ?? ""),
          school_name: String(p?.school_name ?? ""),
          degree: String(p?.degree ?? ""),
          graduation_year: String(p?.graduation_year ?? ""),
          work_authorization: String(p?.work_authorization ?? ""),
          requires_sponsorship: p?.requires_sponsorship ? "Yes" : "No",
        })
      }
      if (prefsRes.status === "fulfilled") {
        const rawP = prefsRes.value?.data as Record<string, unknown> ?? {}
        const nestedP = rawP?.data as Record<string, unknown> ?? rawP
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const pr = (nestedP?.preferences ?? nestedP) as any
        setPrefs({
          target_titles: Array.isArray(pr.target_titles) ? pr.target_titles.join(", ") : (pr.target_titles ?? ""),
          excluded_companies: Array.isArray(pr.excluded_companies) ? pr.excluded_companies.join(", ") : (pr.excluded_companies ?? ""),
          min_salary: String(pr.min_salary ?? ""),
          remote_only: pr.remote_only ? "Yes" : "No",
          auto_apply: pr.auto_apply ? "Yes" : "No",
        })
      }
      if (resumeRes.status === "fulfilled") {
        const rr = resumeRes.value?.data as { resumes?: ResumeRow[] } | undefined
        setResumes(rr?.resumes || [])
      }
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    loadData()
    fetch("/api/auth/token-masked").then(r => r.json()).then(d => {
      if (d.has_token) setMaskedToken(d.masked)
    }).catch(() => {})
  }, [loadData])

  // ── AI Import ────────────────────────────────────────────────────────────

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(AI_PROFILE_PROMPT)
      setPromptCopied(true)
      setTimeout(() => setPromptCopied(false), 2000)
    } catch {
      /* clipboard may be unavailable */
    }
  }

  function parseAiResponse() {
    setAiError(null)
    setAiParsed(false)
    let jsonStr = aiResponse.trim()
    if (!jsonStr) {
      setAiError("Please paste the AI response first.")
      return
    }
    // Strip markdown fences if present
    const fenceMatch = jsonStr.match(/```(?:json)?\s*([\s\S]*?)```/)
    if (fenceMatch) jsonStr = fenceMatch[1].trim()
    // If there's prose wrapping the JSON, grab the first top-level {...} block
    if (!jsonStr.startsWith("{")) {
      const braceStart = jsonStr.indexOf("{")
      const braceEnd = jsonStr.lastIndexOf("}")
      if (braceStart !== -1 && braceEnd > braceStart) {
        jsonStr = jsonStr.slice(braceStart, braceEnd + 1)
      }
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let data: any
    try {
      data = JSON.parse(jsonStr)
    } catch (e) {
      const snippet = jsonStr.slice(0, 60).replace(/\s+/g, " ")
      const reason = e instanceof Error ? e.message : "unknown error"
      setAiError(
        `Could not parse as JSON (${reason}). Starts with: "${snippet}${jsonStr.length > 60 ? "..." : ""}". Make sure you copied only the JSON block.`
      )
      return
    }
    if (!data || typeof data !== "object") {
      setAiError("AI response must be a JSON object (got " + typeof data + ").")
      return
    }

    // Populate profile fields, gated so empty strings don't clobber state
    const nextProfile = { ...profile }
    const setIf = (k: string, v: unknown) => {
      if (v !== undefined && v !== null && String(v) !== "") {
        nextProfile[k] = String(v)
      }
    }
    setIf("first_name", data.first_name)
    setIf("last_name", data.last_name)
    setIf("email", data.email)
    setIf("phone", data.phone)
    setIf("linkedin_url", data.linkedin_url)
    setIf("github_url", data.github_url)
    setIf("portfolio_url", data.portfolio_url)
    setIf("current_company", data.current_company)
    setIf("current_title", data.current_title)
    setIf("years_experience", data.years_experience)
    setIf("education_level", data.education_level)
    setIf("school_name", data.school_name)
    setIf("degree", data.degree)
    setIf("graduation_year", data.graduation_year)
    setIf("work_authorization", data.work_authorization)
    if (data.requires_sponsorship !== undefined) {
      nextProfile.requires_sponsorship = data.requires_sponsorship ? "Yes" : "No"
    }
    setProfile(nextProfile)

    // Populate prefs
    const nextPrefs = { ...prefs }
    if (Array.isArray(data.target_titles) && data.target_titles.length) {
      nextPrefs.target_titles = data.target_titles.join(", ")
    }
    if (Array.isArray(data.excluded_companies)) {
      nextPrefs.excluded_companies = data.excluded_companies.join(", ")
    }
    if (data.salary_min !== undefined) nextPrefs.min_salary = String(data.salary_min)
    if (data.remote_only !== undefined) nextPrefs.remote_only = data.remote_only ? "Yes" : "No"
    if (data.auto_apply !== undefined) nextPrefs.auto_apply = data.auto_apply ? "Yes" : "No"
    setPrefs(nextPrefs)

    setAiParsed(true)
  }

  async function saveAiImport() {
    setSaveError(null)
    setSaving(true)
    try {
      // Persist both profile + preferences in one shot
      await updateProfile(profile)
      await updatePreferences({
        ...prefs,
        target_titles: prefs.target_titles?.split(",").map(s => s.trim()).filter(Boolean),
        excluded_companies: prefs.excluded_companies?.split(",").map(s => s.trim()).filter(Boolean),
        min_salary: prefs.min_salary ? Number(prefs.min_salary) : null,
        remote_only: prefs.remote_only === "Yes",
        auto_apply: prefs.auto_apply === "Yes",
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save profile")
    } finally {
      setSaving(false)
    }
  }

  // ── Resume upload ────────────────────────────────────────────────────────

  async function handleResumeUpload(file: File) {
    setUploadError(null)
    setUploadOk(false)
    setUploading(true)
    try {
      const res = await uploadResume(file, { isDefault: true })
      if (!res.ok) {
        setUploadError(res.error || "Upload failed")
        return
      }
      setUploadOk(true)
      setTimeout(() => setUploadOk(false), 3000)
      // Refresh list
      const list = await listResumes().catch(() => null)
      if (list) setResumes(list.data?.resumes || [])
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed")
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  // ── Standard save handler for Personal/Work/Preferences/Auth ────────────

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      if (activeTab === "personal" || activeTab === "work") {
        await updateProfile(profile)
      } else if (activeTab === "preferences") {
        const data = {
          ...prefs,
          target_titles: prefs.target_titles?.split(",").map((s: string) => s.trim()).filter(Boolean),
          excluded_companies: prefs.excluded_companies?.split(",").map((s: string) => s.trim()).filter(Boolean),
          min_salary: prefs.min_salary ? Number(prefs.min_salary) : null,
          remote_only: prefs.remote_only === "Yes",
          auto_apply: prefs.auto_apply === "Yes",
        }
        await updatePreferences(data)
      } else if (activeTab === "auth") {
        const { saveToken } = await import("@/lib/api")
        await saveToken(token)
      }
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save — check your connection and token")
    } finally { setSaving(false) }
  }

  const updateField = (field: string, value: string) => {
    if (activeTab === "preferences") {
      setPrefs((prev) => ({ ...prev, [field]: value }))
    } else {
      setProfile((prev) => ({ ...prev, [field]: value }))
    }
  }

  if (loading) {
    return (
      <AppShell>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading profile...
        </div>
      </AppShell>
    )
  }

  // The AI tab has its own Save button; the Resume tab has its own Upload.
  // Hide the top-right Save for those two to avoid confusion.
  const showTopSave = activeTab !== "ai" && activeTab !== "resume"

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-foreground">Settings</h1>
          <div className="flex items-center gap-3">
            {saveError && (
              <div className="flex items-center gap-1.5 rounded-lg bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
                <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                <span className="max-w-[260px] truncate" title={saveError}>{saveError}</span>
              </div>
            )}
            {showTopSave && (
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : saved ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                {saved ? "Saved!" : "Save Changes"}
              </button>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 rounded-xl border border-border bg-card p-1 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors whitespace-nowrap",
                activeTab === tab.id
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              )}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="rounded-xl border border-border bg-card p-6">
          {activeTab === "ai" && (
            <div className="space-y-5">
              <div>
                <div className="flex items-start gap-3 rounded-lg border border-primary/20 bg-primary/5 p-4">
                  <Sparkles className="h-5 w-5 flex-shrink-0 text-primary" />
                  <div className="text-sm">
                    <p className="font-semibold text-foreground">Let AI fill your profile in 30 seconds</p>
                    <p className="mt-1 text-muted-foreground">
                      Copy the prompt below, paste it into ChatGPT or Claude along with your resume,
                      and paste the JSON response back here. We&apos;ll extract everything and save it.
                    </p>
                  </div>
                </div>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label className="text-sm font-medium text-card-foreground">Step 1: Copy this prompt</label>
                  <button
                    onClick={copyPrompt}
                    className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-secondary"
                  >
                    <Copy className="h-3 w-3" />
                    {promptCopied ? "Copied!" : "Copy prompt"}
                  </button>
                </div>
                <pre className="max-h-40 overflow-auto rounded-lg bg-muted/30 p-3 text-[11px] text-muted-foreground whitespace-pre-wrap font-mono">
{AI_PROFILE_PROMPT}
                </pre>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-medium text-card-foreground">
                  Step 2: Paste the AI response (JSON)
                </label>
                <textarea
                  value={aiResponse}
                  onChange={(e) => setAiResponse(e.target.value)}
                  placeholder={`{\n  "first_name": "Jane",\n  "last_name": "Doe",\n  ...\n}`}
                  rows={10}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              {aiError && (
                <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                  <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                  <span>{aiError}</span>
                </div>
              )}

              {aiParsed && !aiError && (
                <div className="flex items-start gap-2 rounded-lg border border-success/30 bg-success/5 p-3 text-xs text-success">
                  <Check className="h-4 w-4 flex-shrink-0" />
                  <span>
                    Parsed successfully. Review the fields in the Personal, Work, and Preferences tabs
                    and click <strong>Save &amp; Sync</strong> below when ready.
                  </span>
                </div>
              )}

              <div className="flex items-center gap-3">
                <button
                  onClick={parseAiResponse}
                  className="flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary"
                >
                  <Sparkles className="h-4 w-4" />
                  Parse JSON
                </button>
                <button
                  onClick={saveAiImport}
                  disabled={!aiParsed || saving}
                  className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : saved ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  {saved ? "Saved to cloud!" : "Save & Sync"}
                </button>
              </div>
            </div>
          )}

          {activeTab === "personal" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Input label="First Name" value={profile.first_name ?? ""} onChange={(v) => updateField("first_name", v)} />
              <Input label="Last Name" value={profile.last_name ?? ""} onChange={(v) => updateField("last_name", v)} />
              <Input label="Email" value={profile.email ?? ""} onChange={(v) => updateField("email", v)} type="email" />
              <Input label="Phone" value={profile.phone ?? ""} onChange={(v) => updateField("phone", v)} type="tel" />
              <Input label="Location" value={profile.location ?? ""} onChange={(v) => updateField("location", v)} placeholder="San Francisco, CA" />
              <Input label="LinkedIn URL" value={profile.linkedin_url ?? ""} onChange={(v) => updateField("linkedin_url", v)} placeholder="https://linkedin.com/in/..." />
              <Input label="GitHub URL" value={profile.github_url ?? ""} onChange={(v) => updateField("github_url", v)} placeholder="https://github.com/..." />
              <Input label="Portfolio URL" value={profile.portfolio_url ?? ""} onChange={(v) => updateField("portfolio_url", v)} placeholder="https://..." />
            </div>
          )}

          {activeTab === "work" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Input label="Current Company" value={profile.current_company ?? ""} onChange={(v) => updateField("current_company", v)} />
              <Input label="Current Title" value={profile.current_title ?? ""} onChange={(v) => updateField("current_title", v)} />
              <Input label="Years of Experience" value={profile.years_experience ?? ""} onChange={(v) => updateField("years_experience", v)} type="number" />
              <Input label="Education Level" value={profile.education_level ?? ""} onChange={(v) => updateField("education_level", v)} placeholder="bachelors / masters / phd" />
              <Input label="School Name" value={profile.school_name ?? ""} onChange={(v) => updateField("school_name", v)} placeholder="Stanford University" />
              <Input label="Degree" value={profile.degree ?? ""} onChange={(v) => updateField("degree", v)} placeholder="MS Computer Science" />
              <Input label="Graduation Year" value={profile.graduation_year ?? ""} onChange={(v) => updateField("graduation_year", v)} type="number" />
              <Input label="Work Authorization" value={profile.work_authorization ?? ""} onChange={(v) => updateField("work_authorization", v)} placeholder="us_citizen / green_card / h1b / opt" />
              <Input label="Requires Sponsorship" value={profile.requires_sponsorship ?? ""} onChange={(v) => updateField("requires_sponsorship", v)} placeholder="Yes or No" />
            </div>
          )}

          {activeTab === "preferences" && (
            <div className="space-y-4">
              <TextArea
                label="Target Roles (comma-separated)"
                value={prefs.target_titles ?? ""}
                onChange={(v) => updateField("target_titles", v)}
                placeholder="AI Engineer, ML Engineer, Data Scientist"
              />
              <TextArea
                label="Excluded Companies (comma-separated)"
                value={prefs.excluded_companies ?? ""}
                onChange={(v) => updateField("excluded_companies", v)}
                placeholder="Palantir, Anduril"
              />
              <div className="grid gap-4 sm:grid-cols-3">
                <Input label="Minimum Salary ($)" value={prefs.min_salary ?? ""} onChange={(v) => updateField("min_salary", v)} type="number" />
                <Input label="Remote Only" value={prefs.remote_only ?? ""} onChange={(v) => updateField("remote_only", v)} placeholder="Yes or No" />
                <Input label="Auto Apply" value={prefs.auto_apply ?? ""} onChange={(v) => updateField("auto_apply", v)} placeholder="Yes or No" />
              </div>
            </div>
          )}

          {activeTab === "resume" && (
            <div className="space-y-5">
              <div className="flex items-start gap-3 rounded-lg border border-primary/20 bg-primary/5 p-4">
                <FileText className="h-5 w-5 flex-shrink-0 text-primary" />
                <div className="text-sm">
                  <p className="font-semibold text-foreground">Upload your resume</p>
                  <p className="mt-1 text-muted-foreground">
                    PDF only, 10 MB max. The worker uses this to autofill job applications —
                    without one every apply attempt fails. Multiple uploads are kept in history;
                    the most recent becomes the default.
                  </p>
                </div>
              </div>

              {/* Current resumes list */}
              {resumes.length > 0 && (
                <div>
                  <p className="mb-2 text-sm font-medium text-card-foreground">
                    Your resumes ({resumes.length})
                  </p>
                  <ul className="space-y-2">
                    {resumes.map((r) => (
                      <li
                        key={r.id}
                        className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background px-3 py-2 text-sm"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <FileText className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                          <span className="truncate text-foreground" title={r.file_name}>
                            {r.file_name}
                          </span>
                          {r.is_default && (
                            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                              default
                            </span>
                          )}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {new Date(r.created_at).toLocaleDateString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {resumes.length === 0 && (
                <div className="rounded-lg border border-dashed border-border bg-background/50 p-4 text-center text-sm text-muted-foreground">
                  No resume uploaded yet. The worker will fail every apply until you upload one.
                </div>
              )}

              {/* Upload input */}
              <div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/pdf,.pdf"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) handleResumeUpload(f)
                  }}
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border bg-background px-4 py-6 text-sm font-medium text-foreground hover:bg-secondary disabled:opacity-50"
                >
                  {uploading ? (
                    <>
                      <Loader2 className="h-5 w-5 animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="h-5 w-5" />
                      {resumes.length > 0 ? "Upload a new version" : "Select PDF to upload"}
                    </>
                  )}
                </button>
              </div>

              {uploadError && (
                <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                  <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                  <span>{uploadError}</span>
                </div>
              )}

              {uploadOk && (
                <div className="flex items-start gap-2 rounded-lg border border-success/30 bg-success/5 p-3 text-xs text-success">
                  <Check className="h-4 w-4 flex-shrink-0" />
                  <span>
                    Resume uploaded successfully and synced to the cloud. The worker will now use
                    it for new applications.
                  </span>
                </div>
              )}
            </div>
          )}

          {activeTab === "auth" && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Your API token authenticates the desktop app with the ApplyLoop backend.
                Get it from your dashboard at Settings &rarr; API Token.
              </p>
              {maskedToken && !token && (
                <div className="rounded-lg bg-success/5 border border-success/20 px-4 py-3">
                  <p className="text-xs text-muted-foreground">Current token</p>
                  <p className="mt-1 font-mono text-sm text-success">{maskedToken}</p>
                </div>
              )}
              <Input
                label={maskedToken ? "Replace Token (leave empty to keep current)" : "API Token"}
                value={token}
                onChange={setToken}
                placeholder="al_xxx_yyy..."
                type="password"
              />
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}
