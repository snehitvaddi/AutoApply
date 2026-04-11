/**
 * Admin: generate + revoke activation codes.
 *
 * POST  /api/admin/activation-code { user_id, expires_hours?, notes? }
 *   → Creates a short, human-friendly activation code (e.g. AL-X4B9-T2Q7)
 *   → Inserts into activation_codes with 7d TTL + 5 uses by default
 *   → Best-effort Telegram DM to the user if users.telegram_chat_id is set
 *   → Returns { code, expires_at, uses_remaining, telegram_sent }
 *
 * DELETE /api/admin/activation-code { code }
 *   → Revokes (deletes) a single code
 */
import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import crypto from "crypto";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

// Code alphabet: 32 chars, skips ambiguous 0/O/1/I/L to avoid typing errors.
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

function generateCode(): string {
  const block = () =>
    Array.from(
      { length: 4 },
      () => CODE_ALPHABET[crypto.randomInt(CODE_ALPHABET.length)]
    ).join("");
  return `AL-${block()}-${block()}`;
}

/**
 * Best-effort Telegram DM. Never throws — if it fails, the code is still returned
 * to the admin and they can copy from the modal as a fallback.
 */
async function sendTelegramDM(params: {
  chatId: string;
  code: string;
  expiresAt: string;
  usesRemaining: number;
  fullName: string | null;
}): Promise<boolean> {
  const botToken = process.env.TELEGRAM_BOT_TOKEN;
  if (!botToken) return false;
  try {
    const expiresPretty = new Date(params.expiresAt).toLocaleString("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    });
    const greeting = params.fullName ? `Hi ${params.fullName},` : "Hi,";
    const msg = [
      `🔑 *Your ApplyLoop Activation Code*`,
      ``,
      greeting,
      `Your access has been approved. Use the code below to activate the ApplyLoop desktop app:`,
      ``,
      `\`${params.code}\``,
      ``,
      `Open the ApplyLoop desktop app, paste this code in the setup screen, and you're done.`,
      ``,
      `_Expires:_ ${expiresPretty}`,
      `_Uses remaining:_ ${params.usesRemaining}`,
    ].join("\n");

    const r = await fetch(
      `https://api.telegram.org/bot${botToken}/sendMessage`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: params.chatId,
          text: msg,
          parse_mode: "Markdown",
          disable_web_page_preview: true,
        }),
      }
    );
    return r.ok;
  } catch (err) {
    console.warn("[activation-code] Telegram DM failed:", err);
    return false;
  }
}

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const body = await request.json().catch(() => ({}));
  const user_id: string | undefined = body.user_id;
  const expires_hours: number = Number(body.expires_hours ?? 168); // default 7 days
  const uses_remaining: number = Number(body.uses_remaining ?? 5);
  const notes: string | undefined = body.notes;

  if (!user_id) {
    return apiError("validation_error", "user_id is required");
  }
  if (!Number.isFinite(expires_hours) || expires_hours <= 0 || expires_hours > 24 * 365) {
    return apiError("validation_error", "expires_hours must be between 1 and 8760");
  }
  if (!Number.isFinite(uses_remaining) || uses_remaining <= 0 || uses_remaining > 100) {
    return apiError("validation_error", "uses_remaining must be between 1 and 100");
  }

  // Verify the user exists + is approved.
  const { data: userRow, error: userErr } = await supabase
    .from("users")
    .select("id, email, full_name, telegram_chat_id, approval_status")
    .eq("id", user_id)
    .single();

  if (userErr || !userRow) {
    return apiError("not_found", "User not found");
  }
  if (userRow.approval_status !== "approved") {
    return apiError("validation_error", "User is not approved yet", {
      approval_status: userRow.approval_status,
    });
  }

  // Generate a unique code. Retry a few times in the astronomically unlikely
  // event of a collision with an existing row.
  const expires_at = new Date(Date.now() + expires_hours * 3600 * 1000).toISOString();
  let code = "";
  let insertError: { message: string } | null = null;
  for (let attempt = 0; attempt < 5; attempt++) {
    code = generateCode();
    const { error } = await supabase.from("activation_codes").insert({
      code,
      user_id,
      created_by: auth.userId,
      expires_at,
      uses_remaining,
      notes: notes || null,
    });
    if (!error) {
      insertError = null;
      break;
    }
    // Only retry on unique-violation (Postgres code 23505). Fail fast otherwise.
    if (!(error as { code?: string }).code || (error as { code?: string }).code !== "23505") {
      insertError = error;
      break;
    }
    insertError = error;
  }

  if (insertError) {
    return apiError("internal_server_error", insertError.message);
  }

  // Best-effort Telegram DM to the user.
  let telegram_sent = false;
  if (userRow.telegram_chat_id) {
    telegram_sent = await sendTelegramDM({
      chatId: userRow.telegram_chat_id,
      code,
      expiresAt: expires_at,
      usesRemaining: uses_remaining,
      fullName: (userRow as { full_name?: string }).full_name || null,
    });
  }

  return apiSuccess({
    code,
    user_id,
    expires_at,
    uses_remaining,
    telegram_sent,
    telegram_chat_id: userRow.telegram_chat_id || null,
  });
}

export async function DELETE(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const body = await request.json().catch(() => ({}));
  const code: string | undefined = body.code;
  const user_id: string | undefined = body.user_id;

  if (!code && !user_id) {
    return apiError("validation_error", "code or user_id is required");
  }

  const deleteQuery = supabase.from("activation_codes").delete({ count: "exact" });
  const { error, count } = code
    ? await deleteQuery.eq("code", code)
    : await deleteQuery.eq("user_id", user_id!);

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ revoked: true, count: count || 0 });
}
