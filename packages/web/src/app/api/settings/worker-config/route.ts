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
    .from("worker_config")
    .select("*")
    .eq("user_id", auth.userId)
    .single();

  if (error || !data) {
    // Auto-create default config if not exists
    const { data: newConfig, error: insertError } = await supabase
      .from("worker_config")
      .insert({ user_id: auth.userId })
      .select()
      .single();

    if (insertError) {
      return apiError("internal_server_error", insertError.message);
    }
    return apiSuccess({ config: newConfig });
  }

  // Mask API keys for frontend display (show last 8 chars only)
  const masked = { ...data };
  if (masked.llm_api_key) {
    masked.llm_api_key_preview = "..." + masked.llm_api_key.slice(-8);
  }
  if (masked.llm_backend_api_key && masked.llm_backend_api_key !== masked.llm_api_key) {
    masked.llm_backend_api_key_preview = "..." + masked.llm_backend_api_key.slice(-8);
  }
  // Don't send raw keys to frontend
  delete masked.llm_api_key;
  delete masked.llm_backend_api_key;

  return apiSuccess({ config: masked });
}

export async function PUT(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const body = await request.json();

  const allowedFields = [
    "llm_provider", "llm_model", "llm_api_key",
    "llm_backend_provider", "llm_backend_model", "llm_backend_api_key",
    "ollama_base_url",
    "resume_tailoring", "cover_letters", "smart_answers",
    "monthly_limit",
    "worker_id", "poll_interval", "apply_cooldown",
    "auto_apply", "max_daily_apps",
  ];

  const updates: Record<string, unknown> = {};
  for (const field of allowedFields) {
    if (body[field] !== undefined) updates[field] = body[field];
  }

  // If API key is empty string or null, don't overwrite existing key
  if (updates.llm_api_key === "" || updates.llm_api_key === null) {
    delete updates.llm_api_key;
  }
  if (updates.llm_backend_api_key === "" || updates.llm_backend_api_key === null) {
    delete updates.llm_backend_api_key;
  }

  const { data, error } = await supabase
    .from("worker_config")
    .update(updates)
    .eq("user_id", auth.userId)
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  // Mask keys in response
  const masked = { ...data };
  if (masked.llm_api_key) {
    masked.llm_api_key_preview = "..." + masked.llm_api_key.slice(-8);
  }
  if (masked.llm_backend_api_key) {
    masked.llm_backend_api_key_preview = "..." + masked.llm_backend_api_key.slice(-8);
  }
  delete masked.llm_api_key;
  delete masked.llm_backend_api_key;

  return apiSuccess({ config: masked });
}
