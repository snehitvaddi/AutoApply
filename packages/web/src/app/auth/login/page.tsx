"use client";

import { useState } from "react";
import { createSupabaseBrowserClient } from "@/lib/supabase-browser";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleGoogleSignIn() {
    setLoading(true);
    setError("");

    const supabase = createSupabaseBrowserClient();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      setError(error.message);
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="max-w-md w-full bg-white rounded-xl shadow-sm border p-8">
        {/* Branding */}
        <h1 className="text-3xl font-bold text-center mb-2 text-gray-900">
          ApplyLoop
        </h1>
        <p className="text-gray-500 text-center mb-8">
          Automated job applications, powered by AI
        </p>

        {/* Value props */}
        <ul className="space-y-3 mb-8">
          <li className="flex items-start gap-3">
            <span className="flex-shrink-0 mt-0.5 h-5 w-5 rounded-full bg-brand-600 text-white flex items-center justify-center text-xs font-bold">
              1
            </span>
            <span className="text-sm text-gray-700">
              Auto-apply to 50+ jobs daily
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex-shrink-0 mt-0.5 h-5 w-5 rounded-full bg-brand-600 text-white flex items-center justify-center text-xs font-bold">
              2
            </span>
            <span className="text-sm text-gray-700">
              Works with Greenhouse, Lever, Ashby
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex-shrink-0 mt-0.5 h-5 w-5 rounded-full bg-brand-600 text-white flex items-center justify-center text-xs font-bold">
              3
            </span>
            <span className="text-sm text-gray-700">
              Telegram notifications for every application
            </span>
          </li>
        </ul>

        {/* Google Sign-In */}
        <button
          onClick={handleGoogleSignIn}
          disabled={loading}
          className="w-full py-2.5 px-4 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-3"
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24">
            <path
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
              fill="#ffffff"
              fillOpacity={0.8}
            />
            <path
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              fill="#ffffff"
              fillOpacity={0.8}
            />
            <path
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              fill="#ffffff"
              fillOpacity={0.8}
            />
            <path
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              fill="#ffffff"
              fillOpacity={0.8}
            />
          </svg>
          {loading ? "Redirecting..." : "Sign in with Google"}
        </button>

        <p className="mt-4 text-xs text-gray-400 text-center">
          New here? Click the button above to request access. New and returning
          users both sign in with Google.
        </p>

        {/* Error message */}
        {error && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-600 text-center">{error}</p>
          </div>
        )}
      </div>
    </div>
  );
}
