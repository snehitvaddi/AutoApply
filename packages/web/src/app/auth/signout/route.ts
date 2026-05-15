/**
 * Server-side sign-out.
 *
 * The previous client-only handler (DashboardLayout.handleSignOut) was:
 *   await supabase.auth.signOut(); router.push("/auth/login");
 *
 * That has two failure modes that produced the "signout → Google account
 * chooser" symptom users reported:
 *   1. The browser client can only clear non-httpOnly cookies + localStorage.
 *      The sb-*-auth-token.* cookies set by createServerClient on the
 *      callback are httpOnly and survive. Subsequent navigation still sees
 *      a valid server-side session, so middleware (or any auto-redirect
 *      to OAuth on /auth/login) can silently re-pin them.
 *   2. router.push is a soft client navigation. localStorage from the old
 *      session leaks into the new mount and Supabase's browser client may
 *      replay the OAuth flow.
 *
 * This route runs on the server with a cookies()-bound Supabase client, so
 * supabase.auth.signOut() can actually remove the httpOnly entries via its
 * remove() callback. As a belt-and-suspenders we also nuke any sb-* cookie
 * the SDK leaves behind. The client calls this with fetch + then does a
 * window.location.assign so the next page hydrates fresh with no stale
 * localStorage.
 */
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

export async function POST(_request: NextRequest) {
  const cookieStore = cookies();

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
            /* see callback route for rationale */
          }
        },
        remove(name: string, options: CookieOptions) {
          try {
            cookieStore.set({ name, value: "", ...options, maxAge: 0 });
          } catch {
            /* same */
          }
        },
      },
    }
  );

  // Let Supabase clean up its own session cookies via the remove() callback.
  // Catch errors — even if this throws (revoked token, network glitch with
  // the Supabase logout endpoint), we still want to wipe local cookies and
  // return the redirect.
  try {
    await supabase.auth.signOut();
  } catch (err) {
    console.warn("[auth/signout] supabase.signOut threw — clearing cookies anyway:", err);
  }

  // Belt-and-suspenders: wipe any sb-* cookie still in the store. The SDK
  // names cookies based on the project ref (sb-<ref>-auth-token, .0, .1,
  // -refresh-token, etc.) so we can't enumerate by exact name without
  // hardcoding the ref. Wildcard by prefix is the safe approach.
  for (const cookie of cookieStore.getAll()) {
    if (cookie.name.startsWith("sb-")) {
      try {
        cookieStore.set({ name: cookie.name, value: "", maxAge: 0, path: "/" });
      } catch {
        /* nothing to do */
      }
    }
  }

  // 303 See Other forces the browser to do a GET on /auth/login after the
  // POST, which is what we want — and most browsers won't repost the POST
  // body on refresh either.
  return NextResponse.redirect(new URL("/auth/login", _request.url), { status: 303 });
}
