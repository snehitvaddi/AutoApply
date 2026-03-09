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

  const formData = await request.formData();
  const file = formData.get("resume") as File | null;

  if (!file) {
    return apiError("validation_error", "resume file is required");
  }

  const buffer = Buffer.from(await file.arrayBuffer());
  const storagePath = `${auth.userId}/${file.name}`;

  // Upload to Supabase Storage
  const { data: uploadData, error: uploadError } = await supabase.storage
    .from("resumes")
    .upload(storagePath, buffer, { contentType: file.type, upsert: true });

  if (uploadError) {
    return apiError("internal_server_error", uploadError.message);
  }

  // Insert resume record
  const { error: insertError } = await supabase.from("user_resumes").insert({
    user_id: auth.userId,
    file_name: file.name,
    storage_path: uploadData.path,
    is_default: true,
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
