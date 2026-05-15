import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
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

  // Cookies are handled via next/headers cookies() — the mutable
  // request-scoped cookie store. The previous approach (NextResponse.next
  // as a cookie sink + manual copy to a NextResponse.redirect at the end)
  // had two specific bugs that caused the first-login-fails-second-works
  // symptom:
  //   1. Custom get() read request.cookies, which is read-only and never
  //      reflects writes made earlier in the same handler. Supabase's
  //      PKCE verifier dance does write-then-read within exchangeCode-
  //      ForSession, and a stale get() result aborted the exchange
  //      silently — so the first redirect carried no session cookies
  //      and middleware bounced the user back to /auth/login.
  //   2. NextResponse.next() is a middleware idiom; copying its cookies
  //      onto a separately-built redirect was fragile, especially for
  //      chunked sb-*-auth-token.0/.1 entries.
  // cookies() from next/headers solves both: get() sees writes, and any
  // cookie we set is automatically attached to whatever Response we
  // return. No manual shuttling.
  const cookieStore = cookies();

  // If NEXT_PUBLIC_APP_URL is set, warn loudly when the request hit a
  // different host. Cookies are scoped to the responding host, so a
  // redirect to a DIFFERENT host arrives with no session — which would
  // reproduce the first-login-bounce even after the cookie() switch.
  if (request.nextUrl.origin !== appBaseUrl) {
    console.warn(
      `[auth/callback] host mismatch: request origin ${request.nextUrl.origin} ` +
        `but appBaseUrl is ${appBaseUrl}. Cookies set here will not transfer ` +
        `to the redirect target. Set NEXT_PUBLIC_APP_URL to the canonical ` +
        `origin users actually hit, or unset it to use the request origin.`
    );
  }

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return cookieStore.get(name)?.value;
        },
        set(name: string, value: string, options: CookieOptions) {
          try {
            cookieStore.set({ name, value, ...options });
          } catch {
            // cookies() in some Next versions throws if called outside
            // the request lifecycle. Swallow defensively — auth still
            // works via the response attachment that Next does for us.
          }
        },
        remove(name: string, options: CookieOptions) {
          try {
            cookieStore.set({ name, value: "", ...options, maxAge: 0 });
          } catch {
            /* same as above */
          }
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

  // cookies() has been mutating the request-scoped store throughout this
  // handler; Next.js auto-attaches those mutations to whatever Response
  // we return. No manual cookie copy needed.
  return NextResponse.redirect(new URL(redirectPath, appBaseUrl));
}
