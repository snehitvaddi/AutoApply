import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { id } = await params;

  // Fetch the resume record to get storage_path
  const { data: resume, error: fetchError } = await supabase
    .from("user_resumes")
    .select("*")
    .eq("id", id)
    .eq("user_id", auth.userId)
    .single();

  if (fetchError || !resume) {
    return apiError("not_found", "Resume not found");
  }

  // Delete from storage
  const { error: storageError } = await supabase.storage
    .from("resumes")
    .remove([resume.storage_path]);

  if (storageError) {
    return apiError("internal_server_error", storageError.message);
  }

  // Delete from database
  const { error: deleteError } = await supabase
    .from("user_resumes")
    .delete()
    .eq("id", id)
    .eq("user_id", auth.userId);

  if (deleteError) {
    return apiError("internal_server_error", deleteError.message);
  }

  return apiSuccess({ deleted: true });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { id } = await params;
  const body = await request.json();

  // Verify ownership
  const { data: existing, error: fetchError } = await supabase
    .from("user_resumes")
    .select("id")
    .eq("id", id)
    .eq("user_id", auth.userId)
    .single();

  if (fetchError || !existing) {
    return apiError("not_found", "Resume not found");
  }

  const updates: Record<string, unknown> = {};

  // Handle setting as default
  if (body.is_default === true) {
    // Unset other defaults first
    await supabase
      .from("user_resumes")
      .update({ is_default: false })
      .eq("user_id", auth.userId);
    updates.is_default = true;
  } else if (body.is_default === false) {
    updates.is_default = false;
  }

  // Handle target_keywords update
  if (body.target_keywords !== undefined) {
    updates.target_keywords = body.target_keywords;
  }

  if (Object.keys(updates).length === 0) {
    return apiError("validation_error", "No valid fields to update");
  }

  const { data: resume, error: updateError } = await supabase
    .from("user_resumes")
    .update(updates)
    .eq("id", id)
    .eq("user_id", auth.userId)
    .select()
    .single();

  if (updateError) {
    return apiError("internal_server_error", updateError.message);
  }

  return apiSuccess({ resume });
}
