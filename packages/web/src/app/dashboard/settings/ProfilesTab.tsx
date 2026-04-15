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
  // Board overrides — null / empty means "use the global default list".
  ashby_boards: string[] | null;
  greenhouse_boards: string[] | null;
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
        // /api/settings/resumes GET returns apiList(rows) which is
        // { object: "list", data: [...resumes] } — the array sits at
        // .data, NOT .data.resumes. Reading the wrong path was why
        // every uploaded PDF appeared to vanish from the dropdown
        // even though the row was created in the DB.
        fetch("/api/settings/resumes").then((r) => r.json()),
        fetch("/api/settings/email-accounts").then((r) => r.json()),
      ]);
      setProfiles(pRes?.data?.profiles || []);
      const resumeList = Array.isArray(rRes?.data) ? rRes.data : (rRes?.data?.resumes || []);
      setResumes(resumeList);
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
      excluded_titles: [],
      excluded_companies: [],
      excluded_role_keywords: [],
      excluded_levels: [],
      preferred_locations: defaultProfile?.preferred_locations || ["United States"],
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

      {/* Every profile renders as an accordion card. Clicking the
          header toggles expansion; the inline editor lives INSIDE the
          card so the user never leaves the Profiles tab. No separate
          "Edit" mode switch — the previous design was flagged because
          it broke the macro-diagram promise of nested sub-sections. */}
      <div className="space-y-2">
        {profiles.map((p) => {
          const isExpanded = editingId === p.id;
          const resumeFile = p.resume_id ? resumes.find((r) => r.id === p.resume_id)?.file_name : undefined;
          const resumeMissing = !!p.resume_id && !resumeFile;
          return (
            <div key={p.id} className="border rounded-lg overflow-hidden">
              {/* Card header — click to expand. Action buttons stop
                  propagation so set-default / delete don't toggle the
                  card open. */}
              <div
                role="button"
                tabIndex={0}
                onClick={() => (isExpanded ? cancelEdit() : startEdit(p))}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); isExpanded ? cancelEdit() : startEdit(p); } }}
                className="p-3 flex items-start justify-between cursor-pointer hover:bg-gray-50 select-none"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-gray-400 text-xs">{isExpanded ? "▼" : "▶"}</span>
                    <span className="font-medium">{p.name}</span>
                    {p.is_default && <span className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded">DEFAULT</span>}
                    {!p.auto_apply && <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">paused</span>}
                    {resumeMissing && <span className="text-xs bg-red-50 text-red-700 px-2 py-0.5 rounded">⚠ missing resume</span>}
                    {!p.application_email && !p.email_account_id && <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded">no apply email</span>}
                  </div>
                  <div className="text-xs text-gray-500 mt-1 ml-4">
                    {p.application_email || "no email"} · {(p.target_titles || []).slice(0, 3).join(", ") || "no titles"} · resume: {resumeFile || (resumeMissing ? "⚠ deleted" : "none")}
                  </div>
                </div>
                <div className="flex gap-2 ml-2" onClick={(e) => e.stopPropagation()}>
                  {!p.is_default && <button onClick={() => setDefault(p.id)} className="text-xs text-brand-600 hover:underline">Set default</button>}
                  {!p.is_default && <button onClick={() => del(p.id)} className="text-xs text-red-600 hover:underline">Delete</button>}
                </div>
              </div>

              {isExpanded && (
                <div className="px-4 pb-4 pt-2 border-t bg-gray-50/50 space-y-3">
                  {renderEditorBody()}
                </div>
              )}
            </div>
          );
        })}

        {/* Empty state — no profiles yet (rare post-backfill, but
            possible for a brand-new user before mig 014 runs). */}
        {profiles.length === 0 && !editingId && (
          <div className="text-sm text-gray-500 p-3 border rounded-lg">No profiles yet. Click "+ Add profile" to create one.</div>
        )}

        {/* New-profile draft renders as a top-of-list expanded card
            with the same editor body. We pull the entire editor JSX
            into a local helper so add + edit share one source. */}
        {editingId === "__new__" && (
          <div className="border-2 border-brand-300 rounded-lg overflow-hidden">
            <div className="p-3 bg-brand-50">
              <span className="text-sm font-medium text-brand-900">+ New profile</span>
            </div>
            <div className="px-4 pb-4 pt-2 border-t bg-gray-50/50 space-y-3">
              {renderEditorBody()}
            </div>
          </div>
        )}
      </div>
    </section>
  );

  // Editor body used by both the expanded card on an existing profile
  // and the new-profile draft. Pulling it into a closure avoids
  // duplicating ~150 lines of form JSX across two render branches.
  function renderEditorBody() {
    return (
      <>
        <LabelInput label="Profile name" value={draft.name || ""} onChange={(v) => setDraft({ ...draft, name: v })} placeholder="AI Engineer" />
        <ChipInput label="Target titles" values={draft.target_titles || []} onChange={(v) => setDraft({ ...draft, target_titles: v })} placeholder="AI Engineer, ML Engineer" />
        <ChipInput label="Target keywords" values={draft.target_keywords || []} onChange={(v) => setDraft({ ...draft, target_keywords: v })} placeholder="pytorch, llm" />
        <ChipInput label="Excluded titles" values={draft.excluded_titles || []} onChange={(v) => setDraft({ ...draft, excluded_titles: v })} placeholder="Sales, Recruiter" />
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

        <div className="border-t pt-3 mt-2">
          <h3 className="text-sm font-semibold mb-1">Board overrides (optional)</h3>
          <p className="text-xs text-gray-500 mb-2">
            Most users leave this blank. Only fill in if you want this profile to scout a specific subset of companies instead of the global default list.
          </p>
          <details className="mb-3 text-xs text-gray-600">
            <summary className="cursor-pointer text-gray-700 hover:text-gray-900">What&apos;s a board?</summary>
            <div className="mt-2 pl-3 border-l-2 border-gray-200 space-y-1">
              <p>
                <strong>Ashby</strong> and <strong>Greenhouse</strong> are job-board platforms. Companies host their job postings under a slug like <code className="bg-gray-100 px-1 rounded">jobs.ashbyhq.com/<span className="text-brand-700">openai</span></code> or <code className="bg-gray-100 px-1 rounded">boards.greenhouse.io/<span className="text-brand-700">stripe</span></code>.
              </p>
              <p>
                Leaving these fields blank means ApplyLoop scouts a curated list of ~hundreds of company slugs we maintain.
              </p>
              <p>
                Override only when you want to scope this profile tightly — e.g. <em>"my Data Analyst bundle should only watch Stripe + Datadog + Airbnb"</em>.
              </p>
              <p>
                <strong>Format:</strong> just the company slug, not the full URL. <code className="bg-gray-100 px-1 rounded">stripe</code>, not <code className="bg-gray-100 px-1 rounded">boards.greenhouse.io/stripe</code>.
              </p>
            </div>
          </details>
          <ChipInput label="Ashby boards" values={draft.ashby_boards || []} onChange={(v) => setDraft({ ...draft, ashby_boards: v.length ? v : null })} placeholder="openai, anthropic, linear" />
          <ChipInput label="Greenhouse boards" values={draft.greenhouse_boards || []} onChange={(v) => setDraft({ ...draft, greenhouse_boards: v.length ? v : null })} placeholder="stripe, airbnb, datadog" />
        </div>

        {/* Resume picker — moved INSIDE the profile (not a separate
            tab anymore). Pool lives in user_resumes; this dropdown
            picks one by id. Upload UX is the same /api/settings/resumes
            POST that the (now-removed) Resumes tab used. */}
        <div className="border-t pt-3 mt-2">
          <h3 className="text-sm font-semibold mb-1">Resume</h3>
          <p className="text-xs text-gray-500 mb-2">PDF used when applying via this profile. Upload a new one below to add to the pool.</p>
          <select className="border rounded px-2 py-1 w-full mb-2" value={draft.resume_id || ""} onChange={(e) => setDraft({ ...draft, resume_id: e.target.value || null })}>
            <option value="">(none)</option>
            {resumes.map((r) => <option key={r.id} value={r.id}>{r.file_name}</option>)}
          </select>
          <InlineResumeUpload
            // Existing-profile edit gets a real id; new-profile draft
            // is null and skips the parse step until first save.
            profileId={editingId !== "__new__" ? editingId : null}
            onUploaded={(rid) => {
              setDraft((d) => ({ ...d, resume_id: rid }));
              load();
            }}
            onParsed={(parsed) => {
              // Merge parsed W&E into the draft so the editor pre-fills.
              // Use functional setState so we don't read a stale draft.
              setDraft((d) => ({
                ...d,
                work_experience: (parsed.work_experience as never) || d.work_experience,
                education: (parsed.education as never) || d.education,
                skills: (parsed.skills as never) || d.skills,
              }));
            }}
          />
        </div>

        {/* Gmail credentials — entirely per-profile now. The shared
            API Keys tab no longer carries gmail_email / gmail_app_password
            because each profile has its own mailbox. Two clear modes
            via radio (instead of the confusing pool dropdown + opaque
            "use inline email below" placeholder). */}
        <div className="border-t pt-3 mt-2">
          <h3 className="text-sm font-semibold mb-1">Apply-from Gmail</h3>
          <p className="text-xs text-gray-500 mb-3">
            This profile sends applications from this Gmail account. Each profile uses its own mailbox so OTP codes route correctly.{" "}
            <span className="text-gray-400">Need an app password? Enable 2FA on your Google account, then generate one at <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer" className="underline">myaccount.google.com/apppasswords</a>.</span>
          </p>

          {(() => {
            const hasPool = emailAccounts.length > 0;
            // Mode resolution: a profile bound to a pool entry is "saved";
            // anything else (inline email or empty) is "new".
            const mode = draft.email_account_id ? "saved" : "new";
            return (
              <div className="space-y-3">
                {hasPool && (
                  <div className="flex gap-4 text-sm">
                    <label className="flex items-center gap-2">
                      <input
                        type="radio"
                        name={`gmail-mode-${editingId || "new"}`}
                        checked={mode === "saved"}
                        onChange={() => setDraft({
                          ...draft,
                          email_account_id: emailAccounts[0].id,
                          // Clear inline fields so the saved account is the source of truth.
                          application_email: "",
                          application_email_app_password: "",
                        })}
                      />
                      Use a saved Gmail account
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="radio"
                        name={`gmail-mode-${editingId || "new"}`}
                        checked={mode === "new"}
                        onChange={() => setDraft({ ...draft, email_account_id: null })}
                      />
                      Enter a new Gmail account
                    </label>
                  </div>
                )}

                {mode === "saved" && hasPool && (
                  <div>
                    <label className="text-sm font-medium block mb-1">Saved account</label>
                    <select
                      className="border rounded px-2 py-1 w-full"
                      value={draft.email_account_id || ""}
                      onChange={(e) => setDraft({ ...draft, email_account_id: e.target.value || null })}
                    >
                      {emailAccounts.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.email}{e.has_app_password ? "  (password saved ✓)" : "  (no password)"}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">Rotating the password? Switch to <strong>Enter a new account</strong> with the same email — it&apos;ll update the saved entry.</p>
                  </div>
                )}

                {mode === "new" && (
                  <>
                    <LabelInput
                      label="Gmail address"
                      value={draft.application_email || ""}
                      onChange={(v) => setDraft({ ...draft, application_email: v })}
                      placeholder="you@gmail.com"
                    />
                    <LabelInput
                      label={draft.has_app_password ? "Gmail app password (stored ✓ — leave blank to keep, paste a new one to replace)" : "Gmail app password"}
                      value={draft.application_email_app_password || ""}
                      onChange={(v) => setDraft({ ...draft, application_email_app_password: v })}
                      type="password"
                      autoComplete="new-password"
                      placeholder="abcd efgh ijkl mnop"
                    />
                    {!hasPool && (
                      <p className="text-xs text-gray-500">This is your first Gmail. After saving, it&apos;ll appear in a <em>Saved accounts</em> picker for any other profiles you create.</p>
                    )}
                  </>
                )}
              </div>
            );
          })()}
        </div>

        <div className="border-t pt-3 mt-2">
          <h3 className="text-sm font-semibold mb-2">Per-role work & education</h3>
          <WorkEducationEditor
            initial={{ work_experience: draft.work_experience || [], education: draft.education || [], skills: draft.skills || [] }}
            onChange={(next) => setDraft((d) => ({ ...d, work_experience: next.work_experience, education: next.education, skills: next.skills }))}
          />
        </div>

        <div className="border-t pt-3 mt-2">
          <h3 className="text-sm font-semibold mb-2">Per-role content</h3>
          <div className="mb-3">
            <label className="text-sm font-medium block mb-1">Answer key (JSON)
              <span className="ml-2 text-xs font-normal text-gray-500">Role-specific Q&amp;A overrides.</span>
            </label>
            <textarea rows={6} placeholder={'{\n  "why_interested": "Because..."\n}'} className="border rounded px-2 py-1 w-full font-mono text-xs" value={answerKeyText} onChange={(e) => { setAnswerKeyText(e.target.value); setAnswerKeyError(""); }} />
            {answerKeyError && <p className="text-xs text-red-600 mt-1">⚠ {answerKeyError}</p>}
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">Cover letter template</label>
            <textarea rows={6} placeholder="Dear {hiring_manager},..." className="border rounded px-2 py-1 w-full text-sm" value={draft.cover_letter_template || ""} onChange={(e) => setDraft({ ...draft, cover_letter_template: e.target.value || null })} />
            <p className="text-xs text-gray-500 mt-1">Leave blank to inherit the default profile&apos;s template.</p>
          </div>
        </div>

        <div className="flex items-center gap-4 pt-2 border-t">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={draft.auto_apply !== false} onChange={(e) => setDraft({ ...draft, auto_apply: e.target.checked })} /> Active (uncheck to pause this bundle)
          </label>
          <label className="flex items-center gap-2 text-sm">
            Max daily
            <input type="number" min={0} placeholder="no cap" className="border rounded px-2 py-1 w-24" value={draft.max_daily ?? ""} onChange={(e) => setDraft({ ...draft, max_daily: e.target.value ? parseInt(e.target.value) : null })} />
          </label>
        </div>

        <div className="flex gap-2 pt-2">
          <button onClick={save} className="px-4 py-2 text-sm rounded-lg bg-brand-600 text-white hover:bg-brand-700">Save profile</button>
          <button onClick={cancelEdit} className="px-4 py-2 text-sm rounded-lg border">Cancel</button>
        </div>
      </>
    );
  }
}

function LabelInput({ label, value, onChange, placeholder, type = "text", autoComplete }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string; autoComplete?: string }) {
  return (
    <div>
      <label className="text-sm font-medium block mb-1">{label}</label>
      <input type={type} autoComplete={autoComplete} className="border rounded px-2 py-1 w-full" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  );
}

/**
 * Inline resume upload — three-step UX:
 *   1. POST /api/settings/resumes (file → user_resumes row in DB)
 *   2. POST /api/profile/extract-resume?resume_id=&profile_id= (parse
 *      PDF via OpenAI gpt-4o, get back work_experience / education /
 *      skills, write them onto THIS profile bundle)
 *   3. Surface success + parsed counts so the user can see what landed
 *
 * Calls onUploaded(resumeId) after step 1 so the parent dropdown re-
 * binds immediately. Calls onParsed(parsed) after step 2 so the
 * WorkEducationEditor pre-fills with the parsed entries.
 *
 * profileId is optional — when null (e.g. new-profile draft has no id
 * yet), step 2 is skipped and the user can save the profile then run
 * AI Import manually. Most editing happens on existing profiles where
 * profileId is set.
 */
function InlineResumeUpload({
  profileId,
  onUploaded,
  onParsed,
}: {
  profileId: string | null;
  onUploaded: (resumeId: string) => void;
  onParsed?: (parsed: { work_experience?: unknown[]; education?: unknown[]; skills?: unknown[] }) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<"idle" | "uploading" | "parsing">("idle");
  const [error, setError] = useState<string>("");
  const [success, setSuccess] = useState<string>("");

  const upload = async () => {
    if (!file) return;
    setError("");
    setSuccess("");

    // Step 1: upload PDF to storage + create user_resumes row.
    setPhase("uploading");
    let newResumeId: string | null = null;
    try {
      const fd = new FormData();
      fd.append("resume", file);
      fd.append("is_default", "false");
      const res = await fetch("/api/settings/resumes", { method: "POST", body: fd });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(json?.message || `Upload HTTP ${res.status}`);
        setPhase("idle");
        return;
      }
      newResumeId = json?.data?.resume?.id || null;
      if (!newResumeId) {
        // Visible failure — diagnose shape mismatches in console too.
        console.warn("InlineResumeUpload: POST /resumes returned no id", json);
        setError("Upload succeeded but the server returned no resume id");
        setPhase("idle");
        return;
      }
      onUploaded(newResumeId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error during upload");
      setPhase("idle");
      return;
    }

    // Step 2: parse with OpenAI scoped to THIS resume + profile.
    // Skip if we don't have a profile id yet (new-profile draft).
    if (!profileId) {
      setSuccess(`Uploaded ${file.name}. Save the profile, then re-open to AI-parse.`);
      setFile(null);
      setPhase("idle");
      return;
    }

    setPhase("parsing");
    try {
      const url = `/api/profile/extract-resume?resume_id=${encodeURIComponent(newResumeId)}&profile_id=${encodeURIComponent(profileId)}`;
      const res = await fetch(url, { method: "POST" });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(json?.message || `Parse HTTP ${res.status}`);
        setPhase("idle");
        return;
      }
      // The route returns the same shape as before; the parsed fields
      // are NOT in the response body (it stores them and reports
      // populated[] only). To pre-fill the editor we re-fetch the
      // profile so the freshly-written W&E flow back into draft state.
      // Cheaper than re-parsing client-side and stays consistent with
      // what the worker will read at apply time.
      const refresh = await fetch(`/api/settings/profiles`).then((r) => r.json()).catch(() => null);
      const updatedProfile = refresh?.data?.profiles?.find((p: { id: string }) => p.id === profileId);
      if (updatedProfile && onParsed) {
        onParsed({
          work_experience: updatedProfile.work_experience || [],
          education: updatedProfile.education || [],
          skills: updatedProfile.skills || [],
        });
      }
      const populated: string[] = Array.isArray(json?.data?.populated) ? json.data.populated : [];
      const wCount = (updatedProfile?.work_experience as unknown[] | undefined)?.length ?? 0;
      const eCount = (updatedProfile?.education as unknown[] | undefined)?.length ?? 0;
      const sCount = (updatedProfile?.skills as unknown[] | undefined)?.length ?? 0;
      setSuccess(
        populated.length === 0
          ? "Resume uploaded. AI parser found nothing new to add."
          : `Imported ${wCount} job${wCount === 1 ? "" : "s"}, ${eCount} education entr${eCount === 1 ? "y" : "ies"}, ${sCount} skills.`
      );
      setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Parse failed");
    } finally {
      setPhase("idle");
    }
  };

  const buttonLabel =
    phase === "uploading" ? "Uploading…" :
    phase === "parsing" ? "Parsing with AI…" :
    "Upload PDF";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <input
          type="file"
          accept=".pdf,application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="text-xs flex-1"
          disabled={phase !== "idle"}
        />
        <button
          type="button"
          onClick={upload}
          disabled={!file || phase !== "idle"}
          className="text-xs px-3 py-1 rounded border bg-white hover:bg-gray-50 disabled:opacity-50"
        >
          {buttonLabel}
        </button>
      </div>
      {phase === "parsing" && (
        <p className="text-xs text-gray-600">⏳ Reading your resume with AI to fill Work Experience, Education, and Skills below…</p>
      )}
      {success && <p className="text-xs text-green-700">✓ {success}</p>}
      {error && <p className="text-xs text-red-600">⚠ {error}</p>}
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
