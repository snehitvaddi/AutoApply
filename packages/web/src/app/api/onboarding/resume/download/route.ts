import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  // Find the user's default resume
  const { data: resumes, error } = await supabase
    .from("user_resumes")
    .select("storage_path, file_name")
    .eq("user_id", auth.userId)
    .eq("is_default", true)
    .limit(1);

  if (error || !resumes || resumes.length === 0) {
    // Fall back to any resume
    const { data: anyResume } = await supabase
      .from("user_resumes")
      .select("storage_path, file_name")
      .eq("user_id", auth.userId)
      .limit(1);

    if (!anyResume || anyResume.length === 0) {
      return apiError("not_found", "No resume found");
    }

    const { data: fileData, error: downloadError } = await supabase.storage
      .from("resumes")
      .download(anyResume[0].storage_path);

    if (downloadError || !fileData) {
      return apiError("internal_server_error", "Failed to download resume");
    }

    const buffer = Buffer.from(await fileData.arrayBuffer());
    return new NextResponse(buffer, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${anyResume[0].file_name}"`,
      },
    });
  }

  const { data: fileData, error: downloadError } = await supabase.storage
    .from("resumes")
    .download(resumes[0].storage_path);

  if (downloadError || !fileData) {
    return apiError("internal_server_error", "Failed to download resume");
  }

  const buffer = Buffer.from(await fileData.arrayBuffer());
  return new NextResponse(buffer, {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="${resumes[0].file_name}"`,
    },
  });
}
