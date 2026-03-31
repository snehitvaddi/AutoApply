import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";
import crypto from "crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

function hashToken(token: string): string {
  return crypto.createHash("sha256").update(token).digest("hex");
}

function generateToken(): string {
  const prefix = "al";
  const mid = crypto.randomUUID().replace(/-/g, "").slice(0, 8);
  const secret = crypto.randomBytes(16).toString("hex"); // 32 hex chars
  return `${prefix}_${mid}_${secret}`;
}

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const { user_id } = await request.json();
  if (!user_id) {
    return apiError("validation_error", "user_id is required");
  }

  // Revoke any existing token for this user
  await supabase
    .from("worker_tokens")
    .update({ revoked_at: new Date().toISOString() })
    .eq("user_id", user_id)
    .is("revoked_at", null);

  const token = generateToken();
  const token_hash = hashToken(token);

  const { error } = await supabase.from("worker_tokens").insert({
    user_id,
    token_hash,
  });

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ token, user_id });
}

export async function DELETE(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const { user_id } = await request.json();
  if (!user_id) {
    return apiError("validation_error", "user_id is required");
  }

  const { error } = await supabase
    .from("worker_tokens")
    .update({ revoked_at: new Date().toISOString() })
    .eq("user_id", user_id)
    .is("revoked_at", null);

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ user_id, revoked: true });
}
