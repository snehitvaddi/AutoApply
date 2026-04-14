"use client";

import { useEffect, useState } from "react";

// Controlled Work & Education editor for the web ProfilesTab. Mirrors
// packages/desktop/ui/app/settings/WorkEducationEditor.tsx's controlled-
// mode API exactly so the UX is identical between web and desktop.
// Always controlled: the caller owns state and saves via its own flow.

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
  onChange,
}: {
  initial: {
    work_experience?: WorkExperienceRow[];
    education?: EducationRow[];
    skills?: string[];
  };
  onChange: (next: {
    work_experience: WorkExperienceRow[];
    education: EducationRow[];
    skills: string[];
  }) => void;
}) {
  const [workRows, setWorkRows] = useState<WorkExperienceRow[]>([]);
  const [eduRows, setEduRows] = useState<EducationRow[]>([]);
  const [skills, setSkills] = useState<string[]>([]);
  const [skillBuf, setSkillBuf] = useState("");

  useEffect(() => {
    setWorkRows(initial.work_experience || []);
    setEduRows(initial.education || []);
    setSkills(initial.skills || []);
  }, [initial.work_experience, initial.education, initial.skills]);

  useEffect(() => {
    onChange({ work_experience: workRows, education: eduRows, skills });
  }, [onChange, workRows, eduRows, skills]);

  const updateWork = (i: number, patch: Partial<WorkExperienceRow>) =>
    setWorkRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addWork = () =>
    setWorkRows((prev) => [
      ...prev,
      { company: "", title: "", location: "", start_date: "", end_date: "Present", current: true, achievements: [] },
    ]);
  const removeWork = (i: number) => setWorkRows((prev) => prev.filter((_, idx) => idx !== i));

  const updateEdu = (i: number, patch: Partial<EducationRow>) =>
    setEduRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addEdu = () =>
    setEduRows((prev) => [
      ...prev,
      { school: "", degree: "", field: "", start_date: "", end_date: "", gpa: "" },
    ]);
  const removeEdu = (i: number) => setEduRows((prev) => prev.filter((_, idx) => idx !== i));

  const addSkill = () => {
    const parts = skillBuf.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) setSkills((prev) => [...prev, ...parts.filter((p) => !prev.includes(p))]);
    setSkillBuf("");
  };

  return (
    <div className="space-y-5">
      {/* Work Experience */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold">Work Experience</h4>
          <button type="button" onClick={addWork} className="text-xs px-2 py-1 rounded border hover:bg-gray-50">
            + Add role
          </button>
        </div>
        {workRows.length === 0 && (
          <p className="text-xs text-gray-500">No work experience yet. Click Add role.</p>
        )}
        <div className="space-y-3">
          {workRows.map((row, i) => (
            <div key={i} className="border rounded p-3 space-y-2 bg-gray-50">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Company" value={row.company} onChange={(v) => updateWork(i, { company: v })} />
                <Field label="Title" value={row.title} onChange={(v) => updateWork(i, { title: v })} />
                <Field label="Location" value={row.location || ""} onChange={(v) => updateWork(i, { location: v })} />
                <Field label="Start" value={row.start_date || ""} onChange={(v) => updateWork(i, { start_date: v })} />
                <Field label="End / Present" value={row.end_date || ""} onChange={(v) => updateWork(i, { end_date: v })} />
                <label className="flex items-center gap-2 text-xs self-end">
                  <input type="checkbox" checked={!!row.current} onChange={(e) => updateWork(i, { current: e.target.checked })} /> Current
                </label>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-medium">Achievements</label>
                  <button
                    type="button"
                    onClick={() => updateWork(i, { achievements: [...(row.achievements || []), ""] })}
                    className="text-xs px-2 py-0.5 rounded border hover:bg-white"
                  >
                    + Bullet
                  </button>
                </div>
                {(row.achievements || []).map((a, bi) => (
                  <div key={bi} className="flex gap-1 mb-1">
                    <input
                      className="flex-1 border rounded px-2 py-1 text-xs"
                      value={a}
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
                      className="text-red-600 text-xs px-1"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>

              <button type="button" onClick={() => removeWork(i)} className="text-xs text-red-600 hover:underline">
                Remove role
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Education */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold">Education</h4>
          <button type="button" onClick={addEdu} className="text-xs px-2 py-1 rounded border hover:bg-gray-50">
            + Add school
          </button>
        </div>
        {eduRows.length === 0 && (
          <p className="text-xs text-gray-500">No education yet.</p>
        )}
        <div className="space-y-3">
          {eduRows.map((row, i) => (
            <div key={i} className="border rounded p-3 space-y-2 bg-gray-50">
              <div className="grid grid-cols-2 gap-2">
                <Field label="School" value={row.school} onChange={(v) => updateEdu(i, { school: v })} />
                <Field label="Degree" value={row.degree} onChange={(v) => updateEdu(i, { degree: v })} />
                <Field label="Field" value={row.field || ""} onChange={(v) => updateEdu(i, { field: v })} />
                <Field label="GPA" value={row.gpa || ""} onChange={(v) => updateEdu(i, { gpa: v })} />
                <Field label="Start" value={row.start_date || ""} onChange={(v) => updateEdu(i, { start_date: v })} />
                <Field label="End" value={row.end_date || ""} onChange={(v) => updateEdu(i, { end_date: v })} />
              </div>
              <button type="button" onClick={() => removeEdu(i)} className="text-xs text-red-600 hover:underline">
                Remove school
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Skills */}
      <section>
        <h4 className="text-sm font-semibold mb-2">Skills</h4>
        <div className="flex flex-wrap gap-1 mb-2">
          {skills.map((s, i) => (
            <span key={i} className="text-xs bg-gray-100 rounded px-2 py-0.5 flex items-center gap-1">
              {s}
              <button type="button" onClick={() => setSkills((prev) => prev.filter((_, idx) => idx !== i))} className="hover:text-red-600">
                ×
              </button>
            </span>
          ))}
        </div>
        <input
          className="border rounded px-2 py-1 w-full text-sm"
          value={skillBuf}
          onChange={(e) => setSkillBuf(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addSkill(); } }}
          onBlur={addSkill}
          placeholder="python, pytorch, sql — press Enter"
        />
      </section>
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="text-xs font-medium block mb-0.5 text-gray-700">{label}</label>
      <input
        className="border rounded px-2 py-1 w-full text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
