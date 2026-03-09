import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { id } = await params;
  const body = await request.json();
  const { action } = body;

  if (!action || !["approved", "skipped"].includes(action)) {
    return apiError("validation_error", "action must be 'approved' or 'skipped'");
  }

  // Update match status
  const { data: match, error: matchError } = await supabase
    .from("user_job_matches")
    .update({ status: action, updated_at: new Date().toISOString() })
    .eq("id", id)
    .eq("user_id", auth.userId)
    .select()
    .single();

  if (matchError) {
    return apiError("not_found", "Match not found");
  }

  // If approved, insert into application queue
  if (action === "approved") {
    const { error: queueError } = await supabase
      .from("application_queue")
      .insert({
        user_id: auth.userId,
        job_id: match.job_id,
        status: "pending",
      });

    if (queueError) {
      return apiError("internal_server_error", queueError.message);
    }
  }

  return apiSuccess({ match });
}
