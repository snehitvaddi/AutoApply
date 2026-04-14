import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  const { id } = await params;
  const { error } = await supabase
    .from("user_email_accounts")
    .delete()
    .eq("id", id)
    .eq("user_id", auth.userId);
  if (error) return apiError("internal_server_error", error.message);
  return apiSuccess({ deleted: true });
}
