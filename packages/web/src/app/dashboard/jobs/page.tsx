"use client";

import { useEffect, useState } from "react";

interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  ats: string;
  posted_at: string;
  match_status: string;
  match_id: string;
}

interface MatchRow {
  id: string;
  status: string;
  discovered_jobs: {
    title: string;
    company: string;
    location: string | null;
    ats: string;
    posted_at: string | null;
  };
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/jobs")
      .then((r) => r.json())
      .then((data) => {
        const matches: MatchRow[] = data.data?.jobs || [];
        setJobs(matches.map((m) => ({
          id: m.discovered_jobs?.company || m.id,
          title: m.discovered_jobs?.title || "",
          company: m.discovered_jobs?.company || "",
          location: m.discovered_jobs?.location || "",
          ats: m.discovered_jobs?.ats || "",
          posted_at: m.discovered_jobs?.posted_at || "",
          match_status: m.status,
          match_id: m.id,
        })));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  async function handleAction(matchId: string, action: "approved" | "skipped") {
    await fetch(`/api/jobs/${matchId}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    setJobs((prev) => prev.map((j) => j.match_id === matchId ? { ...j, match_status: action } : j));
  }

  async function handleBulkApply() {
    const pendingIds = jobs.filter((j) => j.match_status === "pending").map((j) => j.match_id);
    if (pendingIds.length === 0) return;
    await fetch("/api/jobs/bulk-apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_ids: pendingIds }),
    });
    setJobs((prev) => prev.map((j) => pendingIds.includes(j.match_id) ? { ...j, match_status: "queued" } : j));
  }

  if (loading) return <div className="p-8">Loading jobs...</div>;

  const pendingCount = jobs.filter((j) => j.match_status === "pending").length;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Discovered Jobs</h1>
        {pendingCount > 0 && (
          <button onClick={handleBulkApply} className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700">
            Apply All ({pendingCount})
          </button>
        )}
      </div>

      {jobs.length === 0 ? (
        <div className="bg-white rounded-xl border p-8 text-center text-gray-500">
          <p>No matching jobs found yet. The scanner runs every 6 hours.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b bg-gray-50">
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">ATS</th>
                <th className="px-4 py-3">Posted</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} className="border-b last:border-0 hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{job.company}</td>
                  <td className="px-4 py-3">{job.title}</td>
                  <td className="px-4 py-3 text-gray-500">{job.location || "Remote"}</td>
                  <td className="px-4 py-3 capitalize">{job.ats}</td>
                  <td className="px-4 py-3 text-gray-500">
                    {job.posted_at ? new Date(job.posted_at).toLocaleDateString() : "Unknown"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${
                      job.match_status === "pending" ? "bg-yellow-100 text-yellow-700" :
                      job.match_status === "approved" || job.match_status === "queued" ? "bg-green-100 text-green-700" :
                      job.match_status === "applied" ? "bg-blue-100 text-blue-700" :
                      "bg-gray-100 text-gray-700"
                    }`}>
                      {job.match_status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {job.match_status === "pending" && (
                      <div className="flex gap-2">
                        <button onClick={() => handleAction(job.match_id, "approved")} className="text-green-600 hover:text-green-800 text-xs font-medium">
                          Approve
                        </button>
                        <button onClick={() => handleAction(job.match_id, "skipped")} className="text-gray-400 hover:text-gray-600 text-xs font-medium">
                          Skip
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
