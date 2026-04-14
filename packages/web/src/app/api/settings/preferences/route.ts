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

  const { data: prefs, error: prefsError } = await supabase
    .from("user_job_preferences")
    .select("*")
    .eq("user_id", auth.userId)
    .single();

  if (prefsError) {
    return apiError("not_found", "Preferences not found");
  }

  const { data: user } = await supabase
    .from("users")
    .select("tier, daily_apply_limit")
    .eq("id", auth.userId)
    .single();

  return apiSuccess({
    preferences: prefs,
    tier: user?.tier || "free",
    daily_apply_limit: user?.daily_apply_limit || 5,
  });
}

export async function PUT(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const body = await request.json();

  const { data, error } = await supabase
    .from("user_job_preferences")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("user_id", auth.userId)
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  // MIRROR to the user's default application profile. Post the
  // multi-profile refactor the worker reads scout + filter config from
  // bundles, not from this legacy table. Without this mirror, edits on
  // the Preferences tab were a dead write — users saved, saw nothing
  // happen, and assumed the whole app was broken. Only copy fields
  // that exist on both shapes.
  const mirrorFields: Record<string, unknown> = {};
  const BUNDLE_MIRRORABLE = [
    "target_titles", "target_keywords",
    "excluded_titles", "excluded_companies",
    "excluded_role_keywords", "excluded_levels",
    "preferred_locations", "remote_only", "min_salary",
    "ashby_boards", "greenhouse_boards",
    "auto_apply", "max_daily",
  ] as const;
  for (const k of BUNDLE_MIRRORABLE) {
    if (k in body) mirrorFields[k] = body[k];
  }
  if (Object.keys(mirrorFields).length > 0) {
    mirrorFields.updated_at = new Date().toISOString();
    const { data: mirrorRows, error: mirrorErr } = await supabase
      .from("user_application_profiles")
      .update(mirrorFields)
      .eq("user_id", auth.userId)
      .eq("is_default", true)
      .select("id");
    if (mirrorErr) {
      // Don't fail the whole PUT — legacy write already succeeded.
      // Log for debugging but return success so the UI doesn't double-flash.
      console.warn("preferences mirror to default bundle failed:", mirrorErr.message);
    } else if (!mirrorRows || mirrorRows.length === 0) {
      // User has no default bundle — the mirror was a silent no-op, and
      // the worker reads from bundles. Without surfacing this, the user
      // would think they saved and wonder why nothing happens. Return
      // success (legacy table did persist) + a warning so the UI can
      // nudge them to the Profiles tab.
      console.warn(`preferences mirror: no default bundle for user ${auth.userId} — worker will not see these edits`);
      return apiSuccess({
        preferences: data,
        warning: "Saved to legacy preferences, but you have no default Profile — the worker reads from Profiles. Create one in the Profiles tab.",
      });
    }
  }

  return apiSuccess({ preferences: data });
}
