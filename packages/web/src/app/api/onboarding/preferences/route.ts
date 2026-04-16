import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const body = await request.json();
  const {
    target_titles,
    target_keywords,
    excluded_titles,
    excluded_companies,
    preferred_locations,
    min_salary,
    remote_only,
    auto_apply,
    max_daily,
  } = body;

  const { data, error } = await supabase
    .from("user_job_preferences")
    .upsert(
      {
        user_id: auth.userId,
        target_titles: target_titles || [],
        target_keywords: target_keywords || [],
        excluded_titles: excluded_titles || [],
        excluded_companies: excluded_companies || [],
        preferred_locations: preferred_locations || [],
        min_salary: min_salary || null,
        remote_only: remote_only ?? false,
        auto_apply: auto_apply ?? false,
        // null = no cap. Onboarding UI doesn't expose this field, so a
        // missing value means "user never chose a cap" — not "default
        // me to 50." A non-null hardcoded fallback ended up seeding
        // every bundle via migration 014's backfill and quietly throttled
        // users who never set one.
        max_daily: max_daily ?? null,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id" }
    )
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ preferences: data });
}
