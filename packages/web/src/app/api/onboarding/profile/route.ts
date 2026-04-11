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

  const profileFields: Record<string, unknown> = { user_id: auth.userId };
  const allowedFields = [
    "first_name", "last_name", "phone", "linkedin_url", "github_url",
    "portfolio_url", "current_company", "current_title", "years_experience",
    "education_level", "school_name", "degree", "graduation_year",
    "work_authorization", "requires_sponsorship", "gender", "race_ethnicity",
    "veteran_status", "disability_status", "cover_letter_template", "answer_key_json",
    "work_experience", "skills", "education",
  ];
  for (const field of allowedFields) {
    if (body[field] !== undefined) profileFields[field] = body[field];
  }

  const { data, error } = await supabase
    .from("user_profiles")
    .upsert(profileFields, { onConflict: "user_id" })
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ profile: data });
}
