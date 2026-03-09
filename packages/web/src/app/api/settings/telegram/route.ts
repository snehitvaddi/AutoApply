import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const body = await request.json();
  const { chat_id } = body;

  if (!chat_id) {
    return apiError("validation_error", "chat_id is required");
  }

  const { error } = await supabase
    .from("users")
    .update({ telegram_chat_id: chat_id })
    .eq("id", auth.userId);

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ telegram_chat_id: chat_id });
}

export async function DELETE(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { error } = await supabase
    .from("users")
    .update({ telegram_chat_id: null })
    .eq("id", auth.userId);

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ telegram_chat_id: null });
}
