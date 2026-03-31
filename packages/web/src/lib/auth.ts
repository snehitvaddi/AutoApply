import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { createSupabaseServerClient } from "./supabase-server";
import crypto from "crypto";

export type AuthMethod = "bearer" | "cookie" | "worker-token";

export interface AuthResult {
  userId: string;
  email: string;
  authMethod: AuthMethod;
}

export type AuthError = "unauthorized";

export async function authenticateRequest(
  request: NextRequest
): Promise<AuthResult | { error: AuthError }> {
  // 0. Check for X-Worker-Token header
  const workerToken = request.headers.get("x-worker-token");
  if (workerToken) {
    const tokenHash = crypto.createHash("sha256").update(workerToken).digest("hex");
    const supabaseAdmin = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!
    );
    const { data } = await supabaseAdmin
      .from("worker_tokens")
      .select("user_id, users!inner(email)")
      .eq("token_hash", tokenHash)
      .is("revoked_at", null)
      .single();
    if (data) {
      const userRow = data.users as unknown as { email: string };
      return {
        userId: data.user_id,
        email: userRow.email,
        authMethod: "worker-token",
      };
    }
    return { error: "unauthorized" };
  }

  // 1. Check for Bearer token
  const authHeader = request.headers.get("authorization");
  const token = authHeader?.replace("Bearer ", "");

  if (token) {
    const supabaseAdmin = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!
    );

    const { data, error } = await supabaseAdmin.auth.getUser(token);
    if (!error && data.user) {
      return {
        userId: data.user.id,
        email: data.user.email || "",
        authMethod: "bearer",
      };
    }
  }

  // 2. Fallback to cookie auth
  try {
    const supabase = await createSupabaseServerClient();
    const { data, error } = await supabase.auth.getUser();
    if (!error && data.user) {
      return {
        userId: data.user.id,
        email: data.user.email || "",
        authMethod: "cookie",
      };
    }
  } catch {
    // Cookie auth may fail in certain contexts
  }

  return { error: "unauthorized" };
}

export function isAuthError(
  result: AuthResult | { error: AuthError }
): result is { error: AuthError } {
  return "error" in result;
}
