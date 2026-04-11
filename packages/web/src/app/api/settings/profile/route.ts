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

  return apiSuccess({ profile: data });
}
