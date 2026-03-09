import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiError, apiList } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const limit = parseInt(request.nextUrl.searchParams.get("limit") || "50", 10);
  const offset = parseInt(request.nextUrl.searchParams.get("offset") || "0", 10);

  const { data, error, count } = await supabase
    .from("applications")
    .select("*", { count: "exact" })
    .eq("user_id", auth.userId)
    .order("applied_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  const hasMore = count !== null && offset + limit < count;
  return apiList(data || [], hasMore);
}
