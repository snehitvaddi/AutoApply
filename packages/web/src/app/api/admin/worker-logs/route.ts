import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  // Check admin
  const { data: user } = await supabase
    .from("users")
    .select("is_admin")
    .eq("id", auth.userId)
    .single();

  if (!user?.is_admin) {
    return apiError("forbidden", "Admin access required");
  }

  const url = new URL(request.url);
  const level = url.searchParams.get("level"); // filter by level
  const resolved = url.searchParams.get("resolved"); // "true" or "false"
  const limit = parseInt(url.searchParams.get("limit") || "50");
  const userId = url.searchParams.get("user_id"); // filter by user

  let query = supabase
    .from("worker_logs")
    .select("*, users!worker_logs_user_id_fkey(email, full_name)")
    .order("created_at", { ascending: false })
    .limit(limit);

  if (level) query = query.eq("level", level);
  if (resolved === "false") query = query.eq("resolved", false);
  if (resolved === "true") query = query.eq("resolved", true);
  if (userId) query = query.eq("user_id", userId);

  const { data, error } = await query;

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  // Get summary counts
  const { count: unresolvedErrors } = await supabase
    .from("worker_logs")
    .select("id", { count: "exact", head: true })
    .eq("resolved", false)
    .in("level", ["error", "critical"]);

  const { count: totalToday } = await supabase
    .from("worker_logs")
    .select("id", { count: "exact", head: true })
    .gte("created_at", new Date().toISOString().split("T")[0] + "T00:00:00Z");

  return apiSuccess({
    logs: data || [],
    summary: {
      unresolved_errors: unresolvedErrors || 0,
      total_today: totalToday || 0,
    },
  });
}

// Resolve/unresolve a log entry
export async function PATCH(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { data: user } = await supabase
    .from("users")
    .select("is_admin")
    .eq("id", auth.userId)
    .single();

  if (!user?.is_admin) {
    return apiError("forbidden", "Admin access required");
  }

  const body = await request.json();
  const { log_id, resolved, resolution_note } = body;

  if (!log_id) {
    return apiError("bad_request", "log_id is required");
  }

  const updates: Record<string, unknown> = {
    resolved: resolved ?? true,
    resolved_by: auth.userId,
  };
  if (resolved) {
    updates.resolved_at = new Date().toISOString();
  } else {
    updates.resolved_at = null;
    updates.resolved_by = null;
  }
  if (resolution_note !== undefined) {
    updates.resolution_note = resolution_note;
  }

  const { data, error } = await supabase
    .from("worker_logs")
    .update(updates)
    .eq("id", log_id)
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ log: data });
}
