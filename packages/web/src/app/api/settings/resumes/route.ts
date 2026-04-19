import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError, apiList } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { data, error } = await supabase
    .from("user_resumes")
    .select("*")
    .eq("user_id", auth.userId)
    .order("created_at", { ascending: false });

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiList(data || []);
}

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const formData = await request.formData();
  const file = formData.get("resume") as File | null;
  const targetRoles = formData.get("target_roles") as string | null;
  const isDefault = formData.get("is_default") === "true";

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

  // If setting as default, unset other defaults first
  if (isDefault) {
    await supabase
      .from("user_resumes")
      .update({ is_default: false })
      .eq("user_id", auth.userId);
  }

  // Parse target roles into array
  const targetKeywords = targetRoles
    ? targetRoles.split(",").map((s) => s.trim()).filter(Boolean)
    : [];

  // Dedupe by (user_id, file_name). Re-uploading the same filename
  // should REPLACE the existing row's storage_path / metadata, not
  // append another dropdown option. The dropdown grew forever before
  // this — every PDF re-upload created a new user_resumes row even
  // though Supabase Storage upserts at the same path (belt-and-
  // suspenders: upsert:true above already stomps the file bytes).
  const { data: existing } = await supabase
    .from("user_resumes")
    .select("id")
    .eq("user_id", auth.userId)
    .eq("file_name", file.name)
    .maybeSingle();

  if (existing?.id) {
    const { data: resume, error: updateError } = await supabase
      .from("user_resumes")
      .update({
        storage_path: uploadData.path,
        is_default: isDefault,
        target_keywords: targetKeywords,
      })
      .eq("id", existing.id)
      .select()
      .single();

    if (updateError) {
      return apiError("internal_server_error", updateError.message);
    }
    return apiSuccess({ resume }, 200);
  }

  // No row yet — insert fresh.
  const { data: resume, error: insertError } = await supabase
    .from("user_resumes")
    .insert({
      user_id: auth.userId,
      file_name: file.name,
      storage_path: uploadData.path,
      is_default: isDefault,
      target_keywords: targetKeywords,
    })
    .select()
    .single();

  if (insertError) {
    return apiError("internal_server_error", insertError.message);
  }

  return apiSuccess({ resume }, 201);
}
