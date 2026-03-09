import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { code, email } = body;

  if (!code || !email) {
    return apiError("validation_error", "code and email are required");
  }

  // Validate invite code
  const { data: invite, error: inviteError } = await supabase
    .from("invite_codes")
    .select("*")
    .eq("code", code)
    .single();

  if (inviteError || !invite) {
    return apiError("invite_invalid");
  }

  if (!invite.is_active) {
    return apiError("invite_invalid", "Invite code is no longer active");
  }

  if (invite.used_count >= invite.max_uses) {
    return apiError("invite_invalid", "Invite code has reached maximum uses");
  }

  if (invite.expires_at && new Date(invite.expires_at) < new Date()) {
    return apiError("invite_invalid", "Invite code has expired");
  }

  // Check system max users
  const { count } = await supabase
    .from("users")
    .select("*", { count: "exact", head: true });

  if (count !== null && count >= 50) {
    return apiError("max_users_reached");
  }

  // Increment used_count
  const { error: updateError } = await supabase
    .from("invite_codes")
    .update({ used_count: invite.used_count + 1 })
    .eq("id", invite.id);

  if (updateError) {
    return apiError("internal_server_error");
  }

  return apiSuccess({ redeemed: true, email });
}
