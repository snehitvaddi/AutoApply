"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Plus, X, Loader2, Check, AlertTriangle } from "lucide-react";
import { WorkEducationEditor, type WorkExperienceRow, type EducationRow } from "./WorkEducationEditor";
import {
  Section,
  SectionDivider,
  FormRow,
  FieldLabel,
  InlineHint,
  StatusBadge,
  fieldClass,
  buttonClass,
} from "@/components/settings-ui";
import { cn } from "@/lib/utils";

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
  // See web ProfilesTab — bumps on every successful resume parse so the
  // WorkEducationEditor remounts via React key and pulls the parsed
  // values out of `initial` cleanly without the onChange-loop glitch.
  const [parseSeq, setParseSeq] = useState(0);

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
        // /api/resumes proxies to the cloud /api/settings/resumes which
        // returns apiList(rows) → { object: "list", data: [...] }. The
        // FastAPI wraps it as { ok, data: <that> }, so the array sits
        // at .data.data. Read both shapes defensively.
        safe(call("/api/resumes"), { data: { data: [] } }),
        safe(call("/api/email-accounts"), { data: { email_accounts: [] } }),
      ]);
      setProfiles(p?.data?.profiles || []);
      // Handle both apiList shape (.data.data) and the legacy
      // { resumes: [] } shape.
      const rd = r?.data;
      const rawResumeList: Resume[] = Array.isArray(rd?.data) ? rd.data : (Array.isArray(rd) ? rd : (rd?.resumes || []));
      // Dedupe by file_name — the desktop dropdown was showing the
      // same PDF 7 times because every re-upload INSERTed a new
      // user_resumes row. Server-side upsert (proxy upload_resume
      // + cloud /api/settings/resumes) now prevents fresh dupes;
      // this guards legacy rows that already exist.
      const seen = new Set<string>();
      const resumeList = rawResumeList.filter((r) => {
        if (seen.has(r.file_name)) return false;
        seen.add(r.file_name);
        return true;
      });
      setResumes(resumeList);
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

  // The editor body — used inline by both an expanded existing-profile
  // card AND the new-profile draft. Keeping the form here as a closure
  // means the rendering JSX stays a single source of truth.
  // Active resume, if any — for the "Current resume" display at the
  // top of the editor.
  const activeResume = resumes.find((r) => r.id === draft.resume_id);

  const editorBody = (
      <div className="space-y-5">
        {/* Resume-first layout. Per user feedback (Apr 2026) the
            resume is the single most critical artifact — worker blocks
            with awaiting_resume_upload when it's missing — so it lives
            at the TOP of the editor, above Essentials. The old order
            buried it below Exclusions / Location which made new users
            scroll past ~five sections to get to the critical upload. */}
        <Section
          title="Resume"
          description="PDF used when applying via this profile. Re-uploading the same filename updates the existing entry (no more dropdown bloat)."
        >
          <div className="text-[13px] text-foreground">
            {activeResume
              ? <>Active: <span className="font-mono">{activeResume.file_name}</span></>
              : <span className="text-muted-foreground">No resume selected yet — upload one below.</span>}
          </div>
          {/* Only show the picker when the user actually has
              multiple DISTINCT resumes (dedup is applied in load()),
              otherwise it's noise. The file-upload input is the
              single way to add or replace a resume. */}
          {resumes.length > 1 && (
            <FormRow label="Switch resume">
              <select
                className={fieldClass}
                value={draft.resume_id || ""}
                onChange={(e) => setDraft({ ...draft, resume_id: e.target.value || null })}
              >
                <option value="">(none)</option>
                {resumes.map((r) => <option key={r.id} value={r.id}>{r.file_name}</option>)}
              </select>
            </FormRow>
          )}
          <DesktopInlineResumeUpload
            profileId={editingId !== "__new__" ? editingId : null}
            onUploaded={(rid) => { setDraft((d) => ({ ...d, resume_id: rid })); load(); }}
            onParsed={(parsed) => {
              setDraft((d) => ({
                ...d,
                work_experience: (parsed.work_experience as never) || d.work_experience,
                education: (parsed.education as never) || d.education,
                skills: (parsed.skills as never) || d.skills,
              }));
              setParseSeq((n) => n + 1);
            }}
          />
        </Section>

        <Section
          title="Essentials"
          description="What to apply to. Profile name and at least one target title are required; everything else is optional."
        >
          <TextField
            label="Profile name"
            required
            placeholder="e.g. AI Engineer · Remote US"
            value={draft.name || ""}
            onChange={(v) => setDraft({ ...draft, name: v })}
          />
          <ChipField
            label="Target titles"
            hint="Scout matches jobs whose title contains any of these. Required — add at least one."
            values={draft.target_titles || []}
            onChange={(v) => setDraft({ ...draft, target_titles: v })}
          />
          <ChipField
            label="Target keywords"
            hint="Optional: bias scout toward postings mentioning these words in the description."
            values={draft.target_keywords || []}
            onChange={(v) => setDraft({ ...draft, target_keywords: v })}
          />
          <SectionDivider label="Exclusions" />
          <ChipField
            label="Excluded titles"
            values={draft.excluded_titles || []}
            onChange={(v) => setDraft({ ...draft, excluded_titles: v })}
          />
          <ChipField
            label="Excluded companies"
            values={draft.excluded_companies || []}
            onChange={(v) => setDraft({ ...draft, excluded_companies: v })}
          />
          <ChipField
            label="Excluded role keywords"
            values={draft.excluded_role_keywords || []}
            onChange={(v) => setDraft({ ...draft, excluded_role_keywords: v })}
          />
          <ChipField
            label="Excluded levels"
            hint="e.g. Senior, Staff, Principal — to filter out roles above your stage."
            values={draft.excluded_levels || []}
            onChange={(v) => setDraft({ ...draft, excluded_levels: v })}
          />
          <SectionDivider label="Location & compensation" />
          <ChipField
            label="Preferred locations"
            values={draft.preferred_locations || []}
            onChange={(v) => setDraft({ ...draft, preferred_locations: v })}
          />
          <div className="flex flex-wrap items-center gap-5">
            <label className="inline-flex items-center gap-2 text-[13px] text-foreground cursor-pointer">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-[var(--border-strong)] text-primary focus:ring-primary/40"
                checked={!!draft.remote_only}
                onChange={(e) => setDraft({ ...draft, remote_only: e.target.checked })}
              />
              Remote only
            </label>
            <label className="inline-flex items-center gap-2 text-[13px] text-foreground">
              <span>Min salary</span>
              <input
                type="number"
                className={cn(fieldClass, "w-32")}
                placeholder="no floor"
                value={draft.min_salary ?? ""}
                onChange={(e) => setDraft({ ...draft, min_salary: e.target.value ? parseInt(e.target.value) : null })}
              />
            </label>
          </div>
        </Section>

        <Section
          title="Apply-from Gmail"
          description="This profile sends applications from this mailbox. OTP codes route back here, so each profile should use its own dedicated Gmail."
        >
          <InlineHint variant="info">
            Need an app password? Enable 2FA on your Google account, then generate one at{" "}
            <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">
              myaccount.google.com/apppasswords
            </a>
            .
          </InlineHint>
          {(() => {
            const hasPool = emailAccounts.length > 0;
            const mode = draft.email_account_id ? "saved" : "new";
            return (
              <div className="space-y-3">
                {hasPool && (
                  <div className="flex flex-wrap gap-x-5 gap-y-2">
                    <label className="inline-flex items-center gap-2 text-[13px] text-foreground cursor-pointer">
                      <input
                        type="radio"
                        name={`gmail-mode-${editingId || "new"}`}
                        className="h-4 w-4 text-primary focus:ring-primary/40"
                        checked={mode === "saved"}
                        onChange={() => setDraft({
                          ...draft,
                          email_account_id: emailAccounts[0].id,
                          application_email: "",
                          application_email_app_password: "",
                        })}
                      />
                      Use a saved Gmail account
                    </label>
                    <label className="inline-flex items-center gap-2 text-[13px] text-foreground cursor-pointer">
                      <input
                        type="radio"
                        name={`gmail-mode-${editingId || "new"}`}
                        className="h-4 w-4 text-primary focus:ring-primary/40"
                        checked={mode === "new"}
                        onChange={() => setDraft({ ...draft, email_account_id: null })}
                      />
                      Enter a new Gmail account
                    </label>
                  </div>
                )}

                {mode === "saved" && hasPool && (
                  <FormRow
                    label="Saved account"
                    hint="Rotating the password? Switch to 'Enter a new account' with the same email — it'll update the saved entry."
                  >
                    <select
                      className={fieldClass}
                      value={draft.email_account_id || ""}
                      onChange={(e) => setDraft({ ...draft, email_account_id: e.target.value || null })}
                    >
                      {emailAccounts.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.email}{e.has_app_password ? "  (password saved ✓)" : "  (no password)"}
                        </option>
                      ))}
                    </select>
                  </FormRow>
                )}

                {mode === "new" && (
                  <>
                    <TextField
                      label="Gmail address"
                      placeholder="you@gmail.com"
                      value={draft.application_email || ""}
                      onChange={(v) => setDraft({ ...draft, application_email: v })}
                    />
                    <TextField
                      label="Gmail app password"
                      type="password"
                      autoComplete="new-password"
                      placeholder={draft.has_app_password ? "Leave blank to keep the saved password" : "16-character app password"}
                      status={draft.has_app_password ? <StatusBadge variant="success">Saved</StatusBadge> : undefined}
                      hint={draft.has_app_password ? "A password is already stored. Leave blank to keep it." : undefined}
                      value={draft.application_email_app_password || ""}
                      onChange={(v) => setDraft({ ...draft, application_email_app_password: v })}
                    />
                    {!hasPool && (
                      <p className="text-xs text-muted-foreground">
                        This is your first Gmail. After saving, it&apos;ll appear in a <em>Saved accounts</em> picker for any other profiles you create.
                      </p>
                    )}
                  </>
                )}
              </div>
            );
          })()}
        </Section>

        <Section
          title="Work history & education"
          description="Per-profile story — each bundle can highlight different achievements (AI Eng vs DA etc.). Upload a PDF above to auto-fill via AI."
        >
          <WorkEducationEditor
            key={`woe-${editingId}-${parseSeq}`}
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
        </Section>

        <Section
          title="Cover letter & answer key"
          description="Role-specific content so 'Why AI Engineering?' doesn't leak onto a Data Analyst app."
        >
          <FormRow
            label="Answer key (JSON)"
            hint="Role-specific answers the applier reuses on every submission."
            error={answerKeyError}
          >
            <textarea
              rows={6}
              placeholder={'{\n  "why_interested": "Because..."\n}'}
              className={cn(fieldClass, "font-mono text-xs resize-y min-h-28")}
              value={answerKeyText}
              onChange={(e) => { setAnswerKeyText(e.target.value); setAnswerKeyError(""); }}
            />
          </FormRow>
          <FormRow
            label="Cover letter template"
            hint="Leave blank to inherit the default profile's template."
          >
            <textarea
              rows={6}
              placeholder="Dear {hiring_manager},&#10;&#10;I'm excited to apply for {role} at {company}..."
              className={cn(fieldClass, "resize-y min-h-28")}
              value={draft.cover_letter_template || ""}
              onChange={(e) => setDraft({ ...draft, cover_letter_template: e.target.value || null })}
            />
          </FormRow>
        </Section>

        <Section
          title="Board overrides (optional)"
          description="Leave blank to use the global curated list. Only fill in if this profile should scout a specific subset of companies."
          tone="subtle"
        >
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer text-foreground hover:text-primary font-medium text-[13px]">
              What&apos;s a board?
            </summary>
            <div className="mt-2 pl-3 border-l-2 border-border space-y-1 leading-relaxed">
              <p>
                <strong className="text-foreground">Ashby</strong> and <strong className="text-foreground">Greenhouse</strong> are job-board platforms. Companies host their job postings under a slug like{" "}
                <code className="bg-muted px-1 rounded font-mono text-[11px]">jobs.ashbyhq.com/<span className="text-primary">openai</span></code> or{" "}
                <code className="bg-muted px-1 rounded font-mono text-[11px]">boards.greenhouse.io/<span className="text-primary">stripe</span></code>.
              </p>
              <p>Leaving these fields blank means ApplyLoop scouts a curated list of ~hundreds of company slugs we maintain.</p>
              <p><strong className="text-foreground">Format:</strong> just the company slug, not the full URL. <code className="bg-muted px-1 rounded font-mono text-[11px]">stripe</code>, not <code className="bg-muted px-1 rounded font-mono text-[11px]">boards.greenhouse.io/stripe</code>.</p>
            </div>
          </details>
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
        </Section>

        <Section
          title="Profile controls"
        >
          <div className="flex flex-wrap items-center gap-5">
            <label className="inline-flex items-center gap-2 text-[13px] text-foreground cursor-pointer">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-[var(--border-strong)] text-primary focus:ring-primary/40"
                checked={draft.auto_apply !== false}
                onChange={(e) => setDraft({ ...draft, auto_apply: e.target.checked })}
              />
              Active
              <span className="text-xs text-muted-foreground ml-1">(auto-apply enabled)</span>
            </label>
            <label className="inline-flex items-center gap-2 text-[13px] text-foreground">
              <span>Max daily applications</span>
              <input
                type="number"
                min={0}
                placeholder="no cap"
                className={cn(fieldClass, "w-28")}
                value={draft.max_daily ?? ""}
                onChange={(e) => setDraft({ ...draft, max_daily: e.target.value ? parseInt(e.target.value) : null })}
              />
            </label>
          </div>
        </Section>

        <div className="flex items-center gap-2 pt-2">
          <button type="button" onClick={save} className={buttonClass.primary}>
            Save profile
          </button>
          <button
            type="button"
            onClick={() => { setEditingId(null); setDraft({}); }}
            className={buttonClass.secondary}
          >
            Cancel
          </button>
        </div>
      </div>
  );

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

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
          Each profile binds its own resume, apply-from email, and target titles. Click a card to expand and edit.
        </p>
        <button type="button" onClick={startCreate} className={buttonClass.primary}>
          <Plus className="h-4 w-4" />
          New profile
        </button>
      </div>

      {editingId === "__new__" && (
        <div className="rounded-lg border-2 border-primary/40 bg-card overflow-hidden shadow-sm">
          <div className="flex items-center gap-2 px-4 py-3 bg-[var(--primary-subtle)] border-b border-primary/20">
            <Plus className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold text-foreground">New profile</span>
          </div>
          <div className="p-4">{editorBody}</div>
        </div>
      )}

      {profiles.map((p) => {
        const isExpanded = editingId === p.id;
        const resumeFile = p.resume_id ? resumes.find((r) => r.id === p.resume_id)?.file_name : undefined;
        const resumeMissing = !!p.resume_id && !resumeFile;
        const noEmail = !p.application_email && !p.email_account_id;
        return (
          <div
            key={p.id}
            className={cn(
              "rounded-lg border bg-card overflow-hidden shadow-xs transition-shadow",
              isExpanded ? "border-primary/40 shadow-sm" : "border-border hover:shadow-sm",
            )}
          >
            <div
              role="button"
              tabIndex={0}
              onClick={() => (isExpanded ? cancelEdit() : startEdit(p))}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); isExpanded ? cancelEdit() : startEdit(p); } }}
              className="flex items-start justify-between gap-3 p-4 cursor-pointer hover:bg-secondary/60 select-none transition-colors"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  {isExpanded
                    ? <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                    : <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />}
                  <span className="font-semibold text-[15px] text-foreground truncate">{p.name}</span>
                  {p.is_default && <StatusBadge variant="success">Default</StatusBadge>}
                  {!p.auto_apply && <StatusBadge>Paused</StatusBadge>}
                  {resumeMissing && (
                    <StatusBadge variant="error">
                      <AlertTriangle className="h-3 w-3" />
                      Missing resume
                    </StatusBadge>
                  )}
                  {noEmail && (
                    <StatusBadge variant="warn">
                      <AlertTriangle className="h-3 w-3" />
                      No apply email
                    </StatusBadge>
                  )}
                </div>
                <div className="text-xs text-muted-foreground mt-1.5 ml-6 truncate font-mono">
                  {p.application_email || "no email"}
                  <span className="text-border mx-2">·</span>
                  {(p.target_titles || []).slice(0, 3).join(", ") || "no titles"}
                  <span className="text-border mx-2">·</span>
                  resume: {resumeFile || (resumeMissing ? "deleted" : "none")}
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                {!p.is_default && (
                  <button
                    type="button"
                    onClick={() => setDefault(p.id)}
                    className={buttonClass.ghost}
                  >
                    Make default
                  </button>
                )}
                {!p.is_default && (
                  <button
                    type="button"
                    onClick={() => del(p.id)}
                    className={buttonClass.destructive}
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
            {isExpanded && (
              <div className="px-4 pb-4 pt-1 border-t border-border">
                {editorBody}
              </div>
            )}
          </div>
        );
      })}
      {profiles.length === 0 && editingId !== "__new__" && (
        <div className="rounded-lg border border-dashed border-border bg-[var(--card-subtle)] p-8 text-center">
          <p className="text-sm text-muted-foreground mb-3">No profiles yet.</p>
          <button type="button" onClick={startCreate} className={buttonClass.primary}>
            <Plus className="h-4 w-4" />
            Create your first profile
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Inline resume upload for the desktop ProfilesTab. Three steps:
 *   1. POST /api/resumes (FastAPI proxies to cloud /api/settings/resumes)
 *   2. POST /api/profile/extract-resume?resume_id=&profile_id= (FastAPI
 *      proxies to the cloud parser) — fills the profile's W&E from the PDF
 *   3. Call onParsed(refreshed) so the in-form WorkEducationEditor
 *      pre-fills with what the AI extracted.
 *
 * profileId optional — when null (new-profile draft), step 2 is skipped.
 */
function DesktopInlineResumeUpload({
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

    setPhase("uploading");
    let newResumeId: string | null = null;
    try {
      // Desktop has /api/resumes/upload (existing route) which expects
      // multipart "file" + form "is_default" boolean. The cloud proxy
      // returns { ok, data: { resume: { id, ... } } }.
      const fd = new FormData();
      fd.append("file", file);
      fd.append("is_default", "false");
      const res = await fetch("/api/resumes/upload", { method: "POST", body: fd });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || !json?.ok) {
        setError(json?.detail || json?.error || `Upload HTTP ${res.status}`);
        setPhase("idle");
        return;
      }
      newResumeId = json?.data?.resume?.id || null;
      if (!newResumeId) {
        console.warn("DesktopInlineResumeUpload: POST /resumes returned no id", json);
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
      if (!res.ok || (json?.ok === false)) {
        setError(json?.detail || json?.error || json?.message || `Parse HTTP ${res.status}`);
        setPhase("idle");
        return;
      }
      // Re-fetch the profile so the freshly-written W&E flow back into draft.
      const refresh = await fetch("/api/profiles").then((r) => r.json()).catch(() => null);
      const updatedProfile = refresh?.data?.profiles?.find((p: { id: string }) => p.id === profileId);
      if (updatedProfile && onParsed) {
        onParsed({
          work_experience: updatedProfile.work_experience || [],
          education: updatedProfile.education || [],
          skills: updatedProfile.skills || [],
        });
      }
      const wCount = (updatedProfile?.work_experience as unknown[] | undefined)?.length ?? 0;
      const eCount = (updatedProfile?.education as unknown[] | undefined)?.length ?? 0;
      const sCount = (updatedProfile?.skills as unknown[] | undefined)?.length ?? 0;
      setSuccess(
        wCount + eCount + sCount === 0
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
          // BOTH MIME and extension — macOS Finder greyed out PDFs
          // when only one was specified, depending on how the file
          // was downloaded. Belt-and-suspenders fixes the dimmed
          // file-picker issue users reported.
          accept="application/pdf,.pdf"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          className={cn(
            fieldClass,
            "flex-1 text-xs p-1.5 file:mr-2 file:rounded file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-xs file:text-foreground hover:file:bg-muted",
          )}
          disabled={phase !== "idle"}
        />
        <button
          type="button"
          onClick={upload}
          disabled={!file || phase !== "idle"}
          className={buttonClass.secondary}
        >
          {phase !== "idle" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {buttonLabel}
        </button>
      </div>
      {phase === "parsing" && (
        <InlineHint variant="info">Reading your resume with AI to fill Work Experience, Education, and Skills below…</InlineHint>
      )}
      {success && (
        <p className="text-xs text-[color:var(--success)] inline-flex items-center gap-1">
          <Check className="h-3 w-3" />
          {success}
        </p>
      )}
      {error && (
        <p className="text-xs text-destructive inline-flex items-center gap-1">
          <AlertTriangle className="h-3 w-3" />
          {error}
        </p>
      )}
    </div>
  );
}

function TextField({
  label, value, onChange, type = "text", autoComplete, placeholder, required, hint, status,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  autoComplete?: string
  placeholder?: string
  required?: boolean
  hint?: string
  status?: React.ReactNode
}) {
  return (
    <FormRow label={label} required={required} hint={hint} status={status}>
      <input
        type={type}
        autoComplete={autoComplete}
        placeholder={placeholder}
        className={fieldClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </FormRow>
  );
}

function ChipField({ label, values, onChange, hint, placeholder = "type + Enter" }: { label: string; values: string[]; onChange: (v: string[]) => void; hint?: string; placeholder?: string }) {
  const [buf, setBuf] = useState("");
  const commit = () => {
    const parts = buf.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...(values || []), ...parts]);
    setBuf("");
  };
  return (
    <FormRow label={label} hint={hint}>
      {(values || []).length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {(values || []).map((v, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded-md bg-secondary border border-border px-2 py-0.5 text-[12px] text-foreground"
            >
              {v}
              <button
                type="button"
                aria-label={`Remove ${v}`}
                onClick={() => onChange((values || []).filter((_, j) => j !== i))}
                className="text-muted-foreground hover:text-destructive rounded p-0.5 transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        className={fieldClass}
        value={buf}
        onChange={(e) => setBuf(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          }
        }}
        onBlur={commit}
        placeholder={placeholder}
      />
    </FormRow>
  );
}
