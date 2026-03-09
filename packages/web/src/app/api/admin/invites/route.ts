import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";
import crypto from "crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const { data, error } = await supabase
    .from("invite_codes")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ invites: data || [] });
}

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const body = await request.json();
  const { max_uses } = body;

  const code = crypto.randomBytes(4).toString("hex");

  const { data, error } = await supabase
    .from("invite_codes")
    .insert({
      code,
      max_uses: max_uses || 10,
      used_count: 0,
      is_active: true,
      created_by: auth.userId,
    })
    .select()
    .single();

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  return apiSuccess({ invite: data }, 201);
}
