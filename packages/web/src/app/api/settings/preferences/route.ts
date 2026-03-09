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

  const { data: prefs, error: prefsError } = await supabase
    .from("user_job_preferences")
    .select("*")
    .eq("user_id", auth.userId)
    .single();

  if (prefsError) {
    return apiError("not_found", "Preferences not found");
  }

  const { data: user } = await supabase
    .from("users")
    .select("tier, daily_apply_limit")
    .eq("id", auth.userId)
    .single();

  return apiSuccess({
    preferences: prefs,
    tier: user?.tier || "free",
    daily_apply_limit: user?.daily_apply_limit || 5,
  });
}

export async function PUT(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const body = await request.json();

  const { data, error } = await supabase
    .from("user_job_preferences")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("user_id", auth.userId)
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ preferences: data });
}
