import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  const { id } = await params;

  // Atomic flip via the 017 RPC. The RPC verifies ownership (refuses if
  // p_profile_id doesn't belong to p_user_id) and does the is_default
  // toggle in a single UPDATE so the partial unique index can't trip.
  // No fallback — migration 017 is required.
  const { error: rpcErr } = await supabase.rpc("set_default_application_profile", {
    p_user_id: auth.userId,
    p_profile_id: id,
  });
  if (rpcErr) {
    const msg = rpcErr.message || "";
    if (msg.includes("profile_not_found")) return apiError("not_found", "Profile not found");
    if (msg.includes("profile_not_owned")) return apiError("forbidden", "Profile not owned by this user");
    return apiError("internal_server_error", msg);
  }
  const { data } = await supabase
    .from("user_application_profiles")
    .select("*")
    .eq("id", id)
    .eq("user_id", auth.userId)
    .single();
  if (!data) return apiError("not_found", "Profile not found");
  return apiSuccess({ profile: data });
}
