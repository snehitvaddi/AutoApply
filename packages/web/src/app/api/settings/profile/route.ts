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

  const { data, error } = await supabase
    .from("user_profiles")
    .select("*")
    .eq("user_id", auth.userId)
    .single();

  if (error || !data) {
    return apiError("not_found", "Profile not found");
  }

  const { data: user } = await supabase
    .from("users")
    .select("telegram_chat_id")
    .eq("id", auth.userId)
    .single();

  return apiSuccess({ profile: data, telegram_chat_id: user?.telegram_chat_id || null });
}

export async function PUT(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const body = await request.json();

  const allowedFields = [
    "first_name", "last_name", "phone", "linkedin_url", "github_url",
    "portfolio_url", "current_company", "current_title", "years_experience",
    "education_level", "school_name", "degree", "graduation_year",
    "work_authorization", "requires_sponsorship", "gender", "race_ethnicity",
    "veteran_status", "disability_status", "cover_letter_template", "answer_key_json",
    "work_experience", "skills", "education",
  ];
  const updates: Record<string, unknown> = {};
  for (const field of allowedFields) {
    if (body[field] !== undefined) updates[field] = body[field];
  }

  const { data, error } = await supabase
    .from("user_profiles")
    .update(updates)
    .eq("user_id", auth.userId)
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  // Mirror per-bundle fields into the user's default application profile.
  // Since migrations 019 + 020 moved answer_key / cover_letter /
  // work_experience / education / skills to user_application_profiles,
  // the worker reads them from the bundle at apply time. Without this
  // mirror, any legacy caller hitting /api/settings/profile (the old
  // Work & Edu tab backend, external CLI consumers) would silently
  // desync from the bundle and the worker would serve stale data.
  const MIRRORABLE = [
    "work_experience", "education", "skills",
    "answer_key_json", "cover_letter_template",
  ] as const;
  const mirror: Record<string, unknown> = {};
  for (const k of MIRRORABLE) {
    if (k in updates) mirror[k] = updates[k];
  }
  if (Object.keys(mirror).length > 0) {
    mirror.updated_at = new Date().toISOString();
    const { error: mirrorErr } = await supabase
      .from("user_application_profiles")
      .update(mirror)
      .eq("user_id", auth.userId)
      .eq("is_default", true);
    if (mirrorErr) {
      // Non-blocking — user_profiles update already succeeded and the
      // worker's user_profiles fallback still serves the data.
      console.warn("settings/profile → default bundle mirror failed:", mirrorErr.message);
    }
  }

  return apiSuccess({ profile: data });
}
