import { createSupabaseServerClient } from "@/lib/supabase-server";
import { redirect } from "next/navigation";

async function getStats(userId: string) {
  const supabase = await createSupabaseServerClient();

  const today = new Date().toISOString().split("T")[0];

  const [apps, todayApps, queueItems, recentApps] = await Promise.all([
    supabase.from("applications").select("id", { count: "exact" }).eq("user_id", userId),
    supabase.from("applications").select("id", { count: "exact" }).eq("user_id", userId).gte("applied_at", today),
    supabase.from("application_queue").select("id", { count: "exact" }).eq("user_id", userId).in("status", ["pending", "locked"]),
    supabase.from("applications").select("*").eq("user_id", userId).order("applied_at", { ascending: false }).limit(10),
  ]);

  return {
    totalApplied: apps.count || 0,
    appliedToday: todayApps.count || 0,
    queueDepth: queueItems.count || 0,
    recentApplications: recentApps.data || [],
  };
}

export default async function DashboardPage() {
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/auth/login");

  const stats = await getStats(user.id);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>

      {/* Setup Banner — shown when no applications yet */}
      {stats.totalApplied === 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 mb-6 flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-blue-900">Set up the automation engine</h3>
            <p className="text-sm text-blue-700 mt-1">
              Download and run the setup script to start auto-applying to jobs.
            </p>
          </div>
          <a
            href="/setup-complete"
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 whitespace-nowrap"
          >
            Download Setup Script
          </a>
        </div>
      )}

      {/* Learning Banner */}
      <div className="bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-200 rounded-xl p-4 mb-6">
        <div className="flex items-start gap-3">
          <span className="text-2xl">🧠</span>
          <div>
            <h3 className="font-semibold text-purple-900 text-sm">Your bot gets smarter with every interaction</h3>
            <p className="text-xs text-purple-700 mt-1">
              The more you use ApplyLoop, the better it understands your preferences. Correct it when it applies to the wrong role,
              tell it what you liked, skip companies you don&apos;t want — it learns and adapts. By day 3, it runs almost fully autonomously.
            </p>
          </div>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatCard label="Applied Today" value={stats.appliedToday} />
        <StatCard label="Total Applied" value={stats.totalApplied} />
        <StatCard label="In Queue" value={stats.queueDepth} />
        <StatCard label="Success Rate" value="--" />
      </div>

      {/* Recent Activity */}
      <div className="bg-white rounded-xl border p-6">
        <h2 className="font-semibold mb-4">Recent Applications</h2>
        {stats.recentApplications.length === 0 ? (
          <p className="text-gray-500 text-sm">No applications yet. Jobs will be discovered and applied to automatically.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-2">Company</th>
                <th className="pb-2">Role</th>
                <th className="pb-2">ATS</th>
                <th className="pb-2">Status</th>
                <th className="pb-2">Applied</th>
              </tr>
            </thead>
            <tbody>
              {stats.recentApplications.map((app: Record<string, string>) => (
                <tr key={app.id} className="border-b last:border-0">
                  <td className="py-2">{app.company}</td>
                  <td className="py-2">{app.title}</td>
                  <td className="py-2 capitalize">{app.ats}</td>
                  <td className="py-2">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${
                      app.status === "submitted" ? "bg-green-100 text-green-700" :
                      app.status === "failed" ? "bg-red-100 text-red-700" :
                      "bg-gray-100 text-gray-700"
                    }`}>
                      {app.status}
                    </span>
                  </td>
                  <td className="py-2 text-gray-500">{new Date(app.applied_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="bg-white rounded-xl border p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
    </div>
  );
}
