import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

// GET /api/admin/client-stats?user_id=xxx
// Returns detailed application stats for a specific user
export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const { searchParams } = new URL(request.url);
  const userId = searchParams.get("user_id");

  if (!userId) {
    // Return summary for all users
    const { data: users } = await supabase
      .from("users")
      .select("id, email, full_name, tier, onboarding_completed, created_at");

    const allStats = [];
    for (const user of users || []) {
      const { count: totalApps } = await supabase
        .from("applications")
        .select("id", { count: "exact" })
        .eq("user_id", user.id);

      const { count: submitted } = await supabase
        .from("applications")
        .select("id", { count: "exact" })
        .eq("user_id", user.id)
        .eq("status", "submitted");

      const { count: failed } = await supabase
        .from("applications")
        .select("id", { count: "exact" })
        .eq("user_id", user.id)
        .eq("status", "failed");

      const today = new Date().toISOString().split("T")[0];
      const { count: todayApps } = await supabase
        .from("applications")
        .select("id", { count: "exact" })
        .eq("user_id", user.id)
        .gte("applied_at", `${today}T00:00:00Z`);

      allStats.push({
        user_id: user.id,
        email: user.email,
        full_name: user.full_name,
        tier: user.tier,
        onboarded: user.onboarding_completed,
        total_applications: totalApps || 0,
        submitted: submitted || 0,
        failed: failed || 0,
        today: todayApps || 0,
      });
    }

    return apiSuccess({ clients: allStats });
  }

  // Detailed stats for one user
  const { data: apps } = await supabase
    .from("applications")
    .select("company, title, ats, status, apply_url, screenshot_url, error, applied_at")
    .eq("user_id", userId)
    .order("applied_at", { ascending: false })
    .limit(100);

  const { data: profile } = await supabase
    .from("user_profiles")
    .select("first_name, last_name, current_company, current_title")
    .eq("user_id", userId)
    .single();

  const { data: prefs } = await supabase
    .from("user_job_preferences")
    .select("target_titles, auto_apply")
    .eq("user_id", userId)
    .single();

  const { data: heartbeat } = await supabase
    .from("worker_heartbeats")
    .select("last_action, details, updated_at")
    .eq("user_id", userId)
    .single();

  // Company breakdown
  const companyBreakdown: Record<string, number> = {};
  for (const app of apps || []) {
    companyBreakdown[app.company] = (companyBreakdown[app.company] || 0) + 1;
  }

  return apiSuccess({
    profile: profile || {},
    preferences: prefs || {},
    heartbeat: heartbeat || null,
    applications: apps || [],
    total: (apps || []).length,
    submitted: (apps || []).filter((a: Record<string, string>) => a.status === "submitted").length,
    failed: (apps || []).filter((a: Record<string, string>) => a.status === "failed").length,
    company_breakdown: companyBreakdown,
  });
}
