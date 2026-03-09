import { createClient } from "@supabase/supabase-js";

async function getTelegramBotToken(): Promise<string | null> {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );
  const { data } = await supabase
    .from("system_config")
    .select("value")
    .eq("key", "telegram_bot_token")
    .single();
  return data?.value?.token || process.env.TELEGRAM_BOT_TOKEN || null;
}

export async function sendTelegramMessage(chatId: string, text: string): Promise<boolean> {
  const token = await getTelegramBotToken();
  if (!token || !chatId) return false;

  const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "Markdown",
    }),
  });
  return res.ok;
}

export async function sendTelegramPhoto(
  chatId: string,
  photoUrl: string,
  caption: string
): Promise<boolean> {
  const token = await getTelegramBotToken();
  if (!token || !chatId) return false;

  const res = await fetch(`https://api.telegram.org/bot${token}/sendPhoto`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      photo: photoUrl,
      caption,
      parse_mode: "Markdown",
    }),
  });
  return res.ok;
}
