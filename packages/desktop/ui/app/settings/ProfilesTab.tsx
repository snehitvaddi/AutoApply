"use client";

import { useCallback, useEffect, useState } from "react";
import { WorkEducationEditor, type WorkExperienceRow, type EducationRow } from "./WorkEducationEditor";

type Profile = {
  id: string;
  name: string;
  slug: string;
  is_default: boolean;
  updated_at?: string;
  target_titles: string[];
  target_keywords: string[];
  excluded_titles: string[];
  excluded_companies: string[];
  excluded_role_keywords: string[];
  excluded_levels: string[];
  preferred_locations: string[];
  remote_only: boolean;
  min_salary: number | null;
  ashby_boards: string[] | null;
  greenhouse_boards: string[] | null;
  resume_id: string | null;
  email_account_id: string | null;
  application_email: string | null;
  auto_apply: boolean;
  max_daily: number | null;
  // Per-bundle content (mig 019). null = inherit from shared fallback.
  answer_key_json: Record<string, unknown> | null;
  cover_letter_template: string | null;
  // Per-bundle work history (mig 020). null = inherit from user_profiles.
  work_experience: WorkExperienceRow[] | null;
  education: EducationRow[] | null;
  skills: string[] | null;
  has_app_password?: boolean;
};

type Resume = { id: string; file_name: string; is_default: boolean };
type EmailAccount = { id: string; email: string; label: string | null; has_app_password: boolean };

// Talks to the LOCAL FastAPI endpoints (/api/profiles, /api/email-accounts)
// which proxy to the cloud with the stored worker token. The desktop UI is
// served by the FastAPI itself, so same-origin fetches work without a port.
async function call(path: string, init?: RequestInit) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    // FastAPI HTTPException body is { detail: "..." }.
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      msg = (j?.detail as string) || (j?.error as string) || msg;
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export function ProfilesTab({ onMessage }: { onMessage: (text: string, type: "success" | "error") => void }) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [emailAccounts, setEmailAccounts] = useState<EmailAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<Profile> & { application_email_app_password?: string; same_email_as_default?: boolean }>({});
  const [answerKeyText, setAnswerKeyText] = useState<string>("");
  const [answerKeyError, setAnswerKeyError] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Each call independently try/caught so one failure doesn't
      // unhandled-reject the whole Promise.all.
      const safe = async <T,>(p: Promise<T>, fallback: T): Promise<T> => {
        try { return await p; } catch { return fallback; }
      };
      const [p, r, e] = await Promise.all([
        safe(call("/api/profiles"), { data: { profiles: [] } }),
        safe(call("/api/resumes"), { data: { resumes: [] } }),
        safe(call("/api/email-accounts"), { data: { email_accounts: [] } }),
      ]);
      setProfiles(p?.data?.profiles || []);
      setResumes(r?.data?.resumes || []);
      setEmailAccounts(e?.data?.email_accounts || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (editingId === null) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [editingId]);

  const startCreate = () => {
    const d = profiles.find((p) => p.is_default);
    setEditingId("__new__");
    setAnswerKeyText("");
    setAnswerKeyError("");
    setDraft({
      name: "",
      target_titles: [],
      target_keywords: [],
      excluded_titles: [],
      excluded_companies: [],
      excluded_role_keywords: [],
      excluded_levels: [],
      preferred_locations: d?.preferred_locations || ["United States"],
      remote_only: false,
      min_salary: null,
      ashby_boards: null,
      greenhouse_boards: null,
      resume_id: null,
      email_account_id: null,
      application_email: "",
      auto_apply: true,
      max_daily: null,
      answer_key_json: null,
      cover_letter_template: null,
      // Clone W&E from default bundle when creating a new one so users
      // don't have to re-type their history for every profile. They can
      // still tweak per-role afterwards (that's the whole point of mig 020).
      work_experience: d?.work_experience ? [...d.work_experience] : [],
      education: d?.education ? [...d.education] : [],
      skills: d?.skills ? [...d.skills] : [],
      same_email_as_default: false,
    });
  };

  const save = async () => {
    if (!draft.name) return onMessage("Name is required", "error");
    if (!draft.target_titles || draft.target_titles.length === 0) {
      return onMessage("Add at least one target title so the scout knows what to look for", "error");
    }
    // Parse the answer_key JSON textarea — same contract as the web tab.
    let parsedAnswerKey: Record<string, unknown> | null = null;
    const trimmed = answerKeyText.trim();
    if (trimmed) {
      try {
        parsedAnswerKey = JSON.parse(trimmed);
        if (typeof parsedAnswerKey !== "object" || parsedAnswerKey === null || Array.isArray(parsedAnswerKey)) {
          setAnswerKeyError("Answer key must be a JSON object");
          return onMessage("Answer key is not a JSON object", "error");
        }
        setAnswerKeyError("");
      } catch (err) {
        setAnswerKeyError(err instanceof Error ? err.message : "Invalid JSON");
        return onMessage("Answer key JSON is invalid — see the error under the field", "error");
      }
    }
    draft.answer_key_json = parsedAnswerKey;
    const isNew = editingId === "__new__";
    if (draft.same_email_as_default) {
      const d = profiles.find((p) => p.is_default);
      if (d?.email_account_id) {
        draft.email_account_id = d.email_account_id;
      } else if (d?.application_email) {
        draft.application_email = d.application_email;
        if (!draft.application_email_app_password) {
          return onMessage(
            "Default profile uses an inline email. Re-enter the Gmail app password here, or move the default to the email-account pool first.",
            "error",
          );
        }
      }
    }
    const body: Record<string, unknown> = { ...draft };
    delete body.same_email_as_default;
    if (!isNew) delete body.is_default;  // PUT writable list excludes this
    if (!isNew && draft.updated_at) body.if_updated_at = draft.updated_at;
    const path = isNew ? "/api/profiles" : `/api/profiles/${editingId}`;
    try {
      await call(path, { method: isNew ? "POST" : "PUT", body: JSON.stringify(body) });
    } catch (err) {
      return onMessage(err instanceof Error ? err.message : "Save failed", "error");
    }
    draft.application_email_app_password = "";
    onMessage(isNew ? "Profile created" : "Profile updated", "success");
    setEditingId(null); setDraft({}); load();
  };

  const del = async (id: string) => {
    if (!confirm("Delete this profile?")) return;
    try {
      await call(`/api/profiles/${id}`, { method: "DELETE" });
    } catch (err) {
      return onMessage(err instanceof Error ? err.message : "Delete failed", "error");
    }
    onMessage("Profile deleted", "success"); load();
  };

  const setDefault = async (id: string) => {
    try {
      await call(`/api/profiles/${id}/set-default`, { method: "POST" });
    } catch (err) {
      return onMessage(err instanceof Error ? err.message : "Set default failed", "error");
    }
    onMessage("Default updated", "success"); load();
  };

  if (loading) return <div className="text-sm text-muted-foreground">Loading profiles...</div>;

  if (editingId !== null) {
    return (
      <div className="space-y-3">
        <TextField label="Profile name" value={draft.name || ""} onChange={(v) => setDraft({ ...draft, name: v })} />
        <ChipField label="Target titles" values={draft.target_titles || []} onChange={(v) => setDraft({ ...draft, target_titles: v })} />
        <ChipField label="Target keywords" values={draft.target_keywords || []} onChange={(v) => setDraft({ ...draft, target_keywords: v })} />
        <ChipField label="Excluded titles" values={draft.excluded_titles || []} onChange={(v) => setDraft({ ...draft, excluded_titles: v })} />
        <ChipField label="Excluded companies" values={draft.excluded_companies || []} onChange={(v) => setDraft({ ...draft, excluded_companies: v })} />
        <ChipField label="Excluded role keywords" values={draft.excluded_role_keywords || []} onChange={(v) => setDraft({ ...draft, excluded_role_keywords: v })} />
        <ChipField label="Excluded levels" values={draft.excluded_levels || []} onChange={(v) => setDraft({ ...draft, excluded_levels: v })} />
        <ChipField label="Preferred locations" values={draft.preferred_locations || []} onChange={(v) => setDraft({ ...draft, preferred_locations: v })} />

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!draft.remote_only} onChange={(e) => setDraft({ ...draft, remote_only: e.target.checked })} /> Remote only</label>
          <label className="flex items-center gap-2 text-sm">Min salary
            <input
              type="number"
              className="border rounded px-2 py-1 w-28 bg-background"
              value={draft.min_salary ?? ""}
              onChange={(e) => setDraft({ ...draft, min_salary: e.target.value ? parseInt(e.target.value) : null })}
            />
          </label>
        </div>

        {/* Per-bundle board overrides. Blank = use global defaults. */}
        <div className="border-t pt-3 mt-2">
          <h3 className="text-sm font-semibold mb-1">Board overrides (optional)</h3>
          <p className="text-xs text-muted-foreground mb-2">Leave blank to use the global default board lists.</p>
          <ChipField
            label="Ashby boards"
            values={draft.ashby_boards || []}
            onChange={(v) => setDraft({ ...draft, ashby_boards: v.length ? v : null })}
          />
          <ChipField
            label="Greenhouse boards"
            values={draft.greenhouse_boards || []}
            onChange={(v) => setDraft({ ...draft, greenhouse_boards: v.length ? v : null })}
          />
        </div>

        <div>
          <label className="text-sm font-medium block mb-1">Resume</label>
          <select className="border rounded px-2 py-1 w-full bg-background" value={draft.resume_id || ""} onChange={(e) => setDraft({ ...draft, resume_id: e.target.value || null })}>
            <option value="">(none)</option>
            {resumes.map((r) => <option key={r.id} value={r.id}>{r.file_name}</option>)}
          </select>
        </div>

        {editingId === "__new__" && profiles.some((p) => p.is_default) && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!draft.same_email_as_default} onChange={(e) => setDraft({ ...draft, same_email_as_default: e.target.checked })} />
            Use same apply-from email as Default profile
          </label>
        )}

        {!draft.same_email_as_default && (
          <>
            <div>
              <label className="text-sm font-medium block mb-1">Apply-from email account</label>
              <select className="border rounded px-2 py-1 w-full bg-background" value={draft.email_account_id || ""} onChange={(e) => setDraft({ ...draft, email_account_id: e.target.value || null })}>
                <option value="">(use inline email)</option>
                {emailAccounts.map((e) => <option key={e.id} value={e.id}>{e.email}{e.has_app_password ? " ✓" : ""}</option>)}
              </select>
            </div>
            {!draft.email_account_id && (
              <TextField label="Apply-from email (inline)" value={draft.application_email || ""} onChange={(v) => setDraft({ ...draft, application_email: v })} />
            )}
            <TextField
              label={draft.has_app_password ? "Gmail app password (stored ✓ — leave blank to keep)" : "Gmail app password"}
              type="password"
              autoComplete="new-password"
              value={draft.application_email_app_password || ""}
              onChange={(v) => setDraft({ ...draft, application_email_app_password: v })}
            />
          </>
        )}

        {/* Per-role Work & Education (mig 020). Each bundle tells a
            different story — AI Eng emphasizes ML wins, DA emphasizes
            pipelines. Controlled mode: editor fires onChange, profile
            Save button persists to user_application_profiles. */}
        <div className="border-t pt-3 mt-2">
          <h3 className="text-sm font-semibold mb-2">Per-role work & education</h3>
          <WorkEducationEditor
            initial={{
              work_experience: draft.work_experience || [],
              education: draft.education || [],
              skills: draft.skills || [],
            }}
            onChange={(next) => setDraft((d) => ({
              ...d,
              work_experience: next.work_experience,
              education: next.education,
              skills: next.skills,
            }))}
          />
        </div>

        {/* Per-role content — answer key + cover letter. Different per
            bundle so "Why AI Engineering?" doesn't leak onto a DA app. */}
        <div className="border-t pt-3 mt-2">
          <h3 className="text-sm font-semibold mb-2">Per-role content</h3>
          <div className="mb-3">
            <label className="text-sm font-medium block mb-1">
              Answer key (JSON)
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                Role-specific answers.
              </span>
            </label>
            <textarea
              rows={6}
              placeholder={'{\n  "why_interested": "Because..."\n}'}
              className="border rounded px-2 py-1 w-full bg-background font-mono text-xs"
              value={answerKeyText}
              onChange={(e) => { setAnswerKeyText(e.target.value); setAnswerKeyError(""); }}
            />
            {answerKeyError && <p className="text-xs text-destructive mt-1">⚠ {answerKeyError}</p>}
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">Cover letter template</label>
            <textarea
              rows={6}
              placeholder="Dear {hiring_manager},&#10;&#10;I'm excited to apply for {role} at {company}..."
              className="border rounded px-2 py-1 w-full bg-background text-sm"
              value={draft.cover_letter_template || ""}
              onChange={(e) => setDraft({ ...draft, cover_letter_template: e.target.value || null })}
            />
            <p className="text-xs text-muted-foreground mt-1">
              Leave blank to inherit the default profile&apos;s template.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 pt-2 border-t">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={draft.auto_apply !== false} onChange={(e) => setDraft({ ...draft, auto_apply: e.target.checked })} /> Active
          </label>
          <label className="flex items-center gap-2 text-sm">
            Max daily
            <input
              type="number"
              min={0}
              placeholder="no cap"
              className="border rounded px-2 py-1 w-24 bg-background"
              value={draft.max_daily ?? ""}
              onChange={(e) => setDraft({ ...draft, max_daily: e.target.value ? parseInt(e.target.value) : null })}
            />
          </label>
        </div>

        <div className="flex gap-2 pt-2">
          <button onClick={save} className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground">Save</button>
          <button onClick={() => { setEditingId(null); setDraft({}); }} className="px-4 py-2 text-sm rounded-lg border">Cancel</button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Each bundle binds its own resume, apply-from email, and target titles. The worker routes each job to the matching bundle.</p>
        <button onClick={startCreate} className="px-3 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground">+ Add</button>
      </div>
      {profiles.map((p) => {
        const resumeFile = p.resume_id ? resumes.find((r) => r.id === p.resume_id)?.file_name : undefined;
        const resumeMissing = !!p.resume_id && !resumeFile;
        const noEmail = !p.application_email && !p.email_account_id;
        return (
        <div key={p.id} className="border rounded-lg p-3 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium">{p.name}</span>
              {p.is_default && <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded">DEFAULT</span>}
              {!p.auto_apply && <span className="text-xs bg-muted text-muted-foreground px-2 py-0.5 rounded">paused</span>}
              {resumeMissing && <span className="text-xs bg-destructive/10 text-destructive px-2 py-0.5 rounded">⚠ missing resume</span>}
              {noEmail && <span className="text-xs bg-warning/10 text-warning px-2 py-0.5 rounded">no apply email</span>}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {p.application_email || "no email"} · {(p.target_titles || []).slice(0, 3).join(", ") || "no titles"} · resume: {resumeFile || (resumeMissing ? "⚠ deleted" : "none")}
            </div>
          </div>
          <div className="flex gap-2">
            {!p.is_default && <button onClick={() => setDefault(p.id)} className="text-xs text-primary hover:underline">Default</button>}
            <button
              onClick={() => {
                setEditingId(p.id);
                setDraft({ ...p });
                setAnswerKeyText(p.answer_key_json ? JSON.stringify(p.answer_key_json, null, 2) : "");
                setAnswerKeyError("");
              }}
              className="text-xs hover:underline"
            >Edit</button>
            {!p.is_default && <button onClick={() => del(p.id)} className="text-xs text-destructive hover:underline">Delete</button>}
          </div>
        </div>
        );
      })}
      {profiles.length === 0 && <div className="text-sm text-muted-foreground">No profiles yet.</div>}
    </div>
  );
}

function TextField({ label, value, onChange, type = "text", autoComplete }: { label: string; value: string; onChange: (v: string) => void; type?: string; autoComplete?: string }) {
  return (
    <div>
      <label className="text-sm font-medium block mb-1">{label}</label>
      <input type={type} autoComplete={autoComplete} className="border rounded px-2 py-1 w-full bg-background" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function ChipField({ label, values, onChange }: { label: string; values: string[]; onChange: (v: string[]) => void }) {
  const [buf, setBuf] = useState("");
  const commit = () => {
    const parts = buf.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...(values || []), ...parts]);
    setBuf("");
  };
  return (
    <div>
      <label className="text-sm font-medium block mb-1">{label}</label>
      <div className="flex flex-wrap gap-1 mb-1">
        {(values || []).map((v, i) => (
          <span key={i} className="text-xs bg-muted rounded px-2 py-0.5 flex items-center gap-1">
            {v}<button onClick={() => onChange((values || []).filter((_, j) => j !== i))}>×</button>
          </span>
        ))}
      </div>
      <input className="border rounded px-2 py-1 w-full bg-background" value={buf} onChange={(e) => setBuf(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); } }} onBlur={commit} placeholder="type + Enter" />
    </div>
  );
}
