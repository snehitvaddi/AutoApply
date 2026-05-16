/**
 * Server-side sign-out.
 *
 * Same cookie-attachment pattern as the OAuth callback: hold a mutable
 * NextResponse from the top of the handler, give Supabase's server
 * client a setAll() that writes directly onto that response. Guarantees
 * the Set-Cookie headers with empty values + Max-Age=0 ship with the
 * 303 redirect — clears httpOnly sb-* tokens that the browser client
 * can't touch on its own.
 *
 * Before this, the browser-only signOut left httpOnly cookies in place,
 * so an immediate fresh-OAuth click would silently re-pin the user via
 * the cached session.
 */
import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";

export async function POST(request: NextRequest) {
  // Build the redirect response up front so the SDK's setAll attaches
  // its "delete" Set-Cookie entries directly onto the 303 we'll return.
  const response = NextResponse.redirect(
    new URL("/auth/login", request.url),
    { status: 303 }, // GET on /auth/login, no refresh-replay of the POST
  );

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
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

  // Trigger Supabase's clean-up. The SDK calls setAll() with empty
  // values + Max-Age=0 for each chunked sb-* token, which our setAll
  // forwards onto the response. Errors are non-fatal — we want the
  // user out regardless of whether the cloud /logout endpoint replies.
  try {
    await supabase.auth.signOut();
  } catch (err) {
    console.warn("[auth/signout] supabase.signOut threw — clearing cookies anyway:", err);
  }

  // Belt-and-suspenders: also explicitly wipe any sb-* cookie the SDK
  // might have left behind. The chunked name pattern (sb-<ref>-auth-
  // token.0, .1, -refresh-token, etc.) varies by project; pattern-
  // match on prefix.
  for (const cookie of request.cookies.getAll()) {
    if (cookie.name.startsWith("sb-")) {
      response.cookies.set({ name: cookie.name, value: "", maxAge: 0, path: "/" });
    }
  }

  return response;
}
