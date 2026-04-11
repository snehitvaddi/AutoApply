import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

function getAppBaseUrl(request: NextRequest): string {
  const configuredAppUrl = process.env.NEXT_PUBLIC_APP_URL?.trim();
  if (configuredAppUrl && /^https?:\/\//.test(configuredAppUrl)) {
    return configuredAppUrl.replace(/\/+$/, "");
  }
  return request.nextUrl.origin;
}

function loginWithError(appBaseUrl: string, reason: string, description?: string | null) {
  const url = new URL("/auth/login", appBaseUrl);
  url.searchParams.set("auth_error", reason);
  if (description) url.searchParams.set("auth_error_description", description.slice(0, 200));
  return NextResponse.redirect(url);
}

export async function GET(request: NextRequest) {
  const appBaseUrl = getAppBaseUrl(request);
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const providerError = searchParams.get("error");
  const providerErrorDescription = searchParams.get("error_description");

  // User cancelled Google consent (or the provider returned any other OAuth
  // error). Surface it back on the login page instead of silently bouncing
  // them into the unauthenticated /auth/login and leaving them confused
  // about why they're staring at the sign-in button again.
  if (providerError) {
    return loginWithError(appBaseUrl, providerError, providerErrorDescription);
  }

  if (!code) {
    return loginWithError(appBaseUrl, "missing_code");
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
    return loginWithError(
      appBaseUrl,
      "exchange_failed",
      error?.message || "Could not complete sign-in"
    );
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
  const response = NextResponse.redirect(new URL(redirectPath, appBaseUrl));
  for (const cookie of cookieStore) {
    response.cookies.set({ name: cookie.name, value: cookie.value, ...cookie.options });
  }

  return response;
}
