"use client";

import { useEffect, useRef, useState } from "react";
import { Trash2, Plus, ArrowUp, ArrowDown, X } from "lucide-react";
import { fieldClass, buttonClass, FieldLabel, StatusBadge } from "@/components/settings-ui";
import { cn } from "@/lib/utils";

// Desktop Work & Education tab: row-based editors for work_experience[] +
// education[] + skills[]. Ports the web equivalent 1:1 so users on the
// desktop aren't stuck with only the flat current_company / current_title
// fallback (audit flagged as a regression blocker — previously the desktop
// could only write arrays via AI Import paste).
//
// Persistence: on Save, this component PUTs the three arrays to the
// desktop FastAPI /api/profile endpoint (which proxies to Supabase via
// the worker-token auth). Flat fields (current_company/current_title)
// remain in the parent page.tsx and save independently — we don't touch
// them here to keep the edit surface small.

export interface WorkExperienceRow {
  company: string;
  title: string;
  location?: string;
  start_date?: string;
  end_date?: string;
  current?: boolean;
  achievements: string[];
}

export interface EducationRow {
  school: string;
  degree: string;
  field?: string;
  start_date?: string;
  end_date?: string;
  gpa?: string;
}

export function WorkEducationEditor({
  initial,
  onSaved,
  onError,
  onChange,
}: {
  initial: {
    work_experience?: WorkExperienceRow[];
    education?: EducationRow[];
    skills?: string[];
  };
  onSaved?: () => void;
  onError?: (msg: string) => void;
  // Controlled mode: when onChange is passed, the editor fires onChange
  // on every edit and HIDES its internal Save button. The parent owns
  // the save flow (used by ProfilesTab — the profile's Save button
  // persists W&E to user_application_profiles.{work_experience,...}).
  onChange?: (next: {
    work_experience: WorkExperienceRow[];
    education: EducationRow[];
    skills: string[];
  }) => void;
}) {
  const [workRows, setWorkRows] = useState<WorkExperienceRow[]>([]);
  const [eduRows, setEduRows] = useState<EducationRow[]>([]);
  const [skills, setSkills] = useState<string[]>([]);
  const [skillBuf, setSkillBuf] = useState("");
  const [saving, setSaving] = useState(false);
  const controlled = typeof onChange === "function";
  // Same anti-loop ref as the web editor — suppresses the next onChange
  // call whenever we just synced internal state from `initial`. Without
  // this, the controlled-mode sync triggers parent setDraft, which
  // re-renders with a new `initial` literal, which re-syncs, which
  // fires onChange, etc. — visible as the form "glitching" / flashing.
  const skipNextChange = useRef(false);

  useEffect(() => {
    skipNextChange.current = true;
    setWorkRows(initial.work_experience || []);
    setEduRows(initial.education || []);
    setSkills(initial.skills || []);
  }, [initial.work_experience, initial.education, initial.skills]);

  // In controlled mode, push changes upstream whenever any of the three
  // state buckets moves — but skip the first push after an initial sync.
  useEffect(() => {
    if (!controlled) return;
    if (skipNextChange.current) {
      skipNextChange.current = false;
      return;
    }
    onChange?.({ work_experience: workRows, education: eduRows, skills });
  }, [controlled, onChange, workRows, eduRows, skills]);

  const updateWork = (i: number, patch: Partial<WorkExperienceRow>) =>
    setWorkRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addWork = () =>
    setWorkRows((prev) => [
      ...prev,
      { company: "", title: "", location: "", start_date: "", end_date: "Present", current: true, achievements: [] },
    ]);
  const removeWork = (i: number) => setWorkRows((prev) => prev.filter((_, idx) => idx !== i));
  const moveWork = (i: number, dir: -1 | 1) => {
    const target = i + dir;
    if (target < 0 || target >= workRows.length) return;
    const next = [...workRows];
    [next[i], next[target]] = [next[target], next[i]];
    setWorkRows(next);
  };

  const updateEdu = (i: number, patch: Partial<EducationRow>) =>
    setEduRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addEdu = () =>
    setEduRows((prev) => [
      ...prev,
      { school: "", degree: "", field: "", start_date: "", end_date: "", gpa: "" },
    ]);
  const removeEdu = (i: number) => setEduRows((prev) => prev.filter((_, idx) => idx !== i));
  const moveEdu = (i: number, dir: -1 | 1) => {
    const target = i + dir;
    if (target < 0 || target >= eduRows.length) return;
    const next = [...eduRows];
    [next[i], next[target]] = [next[target], next[i]];
    setEduRows(next);
  };

  const addSkill = () => {
    const parts = skillBuf.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) setSkills((prev) => [...prev, ...parts.filter((p) => !prev.includes(p))]);
    setSkillBuf("");
  };

  const save = async () => {
    setSaving(true);
    // Strip empty rows same way the web side does — user shouldn't see
    // phantom blanks round-trip from the server.
    const cleanWork = workRows
      .filter((r) => r.company.trim() || r.title.trim())
      .map((r) => ({
        ...r,
        company: r.company.trim(),
        title: r.title.trim(),
        achievements: (r.achievements || []).map((a) => a.trim()).filter(Boolean),
      }));
    const cleanEdu = eduRows
      .filter((r) => r.school.trim() || r.degree.trim())
      .map((r) => ({ ...r, school: r.school.trim(), degree: r.degree.trim() }));
    try {
      const res = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          work_experience: cleanWork,
          education: cleanEdu,
          skills,
        }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j?.error || `HTTP ${res.status}`);
      }
      setWorkRows(cleanWork);
      setEduRows(cleanEdu);
      onSaved?.();
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Work Experience */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-[13px] font-semibold text-foreground tracking-tight">
            Work experience
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {workRows.length} {workRows.length === 1 ? "role" : "roles"}
            </span>
          </h4>
          <button type="button" onClick={addWork} className={buttonClass.secondary}>
            <Plus className="h-3.5 w-3.5" />
            Add role
          </button>
        </div>
        {workRows.length === 0 && (
          <p className="text-xs text-muted-foreground">No work experience yet. Click Add or use AI Import.</p>
        )}
        <div className="space-y-3">
          {workRows.map((row, i) => (
            <div
              key={i}
              className="rounded-md border border-border bg-[var(--card-subtle)] p-3 space-y-3"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <LabelInput label="Company" value={row.company} onChange={(v) => updateWork(i, { company: v })} />
                <LabelInput label="Title" value={row.title} onChange={(v) => updateWork(i, { title: v })} />
                <LabelInput label="Location" value={row.location || ""} onChange={(v) => updateWork(i, { location: v })} />
                <LabelInput label="Start (YYYY-MM)" value={row.start_date || ""} onChange={(v) => updateWork(i, { start_date: v })} />
                <LabelInput label="End (YYYY-MM or Present)" value={row.end_date || ""} onChange={(v) => updateWork(i, { end_date: v })} />
                <label className="inline-flex items-center gap-2 text-[13px] text-foreground self-end pb-2">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-[var(--border-strong)] text-primary focus:ring-primary/40"
                    checked={!!row.current}
                    onChange={(e) => updateWork(i, { current: e.target.checked })}
                  />
                  Current role
                </label>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <FieldLabel>Achievements</FieldLabel>
                  <button
                    type="button"
                    onClick={() => updateWork(i, { achievements: [...(row.achievements || []), ""] })}
                    className={buttonClass.ghost}
                  >
                    <Plus className="h-3 w-3" />
                    Add bullet
                  </button>
                </div>
                {(row.achievements || []).length === 0 && (
                  <p className="text-xs text-muted-foreground">No bullets yet.</p>
                )}
                {(row.achievements || []).map((a, bi) => (
                  <div key={bi} className="flex gap-1.5 items-start">
                    <input
                      className={cn(fieldClass, "flex-1 text-xs")}
                      value={a}
                      placeholder="e.g. Shipped X that improved Y by Z%"
                      onChange={(e) => {
                        const next = [...(row.achievements || [])];
                        next[bi] = e.target.value;
                        updateWork(i, { achievements: next });
                      }}
                    />
                    <button
                      type="button"
                      onClick={() =>
                        updateWork(i, { achievements: (row.achievements || []).filter((_, x) => x !== bi) })
                      }
                      className={cn(buttonClass.destructive, "mt-0.5")}
                      aria-label="Remove bullet"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>

              <div className="flex items-center gap-1 pt-1 border-t border-border">
                <button type="button" onClick={() => moveWork(i, -1)} className={cn(buttonClass.ghost, "px-1.5")} disabled={i === 0} aria-label="Move up">
                  <ArrowUp className="h-3.5 w-3.5" />
                </button>
                <button type="button" onClick={() => moveWork(i, 1)} className={cn(buttonClass.ghost, "px-1.5")} disabled={i === workRows.length - 1} aria-label="Move down">
                  <ArrowDown className="h-3.5 w-3.5" />
                </button>
                <button type="button" onClick={() => removeWork(i)} className={cn(buttonClass.destructive, "ml-auto")} aria-label="Remove role">
                  <Trash2 className="h-3.5 w-3.5" />
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Education */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-[13px] font-semibold text-foreground tracking-tight">
            Education
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {eduRows.length} {eduRows.length === 1 ? "entry" : "entries"}
            </span>
          </h4>
          <button type="button" onClick={addEdu} className={buttonClass.secondary}>
            <Plus className="h-3.5 w-3.5" />
            Add school
          </button>
        </div>
        {eduRows.length === 0 && (
          <p className="text-xs text-muted-foreground">No education yet. Click Add or use AI Import.</p>
        )}
        <div className="space-y-3">
          {eduRows.map((row, i) => (
            <div
              key={i}
              className="rounded-md border border-border bg-[var(--card-subtle)] p-3 space-y-3"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <LabelInput label="School" value={row.school} onChange={(v) => updateEdu(i, { school: v })} />
                <LabelInput label="Degree" value={row.degree} onChange={(v) => updateEdu(i, { degree: v })} />
                <LabelInput label="Field of study" value={row.field || ""} onChange={(v) => updateEdu(i, { field: v })} />
                <LabelInput label="GPA" value={row.gpa || ""} onChange={(v) => updateEdu(i, { gpa: v })} />
                <LabelInput label="Start (YYYY-MM)" value={row.start_date || ""} onChange={(v) => updateEdu(i, { start_date: v })} />
                <LabelInput label="End (YYYY-MM)" value={row.end_date || ""} onChange={(v) => updateEdu(i, { end_date: v })} />
              </div>
              <div className="flex items-center gap-1 pt-1 border-t border-border">
                <button type="button" onClick={() => moveEdu(i, -1)} className={cn(buttonClass.ghost, "px-1.5")} disabled={i === 0} aria-label="Move up">
                  <ArrowUp className="h-3.5 w-3.5" />
                </button>
                <button type="button" onClick={() => moveEdu(i, 1)} className={cn(buttonClass.ghost, "px-1.5")} disabled={i === eduRows.length - 1} aria-label="Move down">
                  <ArrowDown className="h-3.5 w-3.5" />
                </button>
                <button type="button" onClick={() => removeEdu(i)} className={cn(buttonClass.destructive, "ml-auto")} aria-label="Remove education">
                  <Trash2 className="h-3.5 w-3.5" />
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Skills */}
      <section className="space-y-2">
        <h4 className="text-[13px] font-semibold text-foreground tracking-tight">
          Skills
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {skills.length}
          </span>
        </h4>
        {skills.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {skills.map((s, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 rounded-md bg-secondary border border-border px-2 py-0.5 text-[12px] text-foreground"
              >
                {s}
                <button
                  type="button"
                  onClick={() => setSkills((prev) => prev.filter((_, idx) => idx !== i))}
                  className="text-muted-foreground hover:text-destructive rounded p-0.5 transition-colors"
                  aria-label={`Remove ${s}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        <input
          className={fieldClass}
          value={skillBuf}
          onChange={(e) => setSkillBuf(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              addSkill();
            }
          }}
          onBlur={addSkill}
          placeholder="python, pytorch, sql — press Enter"
        />
      </section>

      {!controlled && (
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className={buttonClass.primary}
        >
          {saving ? "Saving…" : "Save work & education"}
        </button>
      )}
    </div>
  );
}

function LabelInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="space-y-1">
      <FieldLabel>{label}</FieldLabel>
      <input
        className={fieldClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
