import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { AI_PROFILE_PROMPT, sanitizeParsedProfile } from "@/lib/profile-schema";

export const runtime = "nodejs";
export const maxDuration = 60;

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

/**
 * POST /api/profile/extract-resume
 *
 * Reads the user's default resume from Supabase Storage, sends it to OpenAI
 * as a PDF input with the shared AI_PROFILE_PROMPT, parses the structured
 * response, and upserts the result into `user_profiles`.
 *
 * Why this exists: the onboarding resume upload handler
 * (/api/onboarding/resume) stores the PDF but never parses it — so users who
 * go through onboarding end up with empty work_experience[] and skills[] on
 * the server. This endpoint fills that gap: it's idempotent and can be
 * called at any time (after onboarding, from the desktop PTY self-heal
 * path, or manually from a button on the dashboard).
 *
 * Auth: worker-token header (same as cli-config / settings). Does NOT
 * overwrite non-empty existing fields — the merge logic below preserves
 * whatever's already on user_profiles for each field unless the parse
 * result is non-empty.
 */
export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const openaiKey = process.env.OPENAI_API_KEY_SHARED;
  if (!openaiKey) {
    return apiError("internal_server_error", "OPENAI_API_KEY_SHARED not configured");
  }

  // 1) Find the user's default resume (or fall back to the latest).
  const { data: resumes, error: resumesErr } = await supabase
    .from("user_resumes")
    .select("storage_path, file_name, is_default, created_at")
    .eq("user_id", auth.userId)
    .order("created_at", { ascending: false });

  if (resumesErr) {
    return apiError("internal_server_error", resumesErr.message);
  }
  if (!resumes || resumes.length === 0) {
    return apiError("validation_error", "No resume uploaded. Upload a PDF first.");
  }
  const resumeRow =
    resumes.find((r) => (r as { is_default?: boolean }).is_default) || resumes[0];
  const storagePath = (resumeRow as { storage_path: string }).storage_path;

  // 2) Download the PDF bytes from Storage. Service-role key bypasses RLS.
  const { data: fileBlob, error: dlErr } = await supabase.storage
    .from("resumes")
    .download(storagePath);

  if (dlErr || !fileBlob) {
    return apiError("internal_server_error", `Resume download failed: ${dlErr?.message || "no blob"}`);
  }

  const pdfBuffer = Buffer.from(await fileBlob.arrayBuffer());
  const pdfBase64 = pdfBuffer.toString("base64");

  // Guardrail: reject anything that isn't a real PDF before spending
  // tokens at OpenAI. A real PDF starts with "%PDF".
  if (pdfBuffer.length < 4 || !pdfBuffer.subarray(0, 4).equals(Buffer.from("%PDF"))) {
    return apiError(
      "validation_error",
      "Stored resume is not a valid PDF — magic bytes mismatch. Please re-upload."
    );
  }

  // 3) Call OpenAI's Chat Completions API with the PDF as an input_file.
  // gpt-4o accepts PDF file inputs directly; no pdf-parse dependency
  // needed. We use the chat completions shape (not Responses) because it
  // has the broadest SDK parity and a well-documented `file` content type.
  const oaiResp = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${openaiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "gpt-4o",
      response_format: { type: "json_object" },
      temperature: 0.1,
      max_tokens: 4000,
      messages: [
        {
          role: "system",
          content:
            "You are a resume parser. Read the attached PDF and produce a JSON profile strictly matching the requested schema. Do not wrap in markdown; return pure JSON.",
        },
        {
          role: "user",
          content: [
            {
              type: "file",
              file: {
                filename: (resumeRow as { file_name?: string }).file_name || "resume.pdf",
                file_data: `data:application/pdf;base64,${pdfBase64}`,
              },
            },
            { type: "text", text: AI_PROFILE_PROMPT },
          ],
        },
      ],
    }),
  });

  if (!oaiResp.ok) {
    const errText = await oaiResp.text();
    return apiError("internal_server_error", `OpenAI parse failed (${oaiResp.status}): ${errText.slice(0, 300)}`);
  }

  const oaiBody = (await oaiResp.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const content = oaiBody.choices?.[0]?.message?.content;
  if (!content) {
    return apiError("internal_server_error", "OpenAI returned empty completion");
  }

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(content);
  } catch (e) {
    return apiError(
      "internal_server_error",
      `LLM returned non-JSON: ${(e as Error).message}. Preview: ${content.slice(0, 200)}`
    );
  }

  // 4) Sanitize to the persistable whitelist (drops any hallucinated columns).
  const sanitized = sanitizeParsedProfile(parsed);
  if (Object.keys(sanitized).length === 0) {
    return apiError("internal_server_error", "Parser returned no usable fields");
  }

  // 5) Merge with existing user_profiles row: only fill empty columns.
  // We don't blindly overwrite what's already there (the user may have
  // manually edited via the dashboard) — only populate fields the DB
  // currently has as null / "" / [] / {}.
  const { data: existing } = await supabase
    .from("user_profiles")
    .select("*")
    .eq("user_id", auth.userId)
    .single();

  const patch: Record<string, unknown> = { user_id: auth.userId };
  for (const [k, v] of Object.entries(sanitized)) {
    const existingVal = existing ? (existing as Record<string, unknown>)[k] : undefined;
    const existingEmpty =
      existingVal === null ||
      existingVal === undefined ||
      existingVal === "" ||
      (Array.isArray(existingVal) && existingVal.length === 0) ||
      (typeof existingVal === "object" && !Array.isArray(existingVal) && existingVal !== null && Object.keys(existingVal as object).length === 0);
    if (existingEmpty) {
      patch[k] = v;
    }
  }

  const populated = Object.keys(patch).filter((k) => k !== "user_id");
  if (populated.length === 0) {
    return apiSuccess({
      populated: [],
      note: "All parseable fields were already populated — nothing to update.",
      parsed_fields: Object.keys(sanitized),
    });
  }

  const { error: upsertErr } = await supabase
    .from("user_profiles")
    .upsert(patch, { onConflict: "user_id" });

  if (upsertErr) {
    return apiError("internal_server_error", `Upsert failed: ${upsertErr.message}`);
  }

  // Mirror work_experience / education / skills into the user's default
  // application profile bundle. Migrations 019 + 020 moved these fields
  // from user_profiles (shared) to user_application_profiles (per-bundle).
  // The worker reads from the bundle at apply time. Without this mirror,
  // an AI Import re-parse would update user_profiles but the default
  // bundle would keep serving stale W&E to every application. Same
  // non-blocking pattern as /api/worker/proxy update_profile.
  const bundleMirror: Record<string, unknown> = {};
  for (const k of ["work_experience", "education", "skills"] as const) {
    if (k in patch) bundleMirror[k] = patch[k];
  }
  if (Object.keys(bundleMirror).length > 0) {
    bundleMirror.updated_at = new Date().toISOString();
    const { error: mirrorErr } = await supabase
      .from("user_application_profiles")
      .update(bundleMirror)
      .eq("user_id", auth.userId)
      .eq("is_default", true);
    if (mirrorErr) {
      // user_profiles upsert already succeeded — log and continue.
      // Worker still sees the data via the user_profiles fallback.
      console.warn("extract-resume → default bundle mirror failed:", mirrorErr.message);
    }
  }

  return apiSuccess({
    populated,
    source_resume: (resumeRow as { file_name?: string }).file_name || storagePath,
    parsed_fields: Object.keys(sanitized),
  });
}
