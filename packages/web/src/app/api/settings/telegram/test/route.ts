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

  // Fetch user's telegram_chat_id
  const { data: user, error: fetchError } = await supabase
    .from("users")
    .select("telegram_chat_id")
    .eq("id", auth.userId)
    .single();

  if (fetchError || !user?.telegram_chat_id) {
    return apiError(
      "validation_error",
      "No Telegram Chat ID configured. Go to Settings > Telegram to set one."
    );
  }

  const botToken = process.env.TELEGRAM_BOT_TOKEN;
  if (!botToken) {
    return apiError("internal_server_error", "Telegram bot token not configured");
  }

  // Send test message
  const tgRes = await fetch(
    `https://api.telegram.org/bot${botToken}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: user.telegram_chat_id,
        text: "ApplyLoop test notification — your Telegram is connected!",
      }),
    }
  );

  if (!tgRes.ok) {
    const tgError = await tgRes.json().catch(() => ({}));
    return apiError(
      "internal_server_error",
      `Telegram API error: ${tgError.description || "unknown error"}`
    );
  }

  return apiSuccess({ sent: true });
}
