import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import {
  encryptIntegrationsBlob,
  decryptIntegrationsBlob,
  maskSecret,
} from "@/lib/crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

/**
 * Third-party integration credentials — Telegram, Gmail, AgentMail,
 * Finetune Resume. Stored encrypted in user_profiles.integrations_encrypted
 * so the cloud is the single source of truth for all three entry points
 * (web dashboard settings, desktop settings, and the curl installer).
 *
 * GET  /api/settings/integrations           → masked values + list of which fields are set
 * GET  /api/settings/integrations?raw=1     → plaintext (desktop .env sync path)
 * PUT  /api/settings/integrations           → upsert, encrypting fields present in body
 *
 * Auth: worker-token header (same as /api/settings/profile, cli-config).
 *
 * Shape validations enforce the same regexes the installer uses:
 *   - telegram_bot_token: ^[0-9]{6,}:[A-Za-z0-9_-]{25,}$
 *   - telegram_chat_id:   ^-?[0-9]+$
 *   - gmail_email:        simple RFC-5322 lite
 *   - gmail_app_password: 16 chars (Google's app password length)
 *   - agentmail_api_key / finetune_resume_api_key: ≥8 chars
 *
 * Setting a field to an empty string deletes it from the blob (the client
 * uses this as "clear this integration").
 */

const INTEGRATION_FIELDS = [
  "telegram_bot_token",
  "telegram_chat_id",
  "gmail_email",
  "gmail_app_password",
  "agentmail_api_key",
  "finetune_resume_api_key",
] as const;
type IntegrationField = (typeof INTEGRATION_FIELDS)[number];

const VALIDATORS: Record<IntegrationField, (v: string) => string | null> = {
  telegram_bot_token: (v) => {
    if (!/^[0-9]{6,}:[A-Za-z0-9_-]{25,}$/.test(v)) {
      return "Telegram bot token must look like <bot_id>:<secret>, e.g. 1234567890:ABCdef-ghi...";
    }
    return null;
  },
  telegram_chat_id: (v) => {
    if (!/^-?[0-9]+$/.test(v)) {
      return "Telegram chat ID must be a signed integer (group chats start with -).";
    }
    return null;
  },
  gmail_email: (v) => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) {
      return "Gmail email must be a valid email address.";
    }
    return null;
  },
  gmail_app_password: (v) => {
    // Google app passwords are displayed with spaces for readability
    // (e.g. "abcd efgh ijkl mnop") but are 16 chars when spaces are stripped.
    const stripped = v.replace(/\s+/g, "");
    if (stripped.length !== 16) {
      return "Gmail app password must be 16 characters (spaces are optional).";
    }
    return null;
  },
  agentmail_api_key: (v) => {
    if (v.length < 8) return "AgentMail API key looks too short (expected ≥8 chars).";
    return null;
  },
  finetune_resume_api_key: (v) => {
    if (v.length < 8) return "Finetune Resume API key looks too short (expected ≥8 chars).";
    return null;
  },
};

async function loadProfile(userId: string) {
  const { data, error } = await supabase
    .from("user_profiles")
    .select("integrations_encrypted")
    .eq("user_id", userId)
    .single();
  if (error) {
    // Could be "column does not exist" if the migration hasn't been run
    // on this Supabase project yet. Surface the exact cause so the user
    // knows to paste the SQL from supabase/migrations/010_user_integrations.sql.
    if (error.message?.includes("integrations_encrypted")) {
      throw new Error(
        "Database is missing integrations_encrypted column. Run the migration in supabase/migrations/010_user_integrations.sql against your Supabase project (SQL editor → paste → run)."
      );
    }
    throw error;
  }
  return (data?.integrations_encrypted ?? {}) as Record<string, string | null>;
}

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const raw = request.nextUrl.searchParams.get("raw") === "1";

  let encryptedBlob: Record<string, string | null>;
  try {
    encryptedBlob = await loadProfile(auth.userId);
  } catch (e) {
    return apiError("internal_server_error", (e as Error).message);
  }

  const plaintext = decryptIntegrationsBlob(encryptedBlob);

  if (raw) {
    // Desktop .env sync path. Returns plaintext for every field that has
    // a value. Gated on worker-token auth + HTTPS; same security posture
    // as /api/settings/cli-config.
    return apiSuccess({ integrations: plaintext });
  }

  // UI path: return a map of { field_name: { set: bool, mask: "••••1234" } }
  // so the dashboard can show "(not set)" vs "(••••1234, edit)" without
  // ever sending the plaintext over the wire to client-rendered JS.
  const display: Record<string, { set: boolean; mask: string }> = {};
  for (const field of INTEGRATION_FIELDS) {
    const v = plaintext[field] || "";
    display[field] = { set: Boolean(v), mask: v ? maskSecret(v) : "" };
  }
  return apiSuccess({ integrations: display });
}

export async function PUT(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return apiError("validation_error", "Request body must be JSON.");
  }

  // Validate the fields the client is trying to set. Empty string means
  // "clear this field" — we still merge it in (and the encrypt helper
  // drops empty values), resulting in the key being omitted from the blob.
  const updates: Record<string, string> = {};
  for (const field of INTEGRATION_FIELDS) {
    if (!(field in body)) continue;
    const v = body[field];
    if (v === null || v === undefined) {
      updates[field] = "";
      continue;
    }
    if (typeof v !== "string") {
      return apiError("validation_error", `${field} must be a string.`);
    }
    const trimmed = v.trim();
    if (trimmed === "") {
      // Explicit clear — we want this to actually remove the field.
      updates[field] = "";
      continue;
    }
    const err = VALIDATORS[field](trimmed);
    if (err) return apiError("validation_error", err);
    updates[field] = trimmed;
  }

  if (Object.keys(updates).length === 0) {
    return apiError("validation_error", "No integration fields provided.");
  }

  // Load existing blob so we merge rather than overwrite (partial update).
  let existing: Record<string, string | null>;
  try {
    existing = await loadProfile(auth.userId);
  } catch (e) {
    return apiError("internal_server_error", (e as Error).message);
  }

  // Decrypt existing to plaintext, apply updates, re-encrypt. This way
  // "clear this field" (empty string) results in the key being dropped
  // from the re-encrypted blob rather than persisting as empty ciphertext.
  const merged = { ...decryptIntegrationsBlob(existing) };
  for (const [k, v] of Object.entries(updates)) {
    if (v === "") {
      delete merged[k];
    } else {
      merged[k] = v;
    }
  }

  const reEncrypted = encryptIntegrationsBlob(merged);

  const { error: upsertErr } = await supabase
    .from("user_profiles")
    .update({ integrations_encrypted: reEncrypted, updated_at: new Date().toISOString() })
    .eq("user_id", auth.userId);

  if (upsertErr) {
    return apiError("internal_server_error", `Update failed: ${upsertErr.message}`);
  }

  // Return the new display state so the UI can render the masked values
  // without a follow-up GET.
  const display: Record<string, { set: boolean; mask: string }> = {};
  for (const field of INTEGRATION_FIELDS) {
    const v = merged[field] || "";
    display[field] = { set: Boolean(v), mask: v ? maskSecret(v) : "" };
  }
  return apiSuccess({
    updated: Object.keys(updates),
    integrations: display,
  });
}
