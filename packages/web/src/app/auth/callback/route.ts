import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");

  if (!code) {
    return NextResponse.redirect(new URL("/auth/login", request.url));
  }

  // We don't know the final redirect yet, so start with a placeholder.
  // We'll create a fresh redirect response once we know the destination.
  const cookieStore: { name: string; value: string; options: CookieOptions }[] =
    [];

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return request.cookies.get(name)?.value;
        },
        set(name: string, value: string, options: CookieOptions) {
          cookieStore.push({ name, value, options });
        },
        remove(name: string, options: CookieOptions) {
          cookieStore.push({ name, value: "", options });
        },
      },
    }
  );

  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.user) {
    return NextResponse.redirect(new URL("/auth/login", request.url));
  }

  // Service-role client for admin operations (bypasses RLS)
  const admin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  const userId = data.user.id;
  const email = data.user.email || "";
  const fullName = data.user.user_metadata?.full_name || "";
  const avatarUrl = data.user.user_metadata?.avatar_url || "";

  let redirectPath: string;

  // Check if a user row already exists
  const { data: existingUser } = await admin
    .from("users")
    .select("id, approval_status, onboarding_completed, is_admin")
    .eq("id", userId)
    .single();

  if (!existingUser) {
    // New signup — check if admin pre-approved this email
    const { data: preApproved } = await admin
      .from("users")
      .select("id")
      .eq("email", email)
      .eq("approval_status", "approved")
      .single();

    const approvalStatus = preApproved ? "approved" : "pending";

    await admin.from("users").insert({
      id: userId,
      email,
      full_name: fullName,
      avatar_url: avatarUrl,
      approval_status: approvalStatus,
    });

    redirectPath =
      approvalStatus === "approved" ? "/onboarding" : "/auth/pending";
  } else {
    // Existing user — route based on approval status
    switch (existingUser.approval_status) {
      case "pending":
        redirectPath = "/auth/pending";
        break;
      case "rejected":
        redirectPath = "/auth/rejected";
        break;
      case "approved":
        if (existingUser.is_admin) {
          redirectPath = "/admin";
        } else {
          redirectPath = existingUser.onboarding_completed
            ? "/dashboard"
            : "/onboarding";
        }
        break;
      default:
        // Unknown status — treat as pending
        redirectPath = "/auth/pending";
    }
  }

  // Build the final redirect with all cookies from the session exchange
  const response = NextResponse.redirect(new URL(redirectPath, request.url));
  for (const cookie of cookieStore) {
    response.cookies.set({ name: cookie.name, value: cookie.value, ...cookie.options });
  }

  return response;
}
