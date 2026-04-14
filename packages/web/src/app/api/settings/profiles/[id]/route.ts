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
  "name", "slug",
  "target_titles", "target_keywords",
  "excluded_titles", "excluded_companies",
  "excluded_role_keywords", "excluded_levels",
  "preferred_locations", "remote_only", "min_salary",
  "ashby_boards", "greenhouse_boards",
  "resume_id", "email_account_id",
  "application_email",
  "auto_apply", "max_daily",
] as const;

async function ownProfile(userId: string, id: string) {
  const { data } = await supabase
    .from("user_application_profiles")
    .select("id, is_default, updated_at")
    .eq("user_id", userId)
    .eq("id", id)
    .single();
  return data as { id: string; is_default: boolean; updated_at: string } | null;
}

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  const { id } = await params;
  const existing = await ownProfile(auth.userId, id);
  if (!existing) return apiError("not_found", "Profile not found");

  const body = await request.json();

  // Optimistic concurrency: if the client sent the updated_at they loaded
  // and it no longer matches, someone else (another browser tab, the
  // desktop app) saved a newer version in the meantime. Reject with 409
  // so the client can re-fetch and re-apply the edit intentionally
  // instead of silently clobbering the sibling write.
  const clientStamp = body.if_updated_at as string | undefined;
  if (clientStamp && clientStamp !== existing.updated_at) {
    return apiError(
      "conflict",
      "This profile was changed elsewhere since you loaded it. Refresh and try again.",
    );
  }

  const payload: Record<string, unknown> = { updated_at: new Date().toISOString() };
  for (const k of WRITABLE) if (k in body) payload[k] = body[k];
  if (typeof body.application_email_app_password === "string" && body.application_email_app_password.length) {
    payload.application_email_app_password_enc = encryptString(body.application_email_app_password);
  }

  // Ownership guard: resume_id + email_account_id must belong to the same
  // user. Without this check, a user could bind another tenant's Gmail
  // account and receive its decrypted app password via get_tenant_config.
  if (payload.resume_id) {
    const { data: r } = await supabase.from("user_resumes").select("id").eq("id", payload.resume_id).eq("user_id", auth.userId).maybeSingle();
    if (!r) return apiError("validation_error", "resume_id does not belong to this user");
  }
  if (payload.email_account_id) {
    const { data: e } = await supabase.from("user_email_accounts").select("id").eq("id", payload.email_account_id).eq("user_id", auth.userId).maybeSingle();
    if (!e) return apiError("validation_error", "email_account_id does not belong to this user");
  }

  const { data, error } = await supabase
    .from("user_application_profiles")
    .update(payload)
    .eq("id", id)
    .eq("user_id", auth.userId)
    .select("*")
    .single();
  if (error) return apiError("internal_server_error", error.message);
  return apiSuccess({ profile: data });
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  const { id } = await params;
  const existing = await ownProfile(auth.userId, id);
  if (!existing) return apiError("not_found", "Profile not found");
  if (existing.is_default) return apiError("validation_error", "Cannot delete the default profile. Set another profile as default first.");

  const { error } = await supabase
    .from("user_application_profiles")
    .delete()
    .eq("id", id)
    .eq("user_id", auth.userId);
  if (error) return apiError("internal_server_error", error.message);
  return apiSuccess({ deleted: true });
}
