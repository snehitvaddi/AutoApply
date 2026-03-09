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

  const body = await request.json();
  const { match_ids } = body;

  if (!Array.isArray(match_ids) || match_ids.length === 0) {
    return apiError("validation_error", "match_ids must be a non-empty array");
  }

  // Update all matches to queued
  const { data: matches, error: updateError } = await supabase
    .from("user_job_matches")
    .update({ status: "queued", updated_at: new Date().toISOString() })
    .in("id", match_ids)
    .eq("user_id", auth.userId)
    .select();

  if (updateError) {
    return apiError("internal_server_error", updateError.message);
  }

  // Insert all into application queue
  const queueEntries = (matches || []).map((m) => ({
    user_id: auth.userId,
    job_id: m.job_id,
    status: "pending" as const,
  }));

  if (queueEntries.length > 0) {
    const { error: queueError } = await supabase
      .from("application_queue")
      .insert(queueEntries);

    if (queueError) {
      return apiError("internal_server_error", queueError.message);
    }
  }

  return apiSuccess({ queued: queueEntries.length });
}
