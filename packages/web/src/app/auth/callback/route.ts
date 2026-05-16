import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";

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

  // Host mismatch warning. Cookies are scoped to the responding host, so a
  // redirect to a DIFFERENT host arrives with no session — would reproduce
  // the first-login-bounce even with everything else right.
  if (request.nextUrl.origin !== appBaseUrl) {
    console.warn(
      `[auth/callback] host mismatch: request origin ${request.nextUrl.origin} ` +
        `but appBaseUrl is ${appBaseUrl}. Cookies set here will not transfer ` +
        `to the redirect target. Set NEXT_PUBLIC_APP_URL to the canonical ` +
        `origin users actually hit, or unset it to use the request origin.`
    );
  }

  // Build the final redirect response UP FRONT, even before we know where
  // to redirect to. We'll mutate its Location header at the end. The
  // Supabase server client writes session cookies directly onto this
  // response object via setAll — so they're guaranteed to ship with the
  // 302, including the chunked sb-*-auth-token.0/.1 pair.
  //
  // Why this pattern (vs cookies() from next/headers): the previous
  // attempt used cookieStore.set() inside a Route Handler. That API is
  // mutable in newer Next versions but the writes are NOT automatically
  // attached to a downstream NextResponse.redirect() — particularly for
  // chunked cookies, which Supabase SSR emits in two separate set() calls
  // and which end up split across the cookie store vs the response. The
  // user saw "first sign-in fails, second works" because the localStorage
  // shadow on the browser client bridged the second attempt.
  //
  // Holding a mutable response from the start and writing to ITS cookies
  // is the documented bulletproof pattern. We rewrite the Location at the
  // end once we know the redirectPath.
  const response = NextResponse.redirect(new URL("/", appBaseUrl));

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        // Newer Supabase SSR API: getAll/setAll. Replaces the legacy
        // get/set/remove triplet. The advantage for our case: setAll is
        // called ONCE per exchange with the full list of cookies that
        // need to be written, instead of N separate set() calls for
        // each chunked token segment. That makes "ship them with the
        // response" a single forEach instead of three places where the
        // SDK could write and we could lose a chunk.
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: Array<{ name: string; value: string; options: Record<string, unknown> }>) {
          for (const { name, value, options } of cookiesToSet) {
            response.cookies.set({ name, value, ...options });
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

  // Repoint the response built at the top of the handler at the final
  // redirect path. The session cookies the SDK wrote via setAll are
  // already attached to this response — no manual copy step. Chunked
  // sb-*-auth-token.0/.1 entries ship together, no race.
  const finalUrl = new URL(redirectPath, appBaseUrl);
  response.headers.set("Location", finalUrl.toString());
  return response;
}
