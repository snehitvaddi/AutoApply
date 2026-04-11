"use client"

import { useState, useEffect, useCallback } from "react"
import { AppShell } from "@/components/app-shell"
import { getProfile, updateProfile, getPreferences, updatePreferences } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Save, Loader2, Check, User, Briefcase, Target, Key, AlertTriangle } from "lucide-react"

type Tab = "personal" | "work" | "preferences" | "auth"

const tabs: { id: Tab; label: string; icon: typeof User }[] = [
  { id: "personal", label: "Personal", icon: User },
  { id: "work", label: "Work & Education", icon: Briefcase },
  { id: "preferences", label: "Job Preferences", icon: Target },
  { id: "auth", label: "API Token", icon: Key },
]

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
  const [activeTab, setActiveTab] = useState<Tab>("personal")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [profile, setProfile] = useState<Record<string, string>>({})
  const [prefs, setPrefs] = useState<Record<string, string>>({})
  const [token, setToken] = useState("")
  const [maskedToken, setMaskedToken] = useState("")

  const loadData = useCallback(async () => {
    try {
      const [profileRes, prefsRes] = await Promise.allSettled([
        getProfile(),
        getPreferences(),
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
          education: String(p?.education ?? ""),
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
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    loadData()
    // Load masked token
    fetch("/api/auth/token-masked").then(r => r.json()).then(d => {
      if (d.has_token) setMaskedToken(d.masked)
    }).catch(() => {})
  }, [loadData])

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
      // Surface the failure instead of silently flashing Saved. The
      // most common case is a revoked token — the upstream proxy returns
      // 401, apiFetch throws, and the user is left wondering why their
      // changes didn't stick.
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
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 rounded-xl border border-border bg-card p-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
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
              <Input label="Education" value={profile.education ?? ""} onChange={(v) => updateField("education", v)} placeholder="MS Computer Science, Stanford" />
              <Input label="Work Authorization" value={profile.work_authorization ?? ""} onChange={(v) => updateField("work_authorization", v)} placeholder="US Citizen, Green Card, etc." />
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
