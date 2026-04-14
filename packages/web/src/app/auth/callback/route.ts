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
    console.error("[auth/callback] provider error:", providerError, providerErrorDescription);
    return loginWithError(appBaseUrl, providerError, providerErrorDescription);
  }

  if (!code) {
    console.error("[auth/callback] missing code in request");
    return loginWithError(appBaseUrl, "missing_code");
  }

  // CRITICAL: attach the Supabase server client directly to a response
  // object so the SDK's set()/remove() calls write to the FINAL response
  // headers. The previous pattern (buffering cookies into a local array
  // then copying onto a redirect response at the end) was fragile for
  // two reasons:
  //   1. Chunked cookies (`sb-*-auth-token.0`, `.1`) may be written AND
  //      removed in the same exchange — the manual array let the last
  //      write-or-remove win, which could leave stale half-chunks on
  //      the response.
  //   2. exchangeCodeForSession needs to READ the PKCE verifier cookie
  //      after some internal writes; with the buffered pattern those
  //      writes weren't visible to subsequent reads.
  //
  // First-login-fails / second-login-succeeds was the exact symptom of
  // the chunked-cookie race. Using a single mutable NextResponse fixes
  // it by delegating cookie handling entirely to the SDK.
  //
  // We start with a no-op response, let the SDK attach cookies, then
  // rewrite the Location header at the end once we know where to send
  // the user. Cloning the cookies across to the final redirect preserves
  // them.
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return request.cookies.get(name)?.value;
        },
        set(name: string, value: string, options: CookieOptions) {
          response.cookies.set({ name, value, ...options });
        },
        remove(name: string, options: CookieOptions) {
          // Explicit remove — set an empty value with Max-Age=0 so the
          // browser drops the cookie. Needed to clean up the PKCE
          // verifier + any stale chunks from a prior failed attempt.
          response.cookies.set({ name, value: "", ...options, maxAge: 0 });
        },
      },
    }
  );

  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.user) {
    console.error("[auth/callback] exchange failed:", {
      error_code: error?.code,
      error_message: error?.message,
      has_user: !!data?.user,
      cookie_names: request.cookies.getAll().map((c) => c.name),
    });
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

  // Use maybeSingle() instead of single() — single() raises PGRST116 when
  // zero rows exist (a valid case for new users) which clutters logs and
  // was historically papered over by the `data` being null anyway. The
  // explicit maybeSingle makes the intent clear.
  const { data: existingUser, error: selectError } = await admin
    .from("users")
    .select("id, approval_status, onboarding_completed, is_admin")
    .eq("id", userId)
    .maybeSingle();

  if (selectError) {
    console.error("[auth/callback] users select failed:", selectError.message);
    // Fall through — we'll try to insert below and let that error if it's
    // also broken.
  }

  if (!existingUser) {
    // New signup — check if admin pre-approved this email
    const { data: preApproved } = await admin
      .from("users")
      .select("id")
      .eq("email", email)
      .eq("approval_status", "approved")
      .maybeSingle();

    const approvalStatus = preApproved ? "approved" : "pending";

    // Use upsert to survive the race with any database trigger that
    // might auto-create public.users rows (e.g. a handle_new_user
    // trigger on auth.users). Without the upsert, a concurrent trigger
    // insert would cause our plain insert to 23505 and surface a
    // visible error on the first login.
    const { error: upsertError } = await admin
      .from("users")
      .upsert(
        {
          id: userId,
          email,
          full_name: fullName,
          avatar_url: avatarUrl,
          approval_status: approvalStatus,
        },
        { onConflict: "id", ignoreDuplicates: false },
      );

    if (upsertError) {
      console.error("[auth/callback] users upsert failed:", upsertError.message);
      // Don't bounce them out — the session IS established and they can
      // retry from /auth/pending or /onboarding. Route based on what we
      // intended to set so the UX doesn't regress.
    }

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

  // Build the final redirect, carrying every cookie the SDK wrote onto
  // `response`. NextResponse's cookie jar is spec-compliant so this
  // handles the chunked `sb-*-auth-token.N` case correctly.
  const redirectResponse = NextResponse.redirect(new URL(redirectPath, appBaseUrl));
  for (const cookie of response.cookies.getAll()) {
    redirectResponse.cookies.set(cookie);
  }
  return redirectResponse;
}
