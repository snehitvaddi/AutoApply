"use client";

import { useEffect, useState } from "react";
import { createSupabaseBrowserClient } from "@/lib/supabase-browser";
import { useRouter } from "next/navigation";

export default function PendingApprovalPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");

  useEffect(() => {
    const supabase = createSupabaseBrowserClient();

    // Get current user email
    supabase.auth.getUser().then(({ data }) => {
      if (data.user?.email) setEmail(data.user.email);
    });

    // Poll for approval every 10 seconds
    const interval = setInterval(async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      const res = await fetch("/api/auth/status");
      if (res.ok) {
        const { data } = await res.json();
        if (data?.approval_status === "approved") {
          router.push("/onboarding");
        } else if (data?.approval_status === "rejected") {
          router.push("/auth/rejected");
        }
      }
    }, 10000);

    return () => clearInterval(interval);
  }, [router]);

  async function handleSignOut() {
    const supabase = createSupabaseBrowserClient();
    await supabase.auth.signOut();
    router.push("/auth/login");
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full bg-white rounded-xl shadow-sm border p-8 text-center">
        <div className="w-16 h-16 bg-yellow-100 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg className="w-8 h-8 text-yellow-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h1 className="text-xl font-bold mb-2">Pending Approval</h1>
        <p className="text-gray-500 mb-4">
          Your account ({email}) is waiting for admin approval.
          You&apos;ll be redirected automatically once approved.
        </p>
        <p className="text-sm text-gray-400 mb-6">
          This page checks for approval every 10 seconds.
        </p>
        <button
          onClick={handleSignOut}
          className="text-sm text-gray-500 hover:text-gray-700 underline"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
