import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { encryptString } from "@/lib/crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  const { data, error } = await supabase
    .from("user_email_accounts")
    .select("id, email, label, created_at, app_password_enc")
    .eq("user_id", auth.userId)
    .order("created_at", { ascending: true });
  if (error) return apiError("internal_server_error", error.message);
  const sanitized = (data || []).map((r) => {
    const { app_password_enc, ...rest } = r as Record<string, unknown>;
    return { ...rest, has_app_password: !!app_password_enc };
  });
  return apiSuccess({ email_accounts: sanitized });
}

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  const body = await request.json();
  const email = (body.email as string | undefined)?.trim();
  if (!email) return apiError("validation_error", "email is required");
  const payload: Record<string, unknown> = {
    user_id: auth.userId,
    email,
    label: body.label || null,
  };
  if (typeof body.app_password === "string" && body.app_password.length) {
    payload.app_password_enc = encryptString(body.app_password);
  }
  const { data, error } = await supabase
    .from("user_email_accounts")
    .upsert(payload, { onConflict: "user_id,email" })
    .select("id, email, label, created_at")
    .single();
  if (error) return apiError("internal_server_error", error.message);
  return apiSuccess({ email_account: data });
}
