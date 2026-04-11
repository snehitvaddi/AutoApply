/**
 * Symmetric encryption helpers for at-rest secrets stored in Supabase.
 *
 * Scheme: AES-256-CBC with a random 16-byte salt + random 16-byte IV per
 * ciphertext, derived key via scrypt(ENCRYPTION_KEY, salt, 32). Format is
 *
 *     <salt_hex>:<iv_hex>:<ciphertext_hex>
 *
 * This matches the existing gmail OAuth token storage at
 * api/settings/gmail/callback/route.ts so we reuse the same ENCRYPTION_KEY
 * env var and rotation story for all at-rest secrets.
 *
 * The service-role API routes encrypt on PUT and decrypt on GET; the client
 * never sees the encrypted form. Values are transmitted as plaintext over
 * authenticated TLS — the threat model is "DB dump gets stolen", not
 * "session token gets stolen".
 */
import crypto from "crypto";

function requireKey(): string {
  const k = process.env.ENCRYPTION_KEY;
  if (!k) {
    throw new Error(
      "ENCRYPTION_KEY environment variable is required for crypto helpers"
    );
  }
  return k;
}

export function encryptString(plaintext: string): string {
  if (!plaintext) return "";
  const key_material = requireKey();
  const salt = crypto.randomBytes(16);
  const key = crypto.scryptSync(key_material, salt, 32);
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv("aes-256-cbc", key, iv);
  let encrypted = cipher.update(plaintext, "utf8", "hex");
  encrypted += cipher.final("hex");
  return salt.toString("hex") + ":" + iv.toString("hex") + ":" + encrypted;
}

export function decryptString(blob: string | null | undefined): string {
  if (!blob || typeof blob !== "string") return "";
  const parts = blob.split(":");
  if (parts.length !== 3) return "";
  const [saltHex, ivHex, ciphertextHex] = parts;
  try {
    const key_material = requireKey();
    const salt = Buffer.from(saltHex, "hex");
    const iv = Buffer.from(ivHex, "hex");
    const key = crypto.scryptSync(key_material, salt, 32);
    const decipher = crypto.createDecipheriv("aes-256-cbc", key, iv);
    let decrypted = decipher.update(ciphertextHex, "hex", "utf8");
    decrypted += decipher.final("utf8");
    return decrypted;
  } catch {
    // Corrupted ciphertext, wrong key, or partial write — return empty
    // rather than crashing the route. The UI will show the field as
    // unset and the user can re-enter it.
    return "";
  }
}

/**
 * Display-safe masking. "abcd1234efgh5678" → "••••5678".
 * For values < 5 chars just returns "••••" without any tail.
 * Use on the server before sending to a client that should only see
 * a confirmation, not the actual secret (e.g. a settings page preview).
 */
export function maskSecret(plaintext: string | null | undefined): string {
  if (!plaintext || typeof plaintext !== "string") return "";
  const trimmed = plaintext.trim();
  if (trimmed.length < 5) return "••••";
  return "••••" + trimmed.slice(-4);
}

/**
 * Decrypt an object-shaped blob of ciphertext values. Used by the
 * /api/settings/integrations GET handler and the cli-config endpoint.
 */
export function decryptIntegrationsBlob(
  blob: Record<string, string | null> | null | undefined
): Record<string, string> {
  const out: Record<string, string> = {};
  if (!blob || typeof blob !== "object") return out;
  for (const [k, v] of Object.entries(blob)) {
    out[k] = decryptString(v);
  }
  return out;
}

/**
 * Encrypt an object-shaped blob of plaintext values. Empty strings are
 * dropped (so "clear this field" writes no entry rather than an
 * empty-ciphertext artifact). Used by /api/settings/integrations PUT.
 */
export function encryptIntegrationsBlob(
  plain: Record<string, string | null | undefined>
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(plain)) {
    if (!v || typeof v !== "string") continue;
    const trimmed = v.trim();
    if (!trimmed) continue;
    out[k] = encryptString(trimmed);
  }
  return out;
}
