import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { decryptIntegrationsBlob } from "@/lib/crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

/**
 * POST /api/settings/telegram/test
 *
 * Sends a test message to the user's Telegram. Supports two modes:
 *
 *   1. User has their own bot — credentials in user_profiles.
 *      integrations_encrypted (telegram_bot_token + telegram_chat_id).
 *      We decrypt and use their bot + their chat_id. This is the
 *      "bring your own bot" path from the Settings > Telegram tab's
 *      "Or use your own bot" section.
 *
 *   2. Managed @ApplyLoopBot — falls back to the shared TELEGRAM_BOT_TOKEN
 *      env var + the chat_id saved on users.telegram_chat_id. This is the
 *      default / easiest path.
 *
 * Selection rule: if the user has BOTH their own bot token AND their own
 * chat_id set, use those. Otherwise fall back to the shared bot with the
 * users.telegram_chat_id column.
 */
export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  // Fetch both the legacy users.telegram_chat_id column AND the
  // integrations_encrypted blob in one round-trip.
  const [userResp, profileResp] = await Promise.all([
    supabase
      .from("users")
      .select("telegram_chat_id")
      .eq("id", auth.userId)
      .single(),
    supabase
      .from("user_profiles")
      .select("integrations_encrypted")
      .eq("user_id", auth.userId)
      .single(),
  ]);

  // Try user's own bot first.
  let botToken = "";
  let chatId = "";
  let mode: "user_bot" | "managed_bot" = "managed_bot";

  const integrations = profileResp.data?.integrations_encrypted as
    | Record<string, string | null>
    | null;
  if (integrations) {
    const decrypted = decryptIntegrationsBlob(integrations);
    const userBot = (decrypted.telegram_bot_token || "").trim();
    const userChat = (decrypted.telegram_chat_id || "").trim();
    if (userBot && userChat) {
      botToken = userBot;
      chatId = userChat;
      mode = "user_bot";
    }
  }

  // Fall back to the managed bot.
  if (!botToken) {
    botToken = process.env.TELEGRAM_BOT_TOKEN || "";
    chatId = userResp.data?.telegram_chat_id || "";
  }

  if (!botToken) {
    return apiError(
      "internal_server_error",
      "No bot token available. Either configure your own bot in Settings > Telegram, or contact support to enable the managed bot."
    );
  }
  if (!chatId) {
    return apiError(
      "validation_error",
      "No Telegram chat ID set. Add one in Settings > Telegram before sending a test."
    );
  }

  const label = mode === "user_bot" ? "your bot" : "@ApplyLoopBot";
  const tgRes = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text: `ApplyLoop test notification via ${label} — your Telegram is connected!`,
    }),
  });

  if (!tgRes.ok) {
    const tgError = await tgRes.json().catch(() => ({}));
    return apiError(
      "internal_server_error",
      `Telegram API error (${mode}): ${
        (tgError as { description?: string }).description || "unknown error"
      }`
    );
  }

  return apiSuccess({ sent: true, mode });
}
