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

  const { data: users, error } = await supabase
    .from("users")
    .select("*, applications(count)")
    .order("created_at", { ascending: false });

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  const formatted = (users || []).map((u) => ({
    ...u,
    application_count: u.applications?.[0]?.count || 0,
    applications: undefined,
  }));

  return apiSuccess({ users: formatted });
}

// Admin can update per-user settings like ai_cli_mode, tier, daily_apply_limit
export async function PATCH(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const body = await request.json();
  const { user_id, ...updates } = body;

  if (!user_id) {
    return apiError("validation_error", "user_id is required");
  }

  // Only allow these fields to be updated by admin
  const allowedFields = ["ai_cli_mode", "tier", "daily_apply_limit"];
  const safeUpdates: Record<string, unknown> = {};
  for (const field of allowedFields) {
    if (updates[field] !== undefined) safeUpdates[field] = updates[field];
  }

  if (Object.keys(safeUpdates).length === 0) {
    return apiError("validation_error", "No valid fields to update");
  }

  const { data, error } = await supabase
    .from("users")
    .update({ ...safeUpdates, updated_at: new Date().toISOString() })
    .eq("id", user_id)
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ user: data });
}
