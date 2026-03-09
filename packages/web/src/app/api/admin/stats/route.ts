import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);

  const [usersRes, appsRes, appsTodayRes, queueRes, workersRes] =
    await Promise.all([
      supabase.from("users").select("*", { count: "exact", head: true }),
      supabase.from("applications").select("*", { count: "exact", head: true }),
      supabase
        .from("applications")
        .select("*", { count: "exact", head: true })
        .gte("applied_at", todayStart.toISOString()),
      supabase
        .from("application_queue")
        .select("*", { count: "exact", head: true })
        .eq("status", "pending"),
      supabase
        .from("application_queue")
        .select("*", { count: "exact", head: true })
        .eq("status", "processing"),
    ]);

  return apiSuccess({
    total_users: usersRes.count || 0,
    total_apps: appsRes.count || 0,
    apps_today: appsTodayRes.count || 0,
    queue_depth: queueRes.count || 0,
    active_workers: workersRes.count || 0,
  });
}
