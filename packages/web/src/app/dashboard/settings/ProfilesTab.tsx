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
  excluded_companies: string[];
  excluded_role_keywords: string[];
  excluded_levels: string[];
  preferred_locations: string[];
  remote_only: boolean;
  min_salary: number | null;
  resume_id: string | null;
  email_account_id: string | null;
  application_email: string | null;
  auto_apply: boolean;
  max_daily: number | null;
  // Per-bundle content (mig 019). null = inherit from shared
  // user_profiles fallback at apply time.
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

export function ProfilesTab({
  onMessage,
}: { onMessage: (text: string, type: "success" | "error") => void }) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [emailAccounts, setEmailAccounts] = useState<EmailAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<Profile> & { application_email_app_password?: string; same_email_as_default?: boolean }>({});
  // Free-form JSON text for the answer_key editor. Kept separate from
  // draft.answer_key_json so the user can type invalid JSON while editing
  // without losing their work — we validate + parse on save.
  const [answerKeyText, setAnswerKeyText] = useState<string>("");
  const [answerKeyError, setAnswerKeyError] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [pRes, rRes, eRes] = await Promise.all([
        fetch("/api/settings/profiles").then((r) => r.json()),
        fetch("/api/settings/resumes").then((r) => r.json()).catch(() => ({ data: { resumes: [] } })),
        fetch("/api/settings/email-accounts").then((r) => r.json()),
      ]);
      setProfiles(pRes?.data?.profiles || []);
      setResumes(rRes?.data?.resumes || []);
      setEmailAccounts(eRes?.data?.email_accounts || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Guard against accidental tab close / navigation while a profile is
  // being edited. Browsers show the native "Changes you made may not be
  // saved" dialog when returnValue is set. Only active while editing.
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
    const defaultProfile = profiles.find((p) => p.is_default);
    setEditingId("__new__");
    setAnswerKeyText("");
    setAnswerKeyError("");
    setDraft({
      name: "",
      target_titles: [],
      target_keywords: [],
      excluded_companies: [],
      excluded_role_keywords: [],
      excluded_levels: [],
      preferred_locations: defaultProfile?.preferred_locations || ["United States"],
      remote_only: false,
      min_salary: null,
      resume_id: null,
      email_account_id: null,
      application_email: "",
      auto_apply: true,
      max_daily: null,
      answer_key_json: null,
      cover_letter_template: null,
      // Clone W&E from the default bundle so new profiles start with the
      // user's base history. They can tailor per-role afterwards.
      work_experience: defaultProfile?.work_experience ? [...defaultProfile.work_experience] : [],
      education: defaultProfile?.education ? [...defaultProfile.education] : [],
      skills: defaultProfile?.skills ? [...defaultProfile.skills] : [],
      same_email_as_default: false,
    });
  };

  const startEdit = (p: Profile) => {
    setEditingId(p.id);
    setDraft({ ...p });
    setAnswerKeyText(p.answer_key_json ? JSON.stringify(p.answer_key_json, null, 2) : "");
    setAnswerKeyError("");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraft({});
    setAnswerKeyText("");
    setAnswerKeyError("");
  };

  const save = async () => {
    if (!draft.name) return onMessage("Name is required", "error");
    // Worker refuses to boot without target_titles — surface it here
    // instead of letting the user click Save, think they're done, and
    // then wonder why the worker is silent.
    if (!draft.target_titles || draft.target_titles.length === 0) {
      return onMessage("Add at least one target title so the scout knows what to look for", "error");
    }
    // Parse the answer_key JSON textarea. Blank = clear (null), non-JSON
    // = reject with a specific error so the user knows where to look.
    // The editor keeps the raw text in state so edit-while-broken works.
    let parsedAnswerKey: Record<string, unknown> | null = null;
    const trimmed = answerKeyText.trim();
    if (trimmed) {
      try {
        parsedAnswerKey = JSON.parse(trimmed);
        if (typeof parsedAnswerKey !== "object" || parsedAnswerKey === null || Array.isArray(parsedAnswerKey)) {
          setAnswerKeyError("Answer key must be a JSON object (e.g. {\"why_interested\": \"...\"})");
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

    // Same-email-as-default: prefer the pooled email_account_id (so
    // rotating its app password updates both bundles); fall back to copying
    // the inline application_email. App password can't be re-derived from
    // the sibling bundle — the user must re-enter it OR use the pool.
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
    // is_default is NOT in the PUT writable allowlist (use set-default
    // instead). Strip it to avoid confusing server-side validation.
    if (!isNew) delete body.is_default;
    // Send the draft's loaded updated_at for optimistic concurrency.
    // Server rejects the PUT if the row advanced since load — prevents
    // silent data loss when two tabs edit the same bundle.
    if (!isNew && draft.updated_at) body.if_updated_at = draft.updated_at;

    const url = isNew ? "/api/settings/profiles" : `/api/settings/profiles/${editingId}`;
    const method = isNew ? "POST" : "PUT";
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const json = await res.json();
    // apiError returns a FLAT body { statusCode, name, message } — read
    // json.message directly. json?.error?.message would be undefined and
    // every validation error (slug collision, ownership, etc.) fell
    // through to "Save failed" — the whole point of the friendly errors.
    if (!res.ok || !json?.data) return onMessage(json?.message || "Save failed", "error");
    // Clear the plaintext password from React state immediately so it's
    // not sitting in the component tree for DevTools to read.
    draft.application_email_app_password = "";
    onMessage(isNew ? "Profile created" : "Profile updated", "success");
    cancelEdit();
    load();
  };

  const del = async (id: string) => {
    if (!confirm("Delete this profile? Queue rows referencing it will fall back to default.")) return;
    const res = await fetch(`/api/settings/profiles/${id}`, { method: "DELETE" });
    const json = await res.json();
    if (!res.ok) return onMessage(json?.message || "Delete failed", "error");
    onMessage("Profile deleted", "success");
    load();
  };

  const setDefault = async (id: string) => {
    const res = await fetch(`/api/settings/profiles/${id}/set-default`, { method: "POST" });
    if (!res.ok) {
      const json = await res.json().catch(() => ({}));
      return onMessage(json?.message || "Could not set default", "error");
    }
    onMessage("Default profile updated", "success");
    load();
  };

  if (loading) return <div className="p-6 text-gray-500">Loading profiles...</div>;

  const editing = editingId !== null;

  return (
    <section className="bg-white rounded-xl border p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold">Application Profiles</h2>
          <p className="text-sm text-gray-500">One bundle per role. Each bundle has its own resume, apply-from email, and target titles. The worker picks the matching bundle per job.</p>
        </div>
        {!editing && (
          <button onClick={startCreate} className="px-3 py-1.5 text-sm rounded-lg bg-brand-600 text-white hover:bg-brand-700">+ Add profile</button>
        )}
      </div>

      {!editing && (
        <div className="space-y-2">
          {profiles.map((p) => {
            const resumeFile = p.resume_id ? resumes.find((r) => r.id === p.resume_id)?.file_name : undefined;
            const resumeMissing = !!p.resume_id && !resumeFile;
            return (
            <div key={p.id} className="border rounded-lg p-3 flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium">{p.name}</span>
                  {p.is_default && <span className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded">DEFAULT</span>}
                  {!p.auto_apply && <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">paused</span>}
                  {resumeMissing && <span className="text-xs bg-red-50 text-red-700 px-2 py-0.5 rounded">⚠ missing resume</span>}
                  {!p.application_email && !p.email_account_id && <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded">no apply email</span>}
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {p.application_email || "no email"} · {(p.target_titles || []).slice(0, 3).join(", ") || "no titles"} · resume: {resumeFile || (resumeMissing ? "⚠ deleted" : "none")}
                </div>
              </div>
              <div className="flex gap-2 ml-2">
                {!p.is_default && <button onClick={() => setDefault(p.id)} className="text-xs text-brand-600 hover:underline">Set default</button>}
                <button onClick={() => startEdit(p)} className="text-xs text-gray-700 hover:underline">Edit</button>
                {!p.is_default && <button onClick={() => del(p.id)} className="text-xs text-red-600 hover:underline">Delete</button>}
              </div>
            </div>
          );
          })}
          {profiles.length === 0 && <div className="text-sm text-gray-500">No profiles yet. Add one to get started.</div>}
        </div>
      )}

      {editing && (
        <div className="space-y-3">
          <LabelInput label="Profile name" value={draft.name || ""} onChange={(v) => setDraft({ ...draft, name: v })} placeholder="AI Engineer" />

          <ChipInput label="Target titles" values={draft.target_titles || []} onChange={(v) => setDraft({ ...draft, target_titles: v })} placeholder="AI Engineer, ML Engineer" />
          <ChipInput label="Target keywords" values={draft.target_keywords || []} onChange={(v) => setDraft({ ...draft, target_keywords: v })} placeholder="pytorch, llm" />
          <ChipInput label="Excluded companies" values={draft.excluded_companies || []} onChange={(v) => setDraft({ ...draft, excluded_companies: v })} />
          <ChipInput label="Excluded role keywords" values={draft.excluded_role_keywords || []} onChange={(v) => setDraft({ ...draft, excluded_role_keywords: v })} placeholder="manager, director" />
          <ChipInput label="Excluded levels" values={draft.excluded_levels || []} onChange={(v) => setDraft({ ...draft, excluded_levels: v })} placeholder="staff, principal" />
          <ChipInput label="Preferred locations" values={draft.preferred_locations || []} onChange={(v) => setDraft({ ...draft, preferred_locations: v })} />

          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!draft.remote_only} onChange={(e) => setDraft({ ...draft, remote_only: e.target.checked })} /> Remote only</label>
            <label className="flex items-center gap-2 text-sm">Min salary
              <input type="number" className="border rounded px-2 py-1 w-28" value={draft.min_salary ?? ""} onChange={(e) => setDraft({ ...draft, min_salary: e.target.value ? parseInt(e.target.value) : null })} />
            </label>
          </div>

          <div>
            <label className="text-sm font-medium block mb-1">Resume</label>
            <select className="border rounded px-2 py-1 w-full" value={draft.resume_id || ""} onChange={(e) => setDraft({ ...draft, resume_id: e.target.value || null })}>
              <option value="">(none — upload in Resumes tab)</option>
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
                <select className="border rounded px-2 py-1 w-full" value={draft.email_account_id || ""} onChange={(e) => setDraft({ ...draft, email_account_id: e.target.value || null })}>
                  <option value="">(use inline email field)</option>
                  {emailAccounts.map((e) => <option key={e.id} value={e.id}>{e.email}{e.has_app_password ? " ✓" : ""}</option>)}
                </select>
              </div>
              {!draft.email_account_id && (
                <LabelInput label="Apply-from email (inline)" value={draft.application_email || ""} onChange={(v) => setDraft({ ...draft, application_email: v })} placeholder="you@gmail.com" />
              )}
              <LabelInput
                label={draft.has_app_password ? "Gmail app password (stored ✓ — leave blank to keep, or paste a new one to replace)" : "Gmail app password"}
                value={draft.application_email_app_password || ""}
                onChange={(v) => setDraft({ ...draft, application_email_app_password: v })}
                type="password"
                autoComplete="new-password"
              />
            </>
          )}

          {/* Per-role work & education (mig 020). Different per bundle
              so an AI Eng bundle can emphasize ML wins while a DA bundle
              emphasizes SQL pipelines. Controlled editor — save via the
              profile's Save button. */}
          <div className="border-t pt-3 mt-2">
            <h3 className="text-sm font-semibold mb-2">Work & education</h3>
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

          {/* Content — answers + cover letter — per role. A "Why are you
              interested in AI Engineering?" answer makes no sense on a
              Data Analyst bundle, so these are bundle-scoped (mig 019). */}
          <div className="border-t pt-3 mt-2">
            <h3 className="text-sm font-semibold mb-2">Per-role content</h3>

            <div className="mb-3">
              <label className="text-sm font-medium block mb-1">
                Answer key (JSON)
                <span className="ml-2 text-xs font-normal text-gray-500">
                  Role-specific answers. Key = question slug, value = your answer.
                </span>
              </label>
              <textarea
                rows={6}
                placeholder={'{\n  "why_interested": "Because...",\n  "tell_about_a_project": "I built..."\n}'}
                className="border rounded px-2 py-1 w-full font-mono text-xs"
                value={answerKeyText}
                onChange={(e) => { setAnswerKeyText(e.target.value); setAnswerKeyError(""); }}
              />
              {answerKeyError && (
                <p className="text-xs text-red-600 mt-1">⚠ {answerKeyError}</p>
              )}
              {draft.answer_key_json === null && !answerKeyText && !profiles.find((p) => p.id === editingId)?.is_default && (
                <p className="text-xs text-gray-500 mt-1">
                  Leave blank to inherit the default profile&apos;s answer key.
                </p>
              )}
            </div>

            <div>
              <label className="text-sm font-medium block mb-1">Cover letter template</label>
              <textarea
                rows={6}
                placeholder="Dear {hiring_manager},&#10;&#10;I'm excited to apply for {role} at {company}..."
                className="border rounded px-2 py-1 w-full text-sm"
                value={draft.cover_letter_template || ""}
                onChange={(e) => setDraft({ ...draft, cover_letter_template: e.target.value || null })}
              />
              <p className="text-xs text-gray-500 mt-1">
                Leave blank to inherit the default profile&apos;s template. Placeholders: {"{role}, {company}, {first_name}"} etc.
              </p>
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm pt-2 border-t"><input type="checkbox" checked={draft.auto_apply !== false} onChange={(e) => setDraft({ ...draft, auto_apply: e.target.checked })} /> Active (uncheck to pause this bundle)</label>

          <div className="flex gap-2 pt-2">
            <button onClick={save} className="px-4 py-2 text-sm rounded-lg bg-brand-600 text-white hover:bg-brand-700">Save profile</button>
            <button onClick={cancelEdit} className="px-4 py-2 text-sm rounded-lg border">Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}

function LabelInput({ label, value, onChange, placeholder, type = "text", autoComplete }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string; autoComplete?: string }) {
  return (
    <div>
      <label className="text-sm font-medium block mb-1">{label}</label>
      <input type={type} autoComplete={autoComplete} className="border rounded px-2 py-1 w-full" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  );
}

function ChipInput({ label, values, onChange, placeholder }: { label: string; values: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
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
          <span key={i} className="text-xs bg-gray-100 rounded px-2 py-0.5 flex items-center gap-1">
            {v}
            <button className="text-gray-500 hover:text-red-600" onClick={() => onChange((values || []).filter((_, j) => j !== i))}>×</button>
          </span>
        ))}
      </div>
      <input
        className="border rounded px-2 py-1 w-full"
        value={buf}
        onChange={(e) => setBuf(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); } }}
        onBlur={commit}
        placeholder={placeholder || "type + Enter"}
      />
    </div>
  );
}
