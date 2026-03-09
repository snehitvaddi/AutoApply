import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const { data: users, error } = await supabase
    .from("users")
    .select("*, applications(count)")
    .order("created_at", { ascending: false });

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  const formatted = (users || []).map((u) => ({
    ...u,
    application_count: u.applications?.[0]?.count || 0,
    applications: undefined,
  }));

  return apiSuccess({ users: formatted });
}
