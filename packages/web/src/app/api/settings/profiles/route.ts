import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { encryptString } from "@/lib/crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

const WRITABLE = [
  "name", "slug", "is_default",
  "target_titles", "target_keywords",
  "excluded_titles", "excluded_companies",
  "excluded_role_keywords", "excluded_levels",
  "preferred_locations", "remote_only", "min_salary",
  "ashby_boards", "greenhouse_boards",
  "resume_id", "email_account_id",
  "application_email",
  "auto_apply", "max_daily",
  // Per-bundle content (mig 019) — per-role answer key + cover letter.
  "answer_key_json", "cover_letter_template",
] as const;

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "profile";
}

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { data, error } = await supabase
    .from("user_application_profiles")
    .select("*")
    .eq("user_id", auth.userId)
    .order("is_default", { ascending: false })
    .order("created_at", { ascending: true });
  if (error) return apiError("internal_server_error", error.message);

  // Never return the encrypted app password blob to the client — mask it.
  const sanitized = (data || []).map((p) => {
    const { application_email_app_password_enc, ...rest } = p as Record<string, unknown>;
    return { ...rest, has_app_password: !!application_email_app_password_enc };
  });
  return apiSuccess({ profiles: sanitized });
}

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const body = await request.json();
  const payload: Record<string, unknown> = { user_id: auth.userId };
  for (const k of WRITABLE) if (k in body) payload[k] = body[k];
  if (!payload.name) return apiError("validation_error", "name is required");
  if (!payload.slug) payload.slug = slugify(payload.name as string);

  // Plaintext app password → encrypt + drop plaintext from payload
  if (typeof body.application_email_app_password === "string" && body.application_email_app_password.length) {
    payload.application_email_app_password_enc = encryptString(body.application_email_app_password);
  }

  // Ownership guard — same as PUT. Without this, a user could bind
  // another tenant's Gmail account and exfiltrate its app password via
  // get_tenant_config.
  if (payload.resume_id) {
    const { data: r } = await supabase.from("user_resumes").select("id").eq("id", payload.resume_id).eq("user_id", auth.userId).maybeSingle();
    if (!r) return apiError("validation_error", "resume_id does not belong to this user");
  }
  if (payload.email_account_id) {
    const { data: e } = await supabase.from("user_email_accounts").select("id").eq("id", payload.email_account_id).eq("user_id", auth.userId).maybeSingle();
    if (!e) return apiError("validation_error", "email_account_id does not belong to this user");
  }

  // First profile for a user is forced default. For a second+ profile
  // with is_default=true, we insert with is_default=false first and then
  // atomically flip via the 017 RPC. This avoids the race where two
  // concurrent "create-as-default" POSTs could both clear-then-insert
  // and trip uniq_default_profile_per_user.
  const { count } = await supabase
    .from("user_application_profiles")
    .select("id", { count: "exact", head: true })
    .eq("user_id", auth.userId);

  const wantsDefault = payload.is_default === true || !count;
  // Stage the row as non-default; promote via RPC below if needed.
  payload.is_default = !count ? true : false;

  const { data, error } = await supabase
    .from("user_application_profiles")
    .insert(payload)
    .select("*")
    .single();
  if (error) {
    if ((error as { code?: string }).code === "23505") {
      return apiError("validation_error", `A profile named "${payload.name}" already exists. Pick a different name.`);
    }
    return apiError("internal_server_error", error.message);
  }

  // If the caller wanted this non-first row to be default, flip atomically.
  if (wantsDefault && count) {
    const { error: rpcErr } = await supabase.rpc("set_default_application_profile", {
      p_user_id: auth.userId,
      p_profile_id: data.id,
    });
    if (rpcErr) {
      return apiError("internal_server_error", `profile created but set-default failed: ${rpcErr.message}`);
    }
  }

  return apiSuccess({ profile: data });
}
