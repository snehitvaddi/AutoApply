import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

const STALE_MINUTES = 35;

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const { data, error } = await supabase
    .from("worker_heartbeats")
    .select("user_id, last_action, details, updated_at, users(email)")
    .order("updated_at", { ascending: false });

  if (error) {
    return apiError("internal", error.message);
  }

  const now = Date.now();
  const heartbeats = (data || []).map((row: Record<string, unknown>) => {
    const updatedAt = new Date(row.updated_at as string).getTime();
    const minutesAgo = (now - updatedAt) / 60_000;
    const users = row.users as { email: string } | null;
    return {
      user_id: row.user_id,
      email: users?.email || "unknown",
      last_action: row.last_action,
      details: row.details,
      updated_at: row.updated_at,
      stale: minutesAgo > STALE_MINUTES,
    };
  });

  return apiSuccess({ heartbeats });
}
