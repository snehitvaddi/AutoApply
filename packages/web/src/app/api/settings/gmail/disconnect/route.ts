import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function DELETE(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  // Delete gmail tokens
  await supabase.from("gmail_tokens").delete().eq("user_id", auth.userId);

  // Mark gmail_connected = false on users table
  await supabase.from("users").update({ gmail_connected: false }).eq("id", auth.userId);

  return apiSuccess({ gmail_connected: false });
}
