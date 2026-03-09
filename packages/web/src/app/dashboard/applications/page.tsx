"use client";

import React, { useEffect, useState } from "react";

interface Application {
  id: string;
  company: string;
  title: string;
  ats: string;
  status: string;
  screenshot_url: string | null;
  error: string | null;
  applied_at: string;
}

export default function ApplicationsPage() {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/applications")
      .then((r) => r.json())
      .then((data) => { setApps(data.data || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8">Loading applications...</div>;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Application History</h1>
      <p className="text-sm text-gray-500 mb-4">{apps.length} total applications</p>

      {apps.length === 0 ? (
        <div className="bg-white rounded-xl border p-8 text-center text-gray-500">
          No applications yet.
        </div>
      ) : (
        <div className="bg-white rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b bg-gray-50">
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">ATS</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Applied</th>
                <th className="px-4 py-3">Screenshot</th>
              </tr>
            </thead>
            <tbody>
              {apps.map((app) => (
                <React.Fragment key={app.id}>
                  <tr className="border-b hover:bg-gray-50 cursor-pointer" tabIndex={0} role="button" onClick={() => setExpandedId(expandedId === app.id ? null : app.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setExpandedId(expandedId === app.id ? null : app.id); }}>
                    <td className="px-4 py-3 font-medium">{app.company}</td>
                    <td className="px-4 py-3">{app.title}</td>
                    <td className="px-4 py-3 capitalize">{app.ats}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs ${
                        app.status === "submitted" ? "bg-green-100 text-green-700" :
                        app.status === "failed" ? "bg-red-100 text-red-700" :
                        "bg-blue-100 text-blue-700"
                      }`}>
                        {app.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">{new Date(app.applied_at).toLocaleString()}</td>
                    <td className="px-4 py-3">
                      {app.screenshot_url ? (
                        <a href={app.screenshot_url} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline text-xs" onClick={(e) => e.stopPropagation()}>
                          View
                        </a>
                      ) : "--"}
                    </td>
                  </tr>
                  {expandedId === app.id && (
                    <tr key={`${app.id}-detail`}>
                      <td colSpan={6} className="px-4 py-4 bg-gray-50">
                        {app.error && <p className="text-sm text-red-600 mb-2">Error: {app.error}</p>}
                        {app.screenshot_url && (
                          <img src={app.screenshot_url} alt="Application screenshot" className="max-w-lg rounded-lg border" />
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
