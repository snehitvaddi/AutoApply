import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { apiSuccess, apiError } from "@/lib/api-response";
import crypto from "crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

function hashToken(token: string): string {
  return crypto.createHash("sha256").update(token).digest("hex");
}

export async function POST(request: NextRequest) {
  const { token } = await request.json();
  if (!token) {
    return apiError("validation_error", "token is required");
  }

  const token_hash = hashToken(token);

  const { data, error } = await supabase
    .from("worker_tokens")
    .select("user_id")
    .eq("token_hash", token_hash)
    .is("revoked_at", null)
    .single();

  if (error || !data) {
    return apiError("unauthorized", "Invalid or revoked token");
  }

  return apiSuccess({
    user_id: data.user_id,
    supabase_url: process.env.NEXT_PUBLIC_SUPABASE_URL!,
    supabase_anon_key: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  });
}
