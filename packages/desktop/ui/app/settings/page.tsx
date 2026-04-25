"use client"

import { useState, useEffect, useCallback, useRef, type ReactNode } from "react"
import { useRouter } from "next/navigation"
import { AppShell } from "@/components/app-shell"
import {
  getProfile, updateProfile, getPreferences, updatePreferences,
  listResumes, uploadResume, getSetupStatus,
  getIntegrations, updateIntegrations,
  syncNow,
  type ResumeRow,
} from "@/lib/api"
import { AI_PROFILE_PROMPT, parseAiResponseSafe } from "@/lib/profile-schema"
import { ProfilesTab } from "./ProfilesTab"
import {
  WorkEducationEditor,
  type WorkExperienceRow,
  type EducationRow,
} from "./WorkEducationEditor"
import { cn } from "@/lib/utils"
import {
  Save, Loader2, Check, User, Briefcase, Target, Key,
  AlertTriangle, Sparkles, FileText, Copy, Upload, Download, ArrowLeft,
  Send, Mail, Cpu, CreditCard,
} from "lucide-react"
import {
  Section,
  FormRow,
  PageHeader,
  InlineHint,
  StatusBadge,
  fieldClass,
  buttonClass,
} from "@/components/settings-ui"

type Tab = "ai" | "personal" | "work" | "preferences" | "profiles" | "resume" | "integrations"
  | "telegram" | "email" | "worker" | "billing" | "auth"

// IA mirrors the web sidebar. Profiles is the primary tab. Resumes
// dropped — uploads now live INSIDE each profile card. Work & Education
// is per-bundle (mig 020). API Keys carries only Telegram + AgentMail +
// Finetune; Gmail moved to the per-profile editor. Preferences / Telegram /
// Email tab branches remain in the JSX below for now (tree-shaken in
// prod since they're unreachable via the sidebar).
const tabs: { id: Tab; label: string; icon: typeof User }[] = [
  { id: "profiles", label: "Profiles", icon: Target },
  { id: "personal", label: "Personal", icon: User },
  { id: "integrations", label: "API Keys", icon: Key },
  { id: "worker", label: "Worker & LLM", icon: Cpu },
  { id: "ai", label: "AI Import", icon: Sparkles },
  { id: "billing", label: "Billing", icon: CreditCard },
  { id: "auth", label: "Worker Token", icon: Key },
]

// Integration field definitions — these match packages/web/src/lib/profile-schema.ts
// INTEGRATION_FIELDS list. If you add a field here, also add it to the server-side
// VALIDATORS in packages/web/src/app/api/settings/integrations/route.ts.
interface DesktopIntegrationFieldDef {
  // Gmail moved to per-profile editor; the union no longer includes it.
  key: "telegram_bot_token" | "telegram_chat_id" | "agentmail_api_key" | "finetune_resume_api_key"
  label: string
  sample: string
  help: string
  secret: boolean
}
const DESKTOP_INTEGRATION_FIELDS: DesktopIntegrationFieldDef[] = [
  {
    key: "telegram_bot_token",
    label: "Telegram Bot Token",
    sample: "1234567890:ABCdef-GhIJklMn-oPqRsTUv_WxYz",
    help: "From @BotFather: /newbot → paste the full <bot_id>:<secret> line.",
    secret: true,
  },
  {
    key: "telegram_chat_id",
    label: "Telegram Chat ID",
    sample: "123456789 (or -1001234567890 for a group)",
    help: "Send your bot any message, visit api.telegram.org/bot<token>/getUpdates, copy the chat.id number.",
    secret: false,
  },
  // Gmail moved to per-profile editor — each bundle has its own
  // mailbox + app password. See ProfilesTab "Apply-from Gmail".
  {
    key: "agentmail_api_key",
    label: "AgentMail API Key",
    sample: "am_live_xxxxxxxxxxxxxxxxxxxx",
    help: "Disposable inboxes for application verification. https://agentmail.to/dashboard",
    secret: true,
  },
  {
    key: "finetune_resume_api_key",
    label: "Finetune Resume API Key",
    sample: "fr_live_xxxxxxxxxxxxxxxxxxxx",
    help: "Per-job tailored resume generation. Your base resume is already on the service from signup.",
    secret: true,
  },
]

// AI_PROFILE_PROMPT now imported from @/lib/profile-schema (a byte-identical
// copy of packages/web/src/lib/profile-schema.ts). Previously this file had
// its own local copy that had drifted significantly — missing all the "ALL
// work_experience / education / skills" extraction rules, default values,
// EEO fields, and the generated target_titles instruction. One source of
// truth now, mirrored manually between the web + desktop packages.

// Autolink bare URLs inside integration help strings so users can click
// through instead of copy-pasting (audit-flagged friction). Strip trailing
// punctuation (. , ; : ! ? ) ]) that's almost never part of a URL — a
// user writing "see foo.com." doesn't want the period in the link.
function renderHelpWithLinks(text: string): ReactNode {
  const parts = text.split(/(https?:\/\/[^\s]+)/g);
  return parts.map((part, i) => {
    if (/^https?:\/\//.test(part)) {
      const match = part.match(/^(.*?)([.,;:!?)\]]*)$/);
      const url = match?.[1] || part;
      const trailing = match?.[2] || "";
      return (
        <span key={i}>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-foreground"
          >
            {url}
          </a>
          {trailing}
        </span>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

function Input({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  hint,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  hint?: string
}) {
  return (
    <FormRow label={label} hint={hint}>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={fieldClass}
      />
    </FormRow>
  )
}

function TextArea({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
  hint,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  rows?: number
  hint?: string
}) {
  return (
    <FormRow label={label} hint={hint}>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className={cn(fieldClass, "resize-y min-h-20")}
      />
    </FormRow>
  )
}

export default function SettingsPage() {
  const router = useRouter()
  const [activeTab, setActiveTab] = useState<Tab>("profiles")
  // Mid-setup users land here from the wizard's "Fill in profile" deep-link.
  // We render a banner so they have a one-click way back to the checklist
  // (the wizard wants them to come back once they're done editing).
  const [setupComplete, setSetupComplete] = useState<boolean | null>(null)
  useEffect(() => {
    let cancelled = false
    getSetupStatus()
      .then((s) => { if (!cancelled) setSetupComplete(!!s.setup_complete) })
      .catch(() => { if (!cancelled) setSetupComplete(null) })
    return () => { cancelled = true }
  }, [])

  // Honor ?tab=<id> so the /setup wizard can deep-link to the right tab.
  // Reading from window.location.search in a useEffect (instead of
  // next/navigation's useSearchParams hook) keeps this component
  // statically prerenderable — Next.js 15 fails the build if the hook
  // is used without a Suspense boundary in a static export.
  useEffect(() => {
    if (typeof window === "undefined") return
    const params = new URLSearchParams(window.location.search)
    const tabParam = params.get("tab") as Tab | null
    if (tabParam && tabs.some((t) => t.id === tabParam)) {
      setActiveTab(tabParam)
    }
  }, [])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [profile, setProfile] = useState<Record<string, string>>({})
  // Array-shaped profile data. Kept separate from `profile` (which is
  // Record<string,string> for the flat field editors) so TS doesn't
  // complain and so the scalar Personal/Work fields can save independently
  // from the Work & Education array editor.
  const [workExperience, setWorkExperience] = useState<WorkExperienceRow[]>([])
  const [education, setEducation] = useState<EducationRow[]>([])
  const [skills, setSkills] = useState<string[]>([])
  const [prefs, setPrefs] = useState<Record<string, string>>({})
  const [token, setToken] = useState("")
  const [maskedToken, setMaskedToken] = useState("")

  // Integrations state (Telegram/Gmail/AgentMail/Finetune API keys)
  const [integrationsState, setIntegrationsState] = useState<Record<string, { set: boolean; mask: string }>>({})
  const [integrationsDraft, setIntegrationsDraft] = useState<Record<string, string>>({})
  const [integrationsLoading, setIntegrationsLoading] = useState(false)
  const [integrationsSaving, setIntegrationsSaving] = useState(false)
  const [integrationsMsg, setIntegrationsMsg] = useState<{ text: string; type: "ok" | "err" } | null>(null)

  // On-demand sync state. Fires on mount + when the user clicks the
  // "Refresh" button in the header. syncNow() hits POST /api/sync/now
  // which runs the same pull+push helpers the 5-min background loop runs.
  const [syncing, setSyncing] = useState(false)
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null)

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
        // Hydrate the array fields so the new Work & Education editor
        // can render them. These were previously write-only via AI Import.
        if (Array.isArray(p?.work_experience)) setWorkExperience(p.work_experience as WorkExperienceRow[])
        if (Array.isArray(p?.education)) setEducation(p.education as EducationRow[])
        if (Array.isArray(p?.skills)) setSkills(p.skills as string[])
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

  // Fetch integrations (masked values) from the local FastAPI → cloud.
  // Broken out so the mount flow AND the manual Refresh button both reuse it.
  const refreshIntegrations = useCallback(async () => {
    setIntegrationsLoading(true)
    try {
      const res = await getIntegrations()
      // The /api/integrations endpoint returns { ok, data: { integrations: {...} } }
      // — res.data.integrations, NOT res.data.data.integrations. The old code
      // assumed a nested-data wrapper that the proxy doesn't actually apply,
      // so the integrations always came back empty and the UI showed "(not set)"
      // even when the backend had the full encrypted payload.
      const integrations = res?.data?.integrations
      if (integrations) {
        setIntegrationsState(integrations)
      }
    } catch {
      /* silent — keep whatever we had before */
    } finally {
      setIntegrationsLoading(false)
    }
  }, [])

  // Run a full pull+push sync via the local FastAPI /api/sync/now endpoint,
  // then re-fetch profile / preferences / resumes / integrations so the UI
  // picks up anything that changed on the cloud side. Used by both:
  //
  //   - the mount-time effect (so visiting the Settings page always shows
  //     fresh data without waiting for the 5-min background tick)
  //   - the manual Refresh button in the header
  //
  // Never throws. Uses the syncing state for the spinner indicator. If the
  // sync itself fails (network, migration not applied, etc.) the individual
  // re-fetches still run so the user sees whatever's cached locally.
  const syncAndReload = useCallback(async () => {
    setSyncing(true)
    try {
      try {
        const res = await syncNow()
        const d = res?.data as { data?: { synced_at?: number; errors?: string[] } } | undefined
        if (d?.data?.synced_at) {
          setLastSyncedAt(d.data.synced_at)
        }
      } catch {
        /* swallow — we still want to re-fetch below */
      }
      // Re-fetch everything the Settings page renders from.
      await loadData()
      await refreshIntegrations()
    } finally {
      setSyncing(false)
    }
  }, [loadData, refreshIntegrations])

  useEffect(() => {
    fetch("/api/auth/token-masked").then(r => r.json()).then(d => {
      if (d.has_token) setMaskedToken(d.masked)
    }).catch(() => {})
    // Initial mount: run a full sync then reload. One call covers the
    // "visited the settings tab → get latest" flow the user asked for.
    syncAndReload()
  }, [syncAndReload])

  async function saveIntegrations() {
    const dirty = Object.entries(integrationsDraft).filter(([, v]) => v && v.trim() !== "")
    if (dirty.length === 0) {
      setIntegrationsMsg({ text: "No changes to save.", type: "err" })
      return
    }
    setIntegrationsSaving(true)
    setIntegrationsMsg(null)
    try {
      const res = await updateIntegrations(Object.fromEntries(dirty))
      // /api/integrations PUT returns { ok, data: { updated, integrations } }
      // — top-level 'data' wrapper, no nested 'data.data'. Same fix as
      // refreshIntegrations above.
      const r = res as { error?: string; data?: { updated?: string[]; integrations?: Record<string, { set: boolean; mask: string }> } }
      if (r?.error) {
        setIntegrationsMsg({ text: r.error, type: "err" })
      } else if (r?.data?.integrations) {
        setIntegrationsState(r.data.integrations)
        setIntegrationsDraft({})
        setIntegrationsMsg({ text: `Saved: ${(r.data.updated || []).join(", ")}`, type: "ok" })
        setTimeout(() => setIntegrationsMsg(null), 3000)
      }
    } catch (e) {
      setIntegrationsMsg({ text: e instanceof Error ? e.message : "Save failed", type: "err" })
    } finally {
      setIntegrationsSaving(false)
    }
  }

  async function clearIntegrationField(key: string) {
    setIntegrationsSaving(true)
    try {
      const res = await updateIntegrations({ [key]: "" })
      const r = res as { error?: string; data?: { integrations?: Record<string, { set: boolean; mask: string }> } }
      if (r?.error) {
        setIntegrationsMsg({ text: r.error, type: "err" })
      } else if (r?.data?.integrations) {
        setIntegrationsState(r.data.integrations)
        setIntegrationsDraft((d) => { const next = { ...d }; delete next[key]; return next })
        setIntegrationsMsg({ text: `${key} cleared`, type: "ok" })
        setTimeout(() => setIntegrationsMsg(null), 3000)
      }
    } catch (e) {
      setIntegrationsMsg({ text: e instanceof Error ? e.message : "Clear failed", type: "err" })
    } finally {
      setIntegrationsSaving(false)
    }
  }

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

  // Extra ref-like storage for the array fields (work_experience, skills,
  // education, answer_key_json) that the desktop's `profile` state shape
  // can't hold since it's Record<string, string>. We carry them through
  // parse → saveAiImport without passing through component state.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pendingArraysRef = useRef<Record<string, any>>({})

  function parseAiResponse() {
    setAiError(null)
    setAiParsed(false)
    if (!aiResponse.trim()) {
      setAiError("Please paste the AI response first.")
      return
    }

    // Tolerant parse + default application via the shared lib. This will:
    //   - strip markdown fences, // line / /* */ block comments, trailing commas
    //   - recover from prose wrapping the JSON
    //   - fill DEFAULTS for missing work_auth, sponsorship, disability,
    //     salary range, etc.
    //   - normalize alias field names (experience → work_experience, etc.)
    //   - return .profile (user_profiles fields) + .prefs (user_job_preferences)
    //   - NEVER throw — on unparseable input it returns defaults + an error string
    const result = parseAiResponseSafe(aiResponse)
    const p = result.profile as Record<string, unknown>
    const pf = result.prefs as Record<string, unknown>
    const str = (v: unknown) => (v == null ? "" : String(v))

    if (!result.ok && result.error) {
      setAiError(result.error + " (defaults still applied — you can save or adjust.)")
    }

    // Scalar fields go into the `profile` state (which is Record<string,string>)
    const nextProfile = { ...profile }
    const setIf = (k: string, v: unknown) => {
      if (v !== undefined && v !== null && String(v) !== "") {
        nextProfile[k] = String(v)
      }
    }
    setIf("first_name", p.first_name)
    setIf("last_name", p.last_name)
    setIf("phone", p.phone)
    setIf("linkedin_url", p.linkedin_url)
    setIf("github_url", p.github_url)
    setIf("portfolio_url", p.portfolio_url)
    setIf("current_company", p.current_company)
    setIf("current_title", p.current_title)
    setIf("years_experience", p.years_experience)
    setIf("education_level", p.education_level)
    setIf("school_name", p.school_name)
    setIf("degree", p.degree)
    setIf("graduation_year", p.graduation_year)
    setIf("work_authorization", p.work_authorization)
    setIf("gender", p.gender)
    setIf("race_ethnicity", p.race_ethnicity)
    setIf("veteran_status", p.veteran_status)
    setIf("disability_status", p.disability_status)
    if (typeof p.requires_sponsorship === "boolean") {
      nextProfile.requires_sponsorship = p.requires_sponsorship ? "Yes" : "No"
    }
    setProfile(nextProfile)

    // Array fields stored in a ref for later forwarding to updateProfile().
    pendingArraysRef.current = {}
    if (Array.isArray(p.work_experience) && p.work_experience.length > 0) {
      pendingArraysRef.current.work_experience = p.work_experience
    }
    if (Array.isArray(p.skills) && p.skills.length > 0) {
      pendingArraysRef.current.skills = p.skills
    }
    if (Array.isArray(p.education) && p.education.length > 0) {
      pendingArraysRef.current.education = p.education
    }
    if (p.answer_key_json && typeof p.answer_key_json === "object") {
      pendingArraysRef.current.answer_key_json = p.answer_key_json
    }

    // Preferences → separate prefs state
    const nextPrefs = { ...prefs }
    if (Array.isArray(pf.target_titles) && pf.target_titles.length) {
      nextPrefs.target_titles = (pf.target_titles as string[]).join(", ")
    }
    if (Array.isArray(pf.excluded_companies)) {
      nextPrefs.excluded_companies = (pf.excluded_companies as string[]).join(", ")
    }
    if (pf.min_salary != null) nextPrefs.min_salary = str(pf.min_salary)
    if (typeof pf.remote_only === "boolean") nextPrefs.remote_only = pf.remote_only ? "Yes" : "No"
    if (typeof pf.auto_apply === "boolean") nextPrefs.auto_apply = pf.auto_apply ? "Yes" : "No"
    setPrefs(nextPrefs)

    if (result.defaulted.length > 0) {
      console.info(`[settings] Applied defaults for: ${result.defaulted.join(", ")}`)
    }

    setAiParsed(true)
  }

  async function saveAiImport() {
    setSaveError(null)
    setSaving(true)
    try {
      // Persist profile: scalars from form state + array fields from
      // the pendingArraysRef that parseAiResponse stashed. The desktop
      // /api/profile endpoint forwards to the worker proxy which has
      // work_experience / skills / education / answer_key_json in its
      // PROFILE_COLUMNS allowlist, so they land on user_profiles.
      const profilePayload: Record<string, unknown> = { ...profile }
      if (profile.requires_sponsorship) {
        profilePayload.requires_sponsorship = profile.requires_sponsorship === "Yes"
      }
      Object.assign(profilePayload, pendingArraysRef.current)

      await updateProfile(profilePayload)
      await updatePreferences({
        ...prefs,
        target_titles: prefs.target_titles?.split(",").map(s => s.trim()).filter(Boolean),
        excluded_companies: prefs.excluded_companies?.split(",").map(s => s.trim()).filter(Boolean),
        min_salary: prefs.min_salary ? Number(prefs.min_salary) : null,
        remote_only: prefs.remote_only === "Yes",
        auto_apply: prefs.auto_apply === "Yes",
      })
      // Clear stashed arrays after successful save.
      pendingArraysRef.current = {}
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
  // Read-only / display-only tabs don't need the top Save button. telegram,
  // email, worker, billing show existing integrations state + explanatory
  // content; edits happen via the API Keys tab's encrypted-store flow.
  const showTopSave = activeTab !== "ai" && activeTab !== "resume"
    && activeTab !== "telegram" && activeTab !== "email"
    && activeTab !== "worker" && activeTab !== "billing"
    && activeTab !== "profiles"

  return (
    <AppShell>
      <div className="space-y-6">
        {setupComplete === false && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/30 dark:text-amber-100">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              <span>
                Setup isn&apos;t complete yet. Edit what you need here, then return
                to the wizard to finish the remaining steps.
              </span>
            </div>
            <button
              onClick={() => router.push("/setup")}
              className="flex items-center gap-1.5 rounded-md bg-amber-200 px-3 py-1 text-xs font-medium text-amber-900 hover:bg-amber-300 dark:bg-amber-800 dark:text-amber-100 dark:hover:bg-amber-700"
            >
              <ArrowLeft className="h-3 w-3" />
              Return to wizard
            </button>
          </div>
        )}
        <div className="flex items-center justify-between pb-1">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-foreground">Settings</h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              Profiles, credentials, and worker configuration. Changes sync to the cloud automatically.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {lastSyncedAt && !syncing && (
                <span>
                  Synced {(() => {
                    const secs = Math.round((Date.now() - lastSyncedAt) / 1000)
                    if (secs < 5) return "just now"
                    if (secs < 60) return `${secs}s ago`
                    const mins = Math.round(secs / 60)
                    return `${mins}m ago`
                  })()}
                </span>
              )}
              <button
                onClick={syncAndReload}
                disabled={syncing}
                title="Pull latest from cloud + push local changes"
                className={buttonClass.secondary}
              >
                {syncing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                )}
                {syncing ? "Syncing..." : "Refresh"}
              </button>
            </div>
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
                className={buttonClass.primary}
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
        <div className="flex gap-0.5 rounded-md border border-border bg-card p-1 overflow-x-auto shadow-xs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors whitespace-nowrap",
                activeTab === tab.id
                  ? "bg-[var(--primary-subtle)] text-primary"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              )}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="rounded-lg border border-border bg-card p-6 shadow-xs">
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
                  <div>
                    <div className="font-medium">Parsed successfully.</div>
                    <div className="mt-1 text-success/90">
                      Imported:
                      {" "}
                      {(pendingArraysRef.current.work_experience as unknown[] | undefined)?.length ?? 0} job{((pendingArraysRef.current.work_experience as unknown[] | undefined)?.length ?? 0) === 1 ? "" : "s"},
                      {" "}
                      {(pendingArraysRef.current.education as unknown[] | undefined)?.length ?? 0} education entr{((pendingArraysRef.current.education as unknown[] | undefined)?.length ?? 0) === 1 ? "y" : "ies"},
                      {" "}
                      {(pendingArraysRef.current.skills as unknown[] | undefined)?.length ?? 0} skills,
                      {" "}
                      {Object.keys((pendingArraysRef.current.answer_key_json as Record<string, unknown> | undefined) || {}).length} answer-key entries.
                    </div>
                    <div className="mt-1">
                      Review in the Personal, Work, and Preferences tabs, then click <strong>Save &amp; Sync</strong>.
                    </div>
                  </div>
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
            <div className="space-y-6">
              {/* Flat fields — fast-path overview. Saved by the top-right
                  Save button via the page-level handleSave/updateProfile
                  flow. The structured row editors below save separately
                  via their own button. */}
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

              {/* Structured array editors — the applier reads these when
                  filling multi-entry form sections. Previously the desktop
                  could only write them via AI Import paste (audit-flagged
                  regression). */}
              <div className="border-t pt-6">
                <WorkEducationEditor
                  initial={{ work_experience: workExperience, education: education, skills: skills }}
                  onSaved={() => {
                    setSaved(true)
                    setTimeout(() => setSaved(false), 2000)
                  }}
                  onError={(msg) => setSaveError(msg)}
                />
              </div>
            </div>
          )}

          {activeTab === "preferences" && (
            <div className="space-y-4">
              <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm flex items-start gap-3">
                <div className="flex-1">
                  <p className="font-medium text-foreground">Heads up — these fields mirror to your default Profile.</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    For per-role targeting, use the <strong>Profiles</strong> tab. This tab stays for quick edits to the default bundle.
                  </p>
                </div>
                <button
                  onClick={() => setActiveTab("profiles")}
                  className="text-xs px-3 py-1.5 rounded-lg bg-primary text-primary-foreground whitespace-nowrap"
                >
                  Go to Profiles →
                </button>
              </div>
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

          {activeTab === "profiles" && (
            <ProfilesTab onMessage={(text, type) => { if (type === "error") setSaveError(text); else { setSaved(true); setTimeout(() => setSaved(false), 2000); } }} />
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

          {activeTab === "integrations" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-foreground mb-1">API Keys & Credentials</h2>
                <p className="text-sm text-muted-foreground">
                  Stored encrypted in your cloud profile. Synced across the web dashboard,
                  this desktop app, and your running Claude session. Update any field any time.
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  <strong>Heads up:</strong> the running worker refreshes credentials every ~5 min.
                  If you rotate a Gmail password now, apps submitted in the next few minutes may
                  still use the old one. Restart the worker for an immediate pickup.
                </p>
              </div>

              {integrationsMsg && (
                <div className={cn(
                  "rounded-lg px-3 py-2 text-sm",
                  integrationsMsg.type === "ok" ? "bg-success/10 text-success border border-success/20" : "bg-destructive/10 text-destructive border border-destructive/20"
                )}>
                  {integrationsMsg.text}
                </div>
              )}

              {integrationsLoading && (
                <p className="text-sm text-muted-foreground">Loading current values...</p>
              )}

              <div className="space-y-4">
                {DESKTOP_INTEGRATION_FIELDS.map((def) => {
                  const state = integrationsState[def.key]
                  const draft = integrationsDraft[def.key] ?? ""
                  const isSet = state?.set
                  return (
                    <div key={def.key}>
                      <label className="mb-1.5 block text-sm font-medium text-card-foreground">
                        {def.label}
                        {isSet && (
                          <span className="ml-2 text-xs font-normal text-success">
                            ✓ saved ({state?.mask})
                          </span>
                        )}
                        {!isSet && (
                          <span className="ml-2 text-xs font-normal text-muted-foreground">(not set)</span>
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
                          className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                        />
                        {isSet && (
                          <button
                            type="button"
                            onClick={() => clearIntegrationField(def.key)}
                            disabled={integrationsSaving}
                            className="px-3 py-2 text-sm border border-destructive/30 text-destructive rounded-lg hover:bg-destructive/10 disabled:opacity-50"
                          >
                            Clear
                          </button>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{renderHelpWithLinks(def.help)}</p>
                    </div>
                  )
                })}
              </div>

              <div className="flex items-center gap-3 border-t border-border pt-4">
                <button
                  onClick={saveIntegrations}
                  disabled={integrationsSaving || Object.keys(integrationsDraft).filter((k) => (integrationsDraft[k] || "").trim() !== "").length === 0}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {integrationsSaving ? "Saving..." : "Save changes"}
                </button>
                <span className="text-xs text-muted-foreground">
                  {Object.keys(integrationsDraft).filter((k) => (integrationsDraft[k] || "").trim() !== "").length} pending
                </span>
              </div>
            </div>
          )}

          {activeTab === "telegram" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-foreground mb-1">Telegram Notifications</h2>
                <p className="text-sm text-muted-foreground">
                  Get a photo + caption on every successful submission. Configure your own bot
                  here OR use the API Keys tab — they write to the same encrypted integrations store.
                </p>
              </div>

              <div className="rounded-lg border border-border bg-card/50 p-4 space-y-3">
                <div className="text-sm">
                  <span className="font-medium text-card-foreground">Bot Token:</span>{" "}
                  {integrationsState["telegram_bot_token"]?.set ? (
                    <span className="text-success">✓ saved ({integrationsState["telegram_bot_token"]?.mask})</span>
                  ) : (
                    <span className="text-muted-foreground">not set</span>
                  )}
                </div>
                <div className="text-sm">
                  <span className="font-medium text-card-foreground">Chat ID:</span>{" "}
                  {integrationsState["telegram_chat_id"]?.set ? (
                    <span className="text-success">✓ saved ({integrationsState["telegram_chat_id"]?.mask})</span>
                  ) : (
                    <span className="text-muted-foreground">not set</span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground pt-2 border-t border-border">
                  To change: go to the <button onClick={() => setActiveTab("integrations")} className="text-primary hover:underline">API Keys</button> tab
                  and update telegram_bot_token + telegram_chat_id. Changes sync to both the
                  desktop app and the web dashboard immediately.
                </p>
              </div>

              <div className="rounded-lg bg-muted/50 p-4 space-y-2">
                <p className="text-sm font-medium text-card-foreground">How to get your bot token:</p>
                <ol className="list-decimal list-inside text-sm text-muted-foreground space-y-1">
                  <li>Open Telegram → search <code>@BotFather</code></li>
                  <li>Send <code>/newbot</code> → follow prompts → copy the <code>bot_id:secret</code> token</li>
                  <li>Search your new bot → send <code>/start</code> to yourself</li>
                  <li>Visit <code>https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code> → copy the <code>chat.id</code></li>
                  <li>Paste both in the API Keys tab</li>
                </ol>
              </div>
            </div>
          )}

          {activeTab === "email" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-foreground mb-1">Email (Gmail)</h2>
                <p className="text-sm text-muted-foreground">
                  Used to read verification codes + password reset emails during applications
                  (e.g. when Workday asks for email verification). Two ways to configure:
                </p>
              </div>

              <div className="rounded-lg border border-border bg-card/50 p-4 space-y-3">
                <p className="text-sm font-medium text-card-foreground">1. App password (current)</p>
                <div className="text-sm">
                  <span className="text-card-foreground">Gmail email:</span>{" "}
                  {integrationsState["gmail_email"]?.set ? (
                    <span className="text-success">✓ saved ({integrationsState["gmail_email"]?.mask})</span>
                  ) : (
                    <span className="text-muted-foreground">not set</span>
                  )}
                </div>
                <div className="text-sm">
                  <span className="text-card-foreground">App password:</span>{" "}
                  {integrationsState["gmail_app_password"]?.set ? (
                    <span className="text-success">✓ saved ({integrationsState["gmail_app_password"]?.mask})</span>
                  ) : (
                    <span className="text-muted-foreground">not set</span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground pt-2 border-t border-border">
                  Configure in the <button onClick={() => setActiveTab("integrations")} className="text-primary hover:underline">API Keys</button> tab.
                  Generate an app password at <code>myaccount.google.com/apppasswords</code> (requires 2FA enabled).
                </p>
              </div>

              <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2">
                <p className="text-sm font-medium text-card-foreground">2. OAuth (browser-based — recommended)</p>
                <p className="text-xs text-muted-foreground">
                  Configure on the web dashboard at applyloop.vercel.app/dashboard/settings →
                  Email tab → "Connect Gmail". OAuth is more secure and doesn't require
                  generating an app password. Once connected on the web, it syncs here.
                </p>
              </div>
            </div>
          )}

          {activeTab === "worker" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-foreground mb-1">Worker & LLM</h2>
                <p className="text-sm text-muted-foreground">
                  The worker process scouts and applies to jobs. The LLM powers form-field
                  understanding + answer generation. Both live in this desktop app — the
                  cloud just coordinates state.
                </p>
              </div>

              <div className="rounded-lg border border-border bg-card/50 p-4 space-y-3">
                <p className="text-sm font-medium text-card-foreground">Runtime configuration</p>
                <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                  <li>Scout interval: 30 min (all sources) — set via <code>SCOUT_INTERVAL_MINUTES</code> env</li>
                  <li>Apply cooldown: 30 sec (between jobs) — set via <code>APPLY_COOLDOWN</code> env</li>
                  <li>Max per company: 3 per rolling 7 days (hard cap, global)</li>
                  <li>Queue freshness: 24h (stale rows auto-pruned)</li>
                  <li>Worker token source: <code>~/.applyloop/.env</code> → <code>WORKER_TOKEN</code></li>
                </ul>
                <p className="text-xs text-muted-foreground pt-2 border-t border-border">
                  Advanced LLM settings (provider, model, per-request spend limit) live in the
                  web dashboard at applyloop.vercel.app/dashboard/settings → Worker & LLM.
                  Edit there to change globally; this desktop reads the cloud values on startup.
                </p>
              </div>
            </div>
          )}

          {activeTab === "billing" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-foreground mb-1">Billing</h2>
              </div>

              <div className="rounded-lg border-2 border-primary/30 bg-gradient-to-br from-primary/5 to-primary/10 p-6 text-center space-y-3">
                <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-primary/20">
                  <Sparkles className="h-6 w-6 text-primary" />
                </div>
                <h3 className="text-lg font-semibold text-foreground">Early Adopter — free access</h3>
                <p className="text-sm text-muted-foreground max-w-md mx-auto">
                  You're in the early cohort. Unlimited applications, unlimited scout cycles,
                  no paywall. Paid tiers will launch later — early adopters will be grandfathered
                  on their current plan.
                </p>
              </div>

              <div className="rounded-lg bg-muted/50 p-4">
                <p className="text-xs text-muted-foreground">
                  Questions? Message the admin via Telegram, or open an issue at{" "}
                  <code>github.com/snehitvaddi/ApplyLoop/issues</code>.
                </p>
              </div>
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
