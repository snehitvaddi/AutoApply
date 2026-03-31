import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

// Returns CLI configuration for the setup script
// - Full user profile bundle for worker context
// - ai_cli_mode: "provided_key" or "own_account"
// - api_key: only returned if mode is "provided_key"
export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  // Fetch user, profile, preferences, and resumes in parallel
  const [userResult, profileResult, preferencesResult, resumesResult] =
    await Promise.all([
      supabase
        .from("users")
        .select("id, email, full_name, ai_cli_mode, tier, telegram_chat_id")
        .eq("id", auth.userId)
        .single(),
      supabase
        .from("user_profiles")
        .select(
          "full_name, phone, linkedin_url, github_url, portfolio_url, location, summary, work_experience, education"
        )
        .eq("user_id", auth.userId)
        .single(),
      supabase
        .from("user_job_preferences")
        .select(
          "target_roles, target_locations, min_salary, visa_sponsorship, remote_preference, excluded_companies"
        )
        .eq("user_id", auth.userId)
        .single(),
      supabase
        .from("user_resumes")
        .select("id, file_name, is_default, target_keywords, created_at")
        .eq("user_id", auth.userId)
        .order("is_default", { ascending: false }),
    ]);

  if (userResult.error || !userResult.data) {
    return apiError("not_found", "User not found");
  }

  const user = userResult.data;

  const response: Record<string, unknown> = {
    ai_cli_mode: user.ai_cli_mode || "own_account",
    tier: user.tier,
    user: {
      id: user.id,
      email: user.email,
      full_name: user.full_name,
    },
    profile: profileResult.data || {},
    preferences: preferencesResult.data || {},
    resumes: resumesResult.data || [],
    supabase_url: process.env.NEXT_PUBLIC_SUPABASE_URL,
    supabase_anon_key: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    telegram_chat_id: user.telegram_chat_id || null,
  };

  // Only provide the shared API key if admin has set this user to "provided_key"
  if (user.ai_cli_mode === "provided_key") {
    const sharedKey = process.env.OPENAI_API_KEY_SHARED;
    if (sharedKey) {
      response.api_key = sharedKey;
    } else {
      // Fallback: no shared key configured, user must use own account
      response.ai_cli_mode = "own_account";
      response.note =
        "Shared API key not configured. Please use your own OpenAI account.";
    }
  }

  return apiSuccess(response);
}
