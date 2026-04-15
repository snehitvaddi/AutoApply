"use client";

import { useEffect, useRef, useState } from "react";
import { Trash2, Plus, ArrowUp, ArrowDown } from "lucide-react";

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
    <div className="space-y-6">
      {/* Work Experience */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold">Work Experience</h3>
          <button onClick={addWork} className="text-xs px-2 py-1 rounded-lg border hover:bg-muted flex items-center gap-1">
            <Plus className="h-3 w-3" /> Add
          </button>
        </div>
        {workRows.length === 0 && (
          <p className="text-xs text-muted-foreground">No work experience yet. Click Add or use AI Import.</p>
        )}
        <div className="space-y-3">
          {workRows.map((row, i) => (
            <div key={i} className="border rounded-lg p-3 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <LabelInput label="Company" value={row.company} onChange={(v) => updateWork(i, { company: v })} />
                <LabelInput label="Title" value={row.title} onChange={(v) => updateWork(i, { title: v })} />
                <LabelInput label="Location" value={row.location || ""} onChange={(v) => updateWork(i, { location: v })} />
                <LabelInput label="Start (YYYY-MM)" value={row.start_date || ""} onChange={(v) => updateWork(i, { start_date: v })} />
                <LabelInput label="End (YYYY-MM or Present)" value={row.end_date || ""} onChange={(v) => updateWork(i, { end_date: v })} />
                <label className="flex items-center gap-2 text-xs self-end">
                  <input type="checkbox" checked={!!row.current} onChange={(e) => updateWork(i, { current: e.target.checked })} /> Current
                </label>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-medium">Achievements</label>
                  <button
                    onClick={() => updateWork(i, { achievements: [...(row.achievements || []), ""] })}
                    className="text-xs px-2 py-0.5 rounded border hover:bg-muted"
                  >
                    + Bullet
                  </button>
                </div>
                {(row.achievements || []).map((a, bi) => (
                  <div key={bi} className="flex gap-1 mb-1">
                    <input
                      className="flex-1 border rounded px-2 py-1 text-xs bg-background"
                      value={a}
                      onChange={(e) => {
                        const next = [...(row.achievements || [])];
                        next[bi] = e.target.value;
                        updateWork(i, { achievements: next });
                      }}
                    />
                    <button
                      onClick={() =>
                        updateWork(i, { achievements: (row.achievements || []).filter((_, x) => x !== bi) })
                      }
                      className="text-destructive hover:bg-muted rounded px-1"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>

              <div className="flex gap-1">
                <button onClick={() => moveWork(i, -1)} className="text-xs p-1 rounded border hover:bg-muted" disabled={i === 0}>
                  <ArrowUp className="h-3 w-3" />
                </button>
                <button onClick={() => moveWork(i, 1)} className="text-xs p-1 rounded border hover:bg-muted" disabled={i === workRows.length - 1}>
                  <ArrowDown className="h-3 w-3" />
                </button>
                <button onClick={() => removeWork(i)} className="text-xs p-1 rounded border text-destructive hover:bg-muted ml-auto">
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Education */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold">Education</h3>
          <button onClick={addEdu} className="text-xs px-2 py-1 rounded-lg border hover:bg-muted flex items-center gap-1">
            <Plus className="h-3 w-3" /> Add
          </button>
        </div>
        {eduRows.length === 0 && (
          <p className="text-xs text-muted-foreground">No education yet. Click Add or use AI Import.</p>
        )}
        <div className="space-y-3">
          {eduRows.map((row, i) => (
            <div key={i} className="border rounded-lg p-3 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <LabelInput label="School" value={row.school} onChange={(v) => updateEdu(i, { school: v })} />
                <LabelInput label="Degree" value={row.degree} onChange={(v) => updateEdu(i, { degree: v })} />
                <LabelInput label="Field of Study" value={row.field || ""} onChange={(v) => updateEdu(i, { field: v })} />
                <LabelInput label="GPA" value={row.gpa || ""} onChange={(v) => updateEdu(i, { gpa: v })} />
                <LabelInput label="Start (YYYY-MM)" value={row.start_date || ""} onChange={(v) => updateEdu(i, { start_date: v })} />
                <LabelInput label="End (YYYY-MM)" value={row.end_date || ""} onChange={(v) => updateEdu(i, { end_date: v })} />
              </div>
              <div className="flex gap-1">
                <button onClick={() => moveEdu(i, -1)} className="text-xs p-1 rounded border hover:bg-muted" disabled={i === 0}>
                  <ArrowUp className="h-3 w-3" />
                </button>
                <button onClick={() => moveEdu(i, 1)} className="text-xs p-1 rounded border hover:bg-muted" disabled={i === eduRows.length - 1}>
                  <ArrowDown className="h-3 w-3" />
                </button>
                <button onClick={() => removeEdu(i)} className="text-xs p-1 rounded border text-destructive hover:bg-muted ml-auto">
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Skills */}
      <section>
        <h3 className="text-sm font-semibold mb-2">Skills</h3>
        <div className="flex flex-wrap gap-1 mb-2">
          {skills.map((s, i) => (
            <span key={i} className="text-xs bg-muted rounded px-2 py-0.5 flex items-center gap-1">
              {s}
              <button
                onClick={() => setSkills((prev) => prev.filter((_, idx) => idx !== i))}
                className="hover:text-destructive"
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <input
          className="border rounded px-2 py-1 w-full bg-background text-sm"
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
          onClick={save}
          disabled={saving}
          className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save work & education"}
        </button>
      )}
    </div>
  );
}

function LabelInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="text-xs font-medium block mb-0.5">{label}</label>
      <input
        className="border rounded px-2 py-1 w-full bg-background text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
