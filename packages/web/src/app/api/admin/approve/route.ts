import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const { user_id, action } = await request.json();

  if (!user_id || !["approve", "reject"].includes(action)) {
    return apiError("validation_error", "user_id and action (approve|reject) required");
  }

  const status = action === "approve" ? "approved" : "rejected";

  const { error } = await supabase
    .from("users")
    .update({
      approval_status: status,
      approved_at: new Date().toISOString(),
      approved_by: auth.userId,
    })
    .eq("id", user_id);

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ user_id, approval_status: status });
}
