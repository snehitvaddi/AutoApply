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
          "first_name, last_name, phone, linkedin_url, github_url, portfolio_url, current_company, current_title, years_experience, education_level, school_name, degree, graduation_year, work_authorization, requires_sponsorship, gender, race_ethnicity, veteran_status, disability_status, work_experience, education, skills, answer_key_json, cover_letter_template"
        )
        .eq("user_id", auth.userId)
        .single(),
      supabase
        .from("user_job_preferences")
        .select(
          "target_titles, target_keywords, excluded_titles, excluded_companies, preferred_locations, min_salary, remote_only, auto_apply, max_daily"
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

  // Build profile with fallback arrays from flat fields
  const profile = profileResult.data || {};
  const p = profile as Record<string, unknown>;

  // If work_experience[] is empty but flat fields exist, build array from flat fields
  if ((!p.work_experience || (Array.isArray(p.work_experience) && p.work_experience.length === 0)) && p.current_company) {
    p.work_experience = [{
      company: p.current_company || "",
      title: p.current_title || "",
      location: "",
      start_date: "",
      end_date: "Present",
      current: true,
      achievements: [],
    }];
  }

  // If education[] is empty but flat fields exist, build array from flat fields
  if ((!p.education || (Array.isArray(p.education) && p.education.length === 0)) && p.school_name) {
    p.education = [{
      school: p.school_name || "",
      degree: p.degree || "",
      field: "",
      start_date: "",
      end_date: p.graduation_year ? String(p.graduation_year) : "",
      gpa: "",
    }];
  }

  // Fetch multi-profile bundles so desktop can render the Profiles list +
  // Claude can enumerate them in the initial prompt. No encrypted blobs
  // in this endpoint — passwords flow only through /api/worker/proxy
  // (service-role, worker-token gated).
  //
  // Resolve application_email server-side: pool binding (email_account_id)
  // wins over inline application_email. Without this join, a bundle bound
  // via the email-accounts pool surfaces application_email=null and the
  // desktop prompt renders "—". We fetch pool accounts once and map.
  const [bundlesRes, emailAccountsRes] = await Promise.all([
    supabase
      .from("user_application_profiles")
      .select("id, name, slug, is_default, target_titles, target_keywords, excluded_titles, excluded_companies, excluded_role_keywords, excluded_levels, preferred_locations, remote_only, min_salary, ashby_boards, greenhouse_boards, resume_id, email_account_id, application_email, auto_apply, max_daily, answer_key_json, cover_letter_template, work_experience, education, skills, updated_at")
      .eq("user_id", auth.userId)
      .order("is_default", { ascending: false }),
    supabase
      .from("user_email_accounts")
      .select("id, email")
      .eq("user_id", auth.userId),
  ]);
  const rawBundles = (bundlesRes.data || []) as Record<string, unknown>[];
  const emailAccountMap = new Map(
    ((emailAccountsRes.data || []) as Array<{ id: string; email: string }>).map((e) => [e.id, e.email]),
  );
  const bundles = rawBundles.map((b) => {
    const poolEmail = b.email_account_id ? emailAccountMap.get(b.email_account_id as string) : undefined;
    const resolved = poolEmail || (b.application_email as string | null | undefined) || null;
    return { ...b, application_email: resolved };
  });

  const response: Record<string, unknown> = {
    ai_cli_mode: user.ai_cli_mode || "own_account",
    tier: user.tier,
    user: {
      id: user.id,
      email: user.email,
      full_name: user.full_name,
    },
    profile: p,
    preferences: preferencesResult.data || {},
    resumes: resumesResult.data || [],
    application_profiles: bundles || [],
    supabase_url: process.env.NEXT_PUBLIC_SUPABASE_URL,
    supabase_anon_key: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    telegram_chat_id: user.telegram_chat_id || null,
    telegram_bot_token: process.env.TELEGRAM_BOT_TOKEN || null,
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
