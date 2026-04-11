/**
 * GET /api/me/activation-code
 *
 * Returns the current authenticated user's most recent live activation code
 * (if one exists) so the /setup-complete page can display it without the user
 * having to DM the admin or wait for a Telegram message (which may never
 * arrive if they haven't linked Telegram yet).
 *
 * Authenticated via Supabase cookie session (the page is behind auth). We use
 * the service role client ONLY to read the activation_codes table — every
 * filter pins `user_id = <session user>`, so users can never see another
 * user's code. The full code value is still scoped to the requesting user.
 *
 * Response shape:
 *   { data: { code, expires_at, uses_remaining, created_at } | null }
 *
 * Returns `data: null` (not 404) when:
 *   - the user has never had a code issued
 *   - all their codes are expired or exhausted
 * so the frontend can render a "request one from admin" fallback without
 * treating it as an error.
 */
import { createClient } from "@supabase/supabase-js";
import { getAuthUser } from "@/lib/supabase-server";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabaseAdmin = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET() {
  const user = await getAuthUser();
  if (!user) return apiError("unauthorized");

  const nowIso = new Date().toISOString();

  // Pick the most recently created code for this user that is still
  // redeemable (not expired, has uses remaining). If none qualify, return
  // null so the UI can render the fallback path.
  const { data, error } = await supabaseAdmin
    .from("activation_codes")
    .select("code, expires_at, uses_remaining, created_at")
    .eq("user_id", user.id)
    .gt("expires_at", nowIso)
    .gt("uses_remaining", 0)
    .order("created_at", { ascending: false })
    .limit(1);

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  const row = data && data.length > 0 ? data[0] : null;
  return apiSuccess(row);
}
