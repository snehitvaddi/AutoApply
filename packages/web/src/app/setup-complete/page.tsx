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

        {/* Learning note */}
        <div className="bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-200 rounded-lg p-4 mb-4">
          <p className="text-sm text-purple-800">
            <span className="font-semibold">🧠 Your bot learns as you use it.</span>{" "}
            The more you interact — correcting roles, skipping companies, giving feedback — the smarter it gets.
            By day 3, it runs almost fully on autopilot. Early interactions shape its accuracy, so don&apos;t hold back.
          </p>
        </div>

        {/* What happens next */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-8">
          <h3 className="font-semibold text-blue-900 mb-2">What happens next?</h3>
          <ol className="text-sm text-blue-800 space-y-1 list-decimal list-inside">
            <li>Download and run the setup script for your OS</li>
            <li>The script installs Python, Node.js, OpenClaw, and all dependencies</li>
            <li>It connects to your ApplyLoop account via your worker token</li>
            <li>The worker starts scanning job boards and auto-applying</li>
          </ol>
        </div>

        {/* Download section */}
        <div className="space-y-4 mb-8">
          <h2 className="text-lg font-semibold">Download Setup Script</h2>

          {/* macOS */}
          <div className={`border rounded-lg p-4 ${
            os === "mac" ? "border-brand-500 bg-brand-50" : "border-gray-200"
          }`}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="text-2xl">&#63743;</div>
                <div>
                  <p className="font-medium">macOS</p>
                  <p className="text-sm text-gray-500">Paste one command in Terminal</p>
                </div>
                {os === "mac" && (
                  <span className="px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full">Detected</span>
                )}
              </div>
              <button
                onClick={() => {
                  navigator.clipboard.writeText("curl -fsSL https://applyloop.vercel.app/setup/ApplyLoop-Setup-Mac.sh | bash -s -- YOUR_TOKEN_HERE");
                }}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                Copy Command
              </button>
            </div>
            <pre className="bg-gray-900 text-green-400 text-sm rounded-lg p-3 overflow-x-auto">
{`curl -fsSL https://applyloop.vercel.app/setup/ApplyLoop-Setup-Mac.sh | bash -s -- YOUR_TOKEN_HERE`}
            </pre>
            <p className="text-xs text-gray-500 mt-2">
              Replace <code className="bg-gray-800 px-1 rounded text-yellow-300">YOUR_TOKEN_HERE</code> with the worker token from admin. Open Terminal → paste → Enter.
            </p>
          </div>

          {/* Windows */}
          <div className={`border rounded-lg p-4 ${
            os === "windows" ? "border-brand-500 bg-brand-50" : "border-gray-200"
          }`}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="text-2xl">&#9783;</div>
                <div>
                  <p className="font-medium">Windows</p>
                  <p className="text-sm text-gray-500">Download and double-click</p>
                </div>
                {os === "windows" && (
                  <span className="px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full">Detected</span>
                )}
              </div>
              <a
                href="/setup/ApplyLoop.bat"
                download="ApplyLoop.bat"
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                Download ApplyLoop.bat
              </a>
            </div>
            <p className="text-xs text-gray-500">
              Right-click → <em>Run as administrator</em>. It will ask for your worker token first.
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Or paste in PowerShell (Admin) with your token:
            </p>
            <pre className="bg-gray-900 text-green-400 text-xs rounded-lg p-2 mt-1 overflow-x-auto">
{`irm https://applyloop.vercel.app/setup/ApplyLoop-Setup-Windows.ps1 | iex`}
            </pre>
            <p className="text-xs text-gray-400 mt-1">
              If blocked: paste in PowerShell (Admin): <code className="bg-gray-100 px-1 rounded">irm https://applyloop.vercel.app/setup/ApplyLoop-Setup-Windows.ps1 | iex</code>
            </p>
          </div>
        </div>

        {/* Telegram setup */}
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-8">
          <h3 className="font-semibold text-purple-900 mb-2">Enable Telegram Notifications (Recommended)</h3>
          <p className="text-sm text-purple-800 mb-2">Get screenshot proof for every application submitted.</p>
          <ol className="text-sm text-purple-800 space-y-1 list-decimal list-inside mb-3">
            <li>Open <a href="https://t.me/ApplyLoopBot" target="_blank" rel="noopener" className="underline font-medium">t.me/ApplyLoopBot</a> in Telegram</li>
            <li>Send <span className="font-mono">/start</span></li>
            <li>Copy the <strong>Chat ID</strong></li>
            <li>Paste in <strong>Settings → Telegram</strong></li>
          </ol>
        </div>

        {/* After setup */}
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
          <h3 className="font-semibold text-green-900 mb-2">After setup — daily start</h3>
          <p className="text-sm text-green-800">
            <strong>Windows:</strong> Double-click <code>ApplyLoop.bat</code> on your Desktop.<br/>
            <strong>Mac:</strong> Open Terminal → run <code>cd ~/ApplyLoop && claude --dangerously-skip-permissions &quot;Read AGENTS.md. Start.&quot;</code>
          </p>
          <p className="text-xs text-green-700 mt-2">
            Each launch auto-pulls the latest updates from the admin.
          </p>
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
            <li>• <strong>Worker token</strong> — provided by admin after approval (a single token that connects everything)</li>
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
