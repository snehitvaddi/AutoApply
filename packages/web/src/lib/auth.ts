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
  //
  // Worker tokens look like `al_<prefix>_<secret>`. We refuse to even hash
  // obviously-bogus inputs (empty, short, whitespace-bearing) because:
  //   - An empty or all-whitespace token would hash to a fixed value and a
  //     sufficiently distributed attacker could plant that hash in a broken
  //     deploy and gain auth for free.
  //   - Whitespace in a bearer value is almost always a copy-paste accident
  //     and never a legitimate token — fail loudly.
  const rawWorkerToken = request.headers.get("x-worker-token");
  const workerToken = rawWorkerToken?.trim() || null;
  if (rawWorkerToken !== null && (!workerToken || workerToken.length < 20 || /\s/.test(workerToken))) {
    return { error: "unauthorized" };
  }
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
  //
  // Validate the stripped token BEFORE calling Supabase:
  //   - Empty string (header was exactly "Bearer "): reject.
  //   - Whitespace-bearing: a real JWT or opaque token has no spaces.
  //   - Shorter than 20 chars: no legitimate supabase session token is that
  //     short; this blocks probe traffic from even hitting auth.getUser().
  // Any of these used to silently fall through to cookie auth, which is
  // surprising behaviour for a caller who explicitly set Authorization.
  const authHeader = request.headers.get("authorization");
  const rawToken = authHeader?.startsWith("Bearer ")
    ? authHeader.slice("Bearer ".length)
    : undefined;
  const token = rawToken?.trim();
  const bearerPresent = authHeader !== null && authHeader.startsWith("Bearer ");
  if (bearerPresent && (!token || token.length < 20 || /\s/.test(token))) {
    return { error: "unauthorized" };
  }

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
