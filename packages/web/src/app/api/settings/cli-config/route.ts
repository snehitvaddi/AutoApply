import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

// Returns CLI configuration for the setup script
// - ai_cli_mode: "provided_key" or "own_account"
// - api_key: only returned if mode is "provided_key"
export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { data: user, error } = await supabase
    .from("users")
    .select("ai_cli_mode, tier")
    .eq("id", auth.userId)
    .single();

  if (error || !user) {
    return apiError("not_found", "User not found");
  }

  const response: Record<string, string> = {
    ai_cli_mode: user.ai_cli_mode || "own_account",
    tier: user.tier,
  };

  // Only provide the shared API key if admin has set this user to "provided_key"
  if (user.ai_cli_mode === "provided_key") {
    const sharedKey = process.env.OPENAI_API_KEY_SHARED;
    if (sharedKey) {
      response.api_key = sharedKey;
    } else {
      // Fallback: no shared key configured, user must use own account
      response.ai_cli_mode = "own_account";
      response.note = "Shared API key not configured. Please use your own OpenAI account.";
    }
  }

  return apiSuccess(response);
}
