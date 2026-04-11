import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

const PUBLIC_ROUTES = [
  "/auth/login",
  "/auth/callback",
  "/auth/pending",
  "/auth/rejected",
  "/api/stripe/webhook",
  "/api/health",
  "/api/auth/status",
];

// Routes that should be accessible without authentication (exact match)
const PUBLIC_EXACT_ROUTES = ["/"];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public routes
  if (
    PUBLIC_ROUTES.some((r) => pathname.startsWith(r)) ||
    PUBLIC_EXACT_ROUTES.includes(pathname)
  ) {
    return NextResponse.next();
  }

  // Allow API routes with their own auth
  if (pathname.startsWith("/api/")) {
    // Resolve the CORS allowed origin ONCE. In production we refuse to fall
    // back to http://localhost:3000 — if NEXT_PUBLIC_APP_URL is unset in the
    // Vercel environment, that's a config bug we want to surface, not a quiet
    // "let any localhost through" default. In non-production the localhost
    // default is kept so dev loops work without env setup.
    const configuredOrigin = process.env.NEXT_PUBLIC_APP_URL?.trim();
    const isProd = process.env.NODE_ENV === "production" || process.env.VERCEL_ENV === "production";
    const allowedOrigin = configuredOrigin && /^https?:\/\//.test(configuredOrigin)
      ? configuredOrigin.replace(/\/+$/, "")
      : isProd
        ? null
        : "http://localhost:3000";

    if (request.method === "OPTIONS") {
      if (!allowedOrigin) {
        return new NextResponse("CORS origin not configured", { status: 500 });
      }
      return new NextResponse(null, {
        status: 200,
        headers: {
          "Access-Control-Allow-Origin": allowedOrigin,
          "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization",
          "Access-Control-Allow-Credentials": "true",
        },
      });
    }
    const response = NextResponse.next();
    if (allowedOrigin) {
      response.headers.set("Access-Control-Allow-Origin", allowedOrigin);
      response.headers.set("Access-Control-Allow-Credentials", "true");
    }
    // If allowedOrigin is null (prod + misconfig), we simply emit no CORS
    // headers. Same-origin calls still work; cross-origin calls fail closed.
    return response;
  }

  // Check auth for dashboard/onboarding routes
  let response = NextResponse.next();
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
          response.cookies.set({ name, value: "", ...options });
        },
      },
    }
  );

  const { data: { user } } = await supabase.auth.getUser();

  if (!user && !pathname.startsWith("/auth")) {
    return NextResponse.redirect(new URL("/auth/login", request.url));
  }

  if (user && pathname === "/auth/login") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // Check approval_status for authenticated users accessing protected routes
  if (user && !pathname.startsWith("/auth")) {
    const { data: userData } = await supabase
      .from("users")
      .select("approval_status")
      .eq("id", user.id)
      .single();

    if (userData?.approval_status === "pending") {
      return NextResponse.redirect(new URL("/auth/pending", request.url));
    }
    if (userData?.approval_status === "rejected") {
      return NextResponse.redirect(new URL("/auth/rejected", request.url));
    }
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|setup/).*)"],
};
