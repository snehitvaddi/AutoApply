import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

// Resume upload safety limits. A PDF parser down the pipeline would happily
// OOM on a 500MB file, and pdf.js has historically been a source of RCE when
// fed non-PDF bytes. We enforce two layers:
//   1. A hard byte-count cap (10MB) so no single upload can balloon memory or
//      Supabase storage quotas.
//   2. A magic-byte sniff (the first 4 bytes of a real PDF are "%PDF") so a
//      renamed .exe / .html / .zip cannot reach Storage or any downstream
//      parser. `file.type` (the browser-reported MIME) is trivially spoofable
//      and not used as the primary signal — we check it, but the magic bytes
//      are authoritative.
const MAX_RESUME_BYTES = 10 * 1024 * 1024; // 10MB
const PDF_MAGIC = Buffer.from("%PDF");

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const formData = await request.formData();
  const file = formData.get("resume") as File | null;

  if (!file) {
    return apiError("validation_error", "resume file is required");
  }

  // 1) Size cap — fail BEFORE we buffer the whole body into memory.
  if (typeof file.size === "number" && file.size > MAX_RESUME_BYTES) {
    return apiError(
      "validation_error",
      `Resume exceeds 10MB (got ${(file.size / 1024 / 1024).toFixed(1)}MB). Please upload a smaller file.`
    );
  }

  const buffer = Buffer.from(await file.arrayBuffer());

  // 2) Defense in depth against a spoofed Content-Length.
  if (buffer.length > MAX_RESUME_BYTES) {
    return apiError("validation_error", "Resume exceeds 10MB");
  }

  // 3) MIME check (secondary — the browser value is not authoritative but
  // rejecting obviously-wrong values catches naive mistakes early).
  if (file.type && file.type !== "application/pdf" && file.type !== "application/octet-stream") {
    return apiError(
      "validation_error",
      `Resume must be a PDF (got ${file.type}). Please upload a .pdf file.`
    );
  }

  // 4) Magic-byte sniff — the authoritative content check. A real PDF begins
  // with "%PDF-<version>", so anything else is rejected regardless of filename
  // or MIME claim.
  if (buffer.length < PDF_MAGIC.length || !buffer.subarray(0, PDF_MAGIC.length).equals(PDF_MAGIC)) {
    return apiError(
      "validation_error",
      "Resume must be a valid PDF (file signature check failed). Please re-export from Word/Google Docs as PDF."
    );
  }

  // 5) Sanitize the filename (no path traversal, no null bytes). We still use
  // the original file.name as the stored name for display, but strip anything
  // that would let a malicious name escape the user's directory.
  const safeName = (file.name || "resume.pdf").replace(/[^a-zA-Z0-9._-]/g, "_").slice(-120) || "resume.pdf";
  const storagePath = `${auth.userId}/${safeName}`;

  // Upload to Supabase Storage
  const { data: uploadData, error: uploadError } = await supabase.storage
    .from("resumes")
    .upload(storagePath, buffer, { contentType: file.type, upsert: true });

  if (uploadError) {
    return apiError("internal_server_error", uploadError.message);
  }

  // Parse optional target roles into keywords array
  const targetRoles = formData.get("target_roles") as string | null;
  const targetKeywords = targetRoles
    ? targetRoles.split(",").map((s) => s.trim()).filter(Boolean)
    : [];

  // Insert resume record
  const { error: insertError } = await supabase.from("user_resumes").insert({
    user_id: auth.userId,
    file_name: safeName,
    storage_path: uploadData.path,
    is_default: true,
    target_keywords: targetKeywords,
  });

  if (insertError) {
    return apiError("internal_server_error", insertError.message);
  }

  // Mark onboarding completed
  const { error: updateError } = await supabase
    .from("users")
    .update({ onboarding_completed: true })
    .eq("id", auth.userId);

  if (updateError) {
    return apiError("internal_server_error", updateError.message);
  }

  return apiSuccess({ uploaded: true, path: uploadData.path });
}
