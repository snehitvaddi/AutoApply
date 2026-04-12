"use client";

import { useRouter } from "next/navigation";
import { SetupCard } from "@/components/SetupCard";

/**
 * Post-signup landing page. Full-bleed centered card, no dashboard chrome.
 *
 * This is where a brand-new user lands right after completing the
 * onboarding wizard — they get their activation code + desktop install
 * command + Telegram nudge, then "Go to Dashboard" when ready.
 *
 * Returning users should NOT land here — they use `/dashboard/setup`
 * which renders the same <SetupCard /> inside the dashboard chrome. The
 * sidebar "Setup" link at `components/DashboardLayout.tsx` points there,
 * not here.
 *
 * The body is extracted into `<SetupCard variant="standalone" />` so the
 * activation-code fetch, install command, and Telegram block live in
 * exactly one place.
 */
export default function SetupCompletePage() {
  const router = useRouter();

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full bg-white rounded-xl shadow-sm border p-8">
        <SetupCard variant="standalone" />

        {/* Footer CTAs — only shown on the standalone post-signup page.
            The dashboard variant doesn't need them since the user is
            already in the app. */}
        <div className="mt-8 flex items-center justify-between">
          <button
            onClick={() => router.push("/dashboard")}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Skip — go to dashboard
          </button>
          <button
            onClick={() => router.push("/dashboard")}
            className="px-6 py-2 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700"
          >
            Go to Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
