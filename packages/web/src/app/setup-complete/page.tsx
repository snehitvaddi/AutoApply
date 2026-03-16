"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function SetupCompletePage() {
  const router = useRouter();
  const [os, setOs] = useState<"mac" | "windows" | "unknown">("unknown");

  useEffect(() => {
    const platform = navigator.platform.toLowerCase();
    if (platform.includes("mac")) setOs("mac");
    else if (platform.includes("win")) setOs("windows");
  }, []);

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full bg-white rounded-xl shadow-sm border p-8">
        {/* Success header */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Profile Setup Complete!</h1>
          <p className="text-gray-500 mt-2">
            Your profile is saved and ready. Next, set up the automation engine on your machine.
          </p>
        </div>

        {/* What happens next */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-8">
          <h3 className="font-semibold text-blue-900 mb-2">What happens next?</h3>
          <ol className="text-sm text-blue-800 space-y-1 list-decimal list-inside">
            <li>Download and run the setup script for your OS</li>
            <li>The script installs Python, Node.js, OpenClaw, and all dependencies</li>
            <li>It connects to your AutoApply account via Supabase</li>
            <li>The worker starts scanning job boards and auto-applying</li>
          </ol>
        </div>

        {/* Download section */}
        <div className="space-y-4 mb-8">
          <h2 className="text-lg font-semibold">Download Setup Script</h2>

          {/* macOS */}
          <div className={`border rounded-lg p-4 flex items-center justify-between ${
            os === "mac" ? "border-brand-500 bg-brand-50" : "border-gray-200"
          }`}>
            <div className="flex items-center gap-3">
              <div className="text-2xl">&#63743;</div>
              <div>
                <p className="font-medium">macOS</p>
                <p className="text-sm text-gray-500">Bash script — requires Homebrew</p>
              </div>
              {os === "mac" && (
                <span className="px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full">
                  Detected
                </span>
              )}
            </div>
            <a
              href="/setup/setup-mac.sh"
              download="setup-mac.sh"
              className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
            >
              Download .sh
            </a>
          </div>

          {/* Windows */}
          <div className={`border rounded-lg p-4 flex items-center justify-between ${
            os === "windows" ? "border-brand-500 bg-brand-50" : "border-gray-200"
          }`}>
            <div className="flex items-center gap-3">
              <div className="text-2xl">&#9783;</div>
              <div>
                <p className="font-medium">Windows</p>
                <p className="text-sm text-gray-500">PowerShell script — requires winget</p>
              </div>
              {os === "windows" && (
                <span className="px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full">
                  Detected
                </span>
              )}
            </div>
            <a
              href="/setup/setup-windows.ps1"
              download="setup-windows.ps1"
              className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
            >
              Download .ps1
            </a>
          </div>
        </div>

        {/* Run instructions */}
        <div className="bg-gray-50 rounded-lg p-4 mb-8">
          <h3 className="font-semibold mb-3">How to run</h3>

          <div className="space-y-4">
            <div>
              <p className="text-sm font-medium text-gray-700 mb-1">macOS / Linux:</p>
              <pre className="bg-gray-900 text-green-400 text-sm rounded-lg p-3 overflow-x-auto">
{`chmod +x setup-mac.sh
./setup-mac.sh`}
              </pre>
            </div>

            <div>
              <p className="text-sm font-medium text-gray-700 mb-1">Windows (PowerShell as Admin):</p>
              <pre className="bg-gray-900 text-green-400 text-sm rounded-lg p-3 overflow-x-auto">
{`Set-ExecutionPolicy Bypass -Scope Process
.\\setup-windows.ps1`}
              </pre>
            </div>
          </div>
        </div>

        {/* Requirements note */}
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-8">
          <h3 className="font-semibold text-yellow-900 mb-2">Requirements</h3>
          <ul className="text-sm text-yellow-800 space-y-1">
            <li>• <strong>OpenClaw Pro</strong> ($20/mo) — browser automation engine.{" "}
              <a href="https://openclaw.com/pricing" target="_blank" rel="noopener" className="underline">
                Sign up here
              </a>
            </li>
            <li>• <strong>Supabase credentials</strong> — provided by admin after approval</li>
            <li>• The script installs everything else automatically (Python, Node.js, Playwright, etc.)</li>
          </ul>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between">
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
