"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface UserInfo {
  id: string;
  email: string;
  full_name: string | null;
  tier: string;
  approval_status: string;
  onboarding_completed: boolean;
  daily_apply_limit: number;
  created_at: string;
  approved_at: string | null;
  application_count: number;
}

interface WorkerLog {
  id: string;
  user_id: string | null;
  worker_id: string;
  level: string;
  category: string;
  message: string;
  details: Record<string, unknown> | null;
  ats: string | null;
  company: string | null;
  resolved: boolean;
  resolution_note: string | null;
  created_at: string;
  users?: { email: string; full_name: string | null } | null;
}

interface Heartbeat {
  user_id: string;
  email: string;
  last_action: string;
  details: string;
  updated_at: string;
  stale: boolean;
}

interface InviteCode {
  id: string;
  code: string;
  max_uses: number;
  used_count: number;
  is_active: boolean;
  created_at: string;
}

export default function AdminPage() {
  const router = useRouter();
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [invites, setInvites] = useState<InviteCode[]>([]);
  const [heartbeats, setHeartbeats] = useState<Heartbeat[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [workerLogs, setWorkerLogs] = useState<WorkerLog[]>([]);
  const [logSummary, setLogSummary] = useState({ unresolved_errors: 0, total_today: 0 });
  const [newCodeMaxUses, setNewCodeMaxUses] = useState(1);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [generatedToken, setGeneratedToken] = useState<string | null>(null);
  const [tokenUserId, setTokenUserId] = useState<string | null>(null);
  const [usersWithTokens, setUsersWithTokens] = useState<Set<string>>(new Set());
  const [generatedCode, setGeneratedCode] = useState<{
    code: string;
    expires_at: string;
    uses_remaining: number;
    telegram_sent: boolean;
    email?: string;
  } | null>(null);
  const [showLegacyTools, setShowLegacyTools] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    const [usersRes, invRes, statsRes, logsRes, hbRes] = await Promise.all([
      fetch("/api/admin/users"),
      fetch("/api/admin/invites"),
      fetch("/api/admin/stats"),
      fetch("/api/admin/worker-logs?resolved=false&limit=50"),
      fetch("/api/admin/heartbeat"),
    ]);
    if (usersRes.status === 403 || invRes.status === 403 || statsRes.status === 403) {
      setUnauthorized(true);
      setLoading(false);
      return;
    }
    const [userData, invData, statsData, logsData, hbData] = await Promise.all([
      usersRes.json(), invRes.json(), statsRes.json(), logsRes.json(), hbRes.json(),
    ]);
    setUsers(userData.data?.users || []);
    setInvites(invData.data?.invites || []);
    setStats(statsData.data || {});
    setWorkerLogs(logsData.data?.logs || []);
    setLogSummary(logsData.data?.summary || { unresolved_errors: 0, total_today: 0 });
    setHeartbeats(hbData.data?.heartbeats || []);
    setLoading(false);
  }

  async function handleApproval(userId: string, action: "approve" | "reject") {
    setActionLoading(userId);
    const res = await fetch("/api/admin/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, action }),
    });
    if (res.ok) {
      const data = await res.json();
      setUsers((prev) =>
        prev.map((u) =>
          u.id === userId
            ? { ...u, approval_status: action === "approve" ? "approved" : "rejected" }
            : u
        )
      );
      // On approval: show auto-generated worker token
      if (action === "approve" && data.data?.worker_token) {
        setGeneratedToken(data.data.worker_token);
        setTokenUserId(userId);
        setUsersWithTokens((prev) => new Set([...prev, userId]));
      }
    }
    setActionLoading(null);
  }

  async function resolveLog(logId: string, note?: string) {
    setActionLoading(logId);
    const res = await fetch("/api/admin/worker-logs", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ log_id: logId, resolved: true, resolution_note: note || "Resolved by admin" }),
    });
    if (res.ok) {
      setWorkerLogs((prev) => prev.filter((l) => l.id !== logId));
      setLogSummary((prev) => ({ ...prev, unresolved_errors: Math.max(0, prev.unresolved_errors - 1) }));
    }
    setActionLoading(null);
  }

  async function generateWorkerToken(userId: string) {
    setActionLoading(`token-${userId}`);
    const res = await fetch("/api/admin/worker-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    const data = await res.json();
    if (data.data?.token) {
      setGeneratedToken(data.data.token);
      setTokenUserId(userId);
      setUsersWithTokens((prev) => new Set([...prev, userId]));
    }
    setActionLoading(null);
  }

  async function generateActivationCode(userId: string) {
    setActionLoading(`code-${userId}`);
    try {
      const res = await fetch("/api/admin/activation-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
      const payload = await res.json();
      if (payload.data?.code) {
        const user = users.find((u) => u.id === userId);
        setGeneratedCode({
          code: payload.data.code,
          expires_at: payload.data.expires_at,
          uses_remaining: payload.data.uses_remaining,
          telegram_sent: Boolean(payload.data.telegram_sent),
          email: user?.email,
        });
      } else {
        alert(`Failed to generate code: ${payload.message || "unknown error"}`);
      }
    } catch (err) {
      alert(`Failed to generate code: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function revokeWorkerToken(userId: string) {
    setActionLoading(`revoke-${userId}`);
    const res = await fetch("/api/admin/worker-token", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    if (res.ok) {
      setUsersWithTokens((prev) => {
        const next = new Set(prev);
        next.delete(userId);
        return next;
      });
    }
    setActionLoading(null);
  }

  async function createInviteCode() {
    const res = await fetch("/api/admin/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_uses: newCodeMaxUses }),
    });
    const data = await res.json();
    if (data.data?.invite) setInvites((prev) => [data.data.invite, ...prev]);
  }

  if (loading) return <div className="p-8">Loading admin...</div>;
  if (unauthorized) {
    router.push("/dashboard");
    return <div className="p-8">Access denied. Redirecting...</div>;
  }

  const pendingUsers = users.filter((u) => u.approval_status === "pending");
  const approvedUsers = users.filter((u) => u.approval_status === "approved");
  const rejectedUsers = users.filter((u) => u.approval_status === "rejected");

  return (
    <div className="max-w-5xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-6">Admin Dashboard</h1>

      {/* System Stats */}
      <div className="grid grid-cols-6 gap-4 mb-8">
        <div className="bg-white rounded-xl border p-4">
          <p className="text-sm text-gray-500">Total Users</p>
          <p className="text-2xl font-bold">{stats.total_users || users.length}</p>
        </div>
        <div className="bg-white rounded-xl border p-4">
          <p className="text-sm text-gray-500">Pending</p>
          <p className="text-2xl font-bold text-yellow-600">{pendingUsers.length}</p>
        </div>
        <div className="bg-white rounded-xl border p-4">
          <p className="text-sm text-gray-500">Apps Today</p>
          <p className="text-2xl font-bold">{stats.apps_today || 0}</p>
        </div>
        <div className="bg-white rounded-xl border p-4">
          <p className="text-sm text-gray-500">Total Apps</p>
          <p className="text-2xl font-bold">{stats.total_apps || 0}</p>
        </div>
        <div className="bg-white rounded-xl border p-4">
          <p className="text-sm text-gray-500">Queue Depth</p>
          <p className="text-2xl font-bold">{stats.queue_depth || 0}</p>
        </div>
        <div className={`rounded-xl border p-4 ${logSummary.unresolved_errors > 0 ? "bg-red-50 border-red-200" : "bg-white"}`}>
          <p className="text-sm text-gray-500">Worker Issues</p>
          <p className={`text-2xl font-bold ${logSummary.unresolved_errors > 0 ? "text-red-600" : ""}`}>
            {logSummary.unresolved_errors}
          </p>
        </div>
      </div>

      {/* Pending Approvals */}
      {pendingUsers.length > 0 && (
        <section className="bg-yellow-50 rounded-xl border border-yellow-200 p-6 mb-6">
          <h2 className="font-semibold mb-4 text-yellow-800">
            Pending Approvals ({pendingUsers.length})
          </h2>
          <div className="space-y-3">
            {pendingUsers.map((u) => (
              <div key={u.id} className="flex items-center justify-between bg-white rounded-lg border p-4">
                <div>
                  <p className="font-medium">{u.full_name || u.email}</p>
                  <p className="text-sm text-gray-500">{u.email}</p>
                  <p className="text-xs text-gray-400">
                    Requested {new Date(u.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleApproval(u.id, "approve")}
                    disabled={actionLoading === u.id}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => handleApproval(u.id, "reject")}
                    disabled={actionLoading === u.id}
                    className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Approved Users */}
      <section className="bg-white rounded-xl border p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Approved Users ({approvedUsers.length})</h2>
          <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer">
            <input
              type="checkbox"
              checked={showLegacyTools}
              onChange={(e) => setShowLegacyTools(e.target.checked)}
              className="rounded"
            />
            Show legacy tools
          </label>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="pb-2">Name</th>
              <th className="pb-2">Email</th>
              <th className="pb-2">Tier</th>
              <th className="pb-2">Onboarded</th>
              <th className="pb-2">Apps</th>
              <th className="pb-2">Joined</th>
              <th className="pb-2">Activation</th>
            </tr>
          </thead>
          <tbody>
            {approvedUsers.map((u) => (
              <tr key={u.id} className="border-b last:border-0">
                <td className="py-2">{u.full_name || "-"}</td>
                <td className="py-2">{u.email}</td>
                <td className="py-2 capitalize">{u.tier}</td>
                <td className="py-2">{u.onboarding_completed ? "Yes" : "No"}</td>
                <td className="py-2">{u.application_count}</td>
                <td className="py-2 text-gray-500">{new Date(u.created_at).toLocaleDateString()}</td>
                <td className="py-2">
                  <div className="flex gap-1 flex-wrap">
                    <button
                      onClick={() => generateActivationCode(u.id)}
                      disabled={actionLoading === `code-${u.id}`}
                      className="px-2 py-1 bg-brand-600 text-white rounded text-xs font-medium hover:bg-brand-700 disabled:opacity-50"
                      title="Create an activation code and DM it to the user via Telegram"
                    >
                      {actionLoading === `code-${u.id}` ? "..." : "Generate Activation Code"}
                    </button>
                    {showLegacyTools && (
                      <button
                        onClick={() => generateWorkerToken(u.id)}
                        disabled={actionLoading === `token-${u.id}`}
                        className="px-2 py-1 bg-gray-400 text-white rounded text-xs font-medium hover:bg-gray-500 disabled:opacity-50"
                        title="Legacy: generate raw worker token (paste into terminal setup script)"
                      >
                        {actionLoading === `token-${u.id}` ? "..." : "Legacy Token"}
                      </button>
                    )}
                    {usersWithTokens.has(u.id) && (
                      <button
                        onClick={() => revokeWorkerToken(u.id)}
                        disabled={actionLoading === `revoke-${u.id}`}
                        className="px-2 py-1 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700 disabled:opacity-50"
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Rejected Users */}
      {rejectedUsers.length > 0 && (
        <section className="bg-white rounded-xl border p-6 mb-6">
          <h2 className="font-semibold mb-4 text-gray-500">Rejected ({rejectedUsers.length})</h2>
          <div className="space-y-2">
            {rejectedUsers.map((u) => (
              <div key={u.id} className="flex items-center justify-between text-sm text-gray-500">
                <span>{u.email}</span>
                <button
                  onClick={() => handleApproval(u.id, "approve")}
                  className="text-brand-600 hover:underline text-xs"
                >
                  Re-approve
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Worker Heartbeats */}
      {heartbeats.length > 0 && (
        <section className="bg-white rounded-xl border p-6 mb-6">
          <h2 className="font-semibold mb-4">Worker Heartbeats ({heartbeats.length})</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-2">Status</th>
                <th className="pb-2">User</th>
                <th className="pb-2">Last Action</th>
                <th className="pb-2">Details</th>
                <th className="pb-2">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {heartbeats.map((hb) => {
                const minutesAgo = (Date.now() - new Date(hb.updated_at).getTime()) / 60_000;
                const dotColor =
                  minutesAgo <= 35
                    ? "bg-green-500"
                    : minutesAgo <= 60
                    ? "bg-yellow-400"
                    : "bg-red-500";
                const label =
                  minutesAgo <= 35 ? "Fresh" : minutesAgo <= 60 ? "Stale" : "Dead";
                const timeLabel =
                  minutesAgo < 1
                    ? "just now"
                    : minutesAgo < 60
                    ? `${Math.round(minutesAgo)}m ago`
                    : `${Math.round(minutesAgo / 60)}h ago`;
                return (
                  <tr key={hb.user_id} className="border-b last:border-0">
                    <td className="py-2">
                      <span className="flex items-center gap-2">
                        <span className={`inline-block w-2.5 h-2.5 rounded-full ${dotColor}`} />
                        <span className="text-xs text-gray-500">{label}</span>
                      </span>
                    </td>
                    <td className="py-2">{hb.email}</td>
                    <td className="py-2 capitalize">{hb.last_action}</td>
                    <td className="py-2 text-gray-500 truncate max-w-[200px]">{hb.details}</td>
                    <td className="py-2 text-gray-500">{timeLabel}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {/* Worker Logs */}
      {workerLogs.length > 0 && (
        <section className="bg-red-50 rounded-xl border border-red-200 p-6 mb-6">
          <h2 className="font-semibold mb-4 text-red-800">
            Worker Issues ({workerLogs.length} unresolved)
          </h2>
          <div className="space-y-3">
            {workerLogs.map((log) => (
              <div key={log.id} className="bg-white rounded-lg border p-4">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        log.level === "critical" ? "bg-red-100 text-red-800" :
                        log.level === "error" ? "bg-red-50 text-red-700" :
                        log.level === "warn" ? "bg-yellow-50 text-yellow-700" :
                        "bg-gray-50 text-gray-600"
                      }`}>
                        {log.level.toUpperCase()}
                      </span>
                      <span className="text-xs text-gray-400">{log.category}</span>
                      {log.ats && <span className="text-xs text-gray-400">| {log.ats}</span>}
                      {log.company && <span className="text-xs text-gray-400">| {log.company}</span>}
                    </div>
                    <p className="text-sm font-medium">{log.message}</p>
                    <div className="flex gap-4 mt-1">
                      <p className="text-xs text-gray-500">
                        Worker: {log.worker_id}
                      </p>
                      {log.users && (
                        <p className="text-xs text-gray-500">
                          User: {log.users.full_name || log.users.email}
                        </p>
                      )}
                      <p className="text-xs text-gray-400">
                        {new Date(log.created_at).toLocaleString()}
                      </p>
                    </div>
                    {log.details && (
                      <details className="mt-2">
                        <summary className="text-xs text-gray-400 cursor-pointer">Details</summary>
                        <pre className="mt-1 text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                          {JSON.stringify(log.details, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                  <button
                    onClick={() => resolveLog(log.id)}
                    disabled={actionLoading === log.id}
                    className="ml-4 px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs font-medium hover:bg-green-700 disabled:opacity-50 whitespace-nowrap"
                  >
                    Resolve
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Activation Code Generated Modal */}
      {generatedCode && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 max-w-lg w-full mx-4">
            <h3 className="font-semibold text-lg mb-1">🔑 Activation Code Generated</h3>
            {generatedCode.email && (
              <p className="text-xs text-gray-500 mb-3">for {generatedCode.email}</p>
            )}
            <p className="text-sm text-gray-600 mb-4">
              The user enters this code in the ApplyLoop desktop app&apos;s setup screen. No terminal, no raw token.
            </p>
            <div className="bg-gray-50 rounded-lg p-4 font-mono text-xl text-center tracking-widest mb-3 select-all">
              {generatedCode.code}
            </div>
            <div className="text-xs text-gray-500 mb-4 space-y-1">
              <p>
                <strong>Expires:</strong>{" "}
                {new Date(generatedCode.expires_at).toLocaleString()}
              </p>
              <p>
                <strong>Uses remaining:</strong> {generatedCode.uses_remaining}
              </p>
              <p>
                <strong>Telegram DM:</strong>{" "}
                {generatedCode.telegram_sent ? (
                  <span className="text-green-600">✓ sent to user automatically</span>
                ) : (
                  <span className="text-amber-600">
                    ⚠ not sent (user has no telegram_chat_id) — copy manually
                  </span>
                )}
              </p>
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => {
                  navigator.clipboard.writeText(generatedCode.code);
                }}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                Copy Code
              </button>
              <button
                onClick={() => setGeneratedCode(null)}
                className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-300"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Token Generated Modal */}
      {generatedToken && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 max-w-lg w-full mx-4">
            <h3 className="font-semibold text-lg mb-2">Worker Token Generated</h3>
            <p className="text-sm text-red-600 mb-4">
              This token will only be shown once. Copy it now.
            </p>
            <div className="bg-gray-50 rounded-lg p-3 font-mono text-sm break-all mb-4">
              {generatedToken}
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => {
                  navigator.clipboard.writeText(generatedToken);
                }}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                Copy
              </button>
              <button
                onClick={() => {
                  setGeneratedToken(null);
                  setTokenUserId(null);
                }}
                className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-300"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Invite Codes (keep for backward compatibility) */}
      <section className="bg-white rounded-xl border p-6">
        <h2 className="font-semibold mb-4">Invite Codes (Legacy)</h2>
        <div className="flex gap-4 mb-4">
          <input
            type="number"
            min={1}
            max={50}
            value={newCodeMaxUses}
            onChange={(e) => setNewCodeMaxUses(parseInt(e.target.value) || 1)}
            className="w-24 px-3 py-2 border rounded-lg"
            placeholder="Max uses"
          />
          <button onClick={createInviteCode} className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700">
            Generate Code
          </button>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="pb-2">Code</th>
              <th className="pb-2">Uses</th>
              <th className="pb-2">Active</th>
              <th className="pb-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {invites.map((inv) => (
              <tr key={inv.id} className="border-b last:border-0">
                <td className="py-2 font-mono text-sm">{inv.code}</td>
                <td className="py-2">{inv.used_count}/{inv.max_uses}</td>
                <td className="py-2">{inv.is_active ? "Yes" : "No"}</td>
                <td className="py-2 text-gray-500">{new Date(inv.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
