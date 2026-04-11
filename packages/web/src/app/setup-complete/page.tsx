"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SETUP_CHECKSUMS } from "@/generated/setup-checksums";

type ActivationCode = {
  code: string;
  expires_at: string;
  uses_remaining: number;
  created_at: string;
} | null;

const APP_URL = "https://applyloop.vercel.app";
const MAC_SCRIPT_URL = `${APP_URL}/setup/ApplyLoop-Setup-Mac.sh`;
const WIN_SCRIPT_URL = `${APP_URL}/setup/ApplyLoop-Setup-Windows.ps1`;
const WIN_BAT_URL = `${APP_URL}/setup/ApplyLoop.bat`;

/**
 * Build the recommended Mac install snippet: download, verify SHA256, then run.
 * This intentionally does NOT use `curl ... | bash`: piping makes the script
 * impossible for the user to inspect or checksum before executing. Instead we
 * write it to a temp file, verify it matches the SHA256 we publish here, and
 * only then execute it. The embedded hash is regenerated from the actual
 * public/setup/ file on every Vercel build via the prebuild step, so it is
 * always in sync with what the URL serves.
 */
function buildMacCommand(sha256: string, activationCode: string): string {
  // Use activation code inline if known; otherwise leave a placeholder the
  // user must replace. We still wrap it in quotes so weird chars can't break
  // the shell.
  const codeArg = activationCode || "YOUR_ACTIVATION_CODE";
  return [
    `curl -fsSL ${MAC_SCRIPT_URL} -o /tmp/applyloop-setup.sh && \\`,
    `  echo "${sha256}  /tmp/applyloop-setup.sh" | shasum -a 256 -c - && \\`,
    `  bash /tmp/applyloop-setup.sh "${codeArg}"`,
  ].join("\n");
}

function buildWindowsCommand(sha256: string, activationCode: string): string {
  const codeArg = activationCode || "YOUR_ACTIVATION_CODE";
  return [
    `$u = "${WIN_SCRIPT_URL}"`,
    `$f = "$env:TEMP\\ApplyLoop-Setup.ps1"`,
    `Invoke-WebRequest $u -OutFile $f`,
    `if ((Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne "${sha256}") {`,
    `  Write-Error "Setup script hash mismatch — refusing to run"; exit 1 }`,
    `PowerShell -ExecutionPolicy Bypass -File $f "${codeArg}"`,
  ].join("\n");
}

export default function SetupCompletePage() {
  const router = useRouter();
  const [os, setOs] = useState<"mac" | "windows" | "unknown">("unknown");
  const [activation, setActivation] = useState<ActivationCode>(null);
  const [activationLoading, setActivationLoading] = useState(true);
  const [activationError, setActivationError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const platform = navigator.platform.toLowerCase();
    if (platform.includes("mac")) setOs("mac");
    else if (platform.includes("win")) setOs("windows");
  }, []);

  // Fetch the authenticated user's current activation code so we can render
  // it inline. Falls back to a "contact admin" path if there isn't one yet.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/me/activation-code", { cache: "no-store" });
        if (!r.ok) {
          if (!cancelled) setActivationError("Could not load activation code");
          return;
        }
        const body = await r.json();
        if (!cancelled) setActivation(body.data || null);
      } catch {
        if (!cancelled) setActivationError("Could not load activation code");
      } finally {
        if (!cancelled) setActivationLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function copy(label: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard may be unavailable */
    }
  }

  const code = activation?.code || "";
  const macCmd = buildMacCommand(SETUP_CHECKSUMS.mac.sha256, code);
  const winCmd = buildWindowsCommand(SETUP_CHECKSUMS.windowsPs1.sha256, code);

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
            Your profile is saved and ready. Next, install the ApplyLoop worker on your machine.
          </p>
        </div>

        {/* Activation code */}
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 mb-6">
          <h3 className="font-semibold text-indigo-900 mb-2">Your activation code</h3>
          {activationLoading ? (
            <p className="text-sm text-indigo-700">Loading...</p>
          ) : activation ? (
            <>
              <div className="flex items-center gap-2">
                <code className="flex-1 bg-white border border-indigo-300 rounded-lg px-4 py-2 text-lg font-mono font-bold text-indigo-900 tracking-wider select-all">
                  {activation.code}
                </code>
                <button
                  onClick={() => copy("code", activation.code)}
                  className="px-3 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
                >
                  {copied === "code" ? "Copied" : "Copy"}
                </button>
              </div>
              <p className="text-xs text-indigo-700 mt-2">
                Paste this into the installer when prompted. Expires{" "}
                {new Date(activation.expires_at).toLocaleString()}. Uses remaining:{" "}
                {activation.uses_remaining}.
              </p>
            </>
          ) : (
            <div className="text-sm text-indigo-800">
              <p className="mb-2">
                No active activation code found on your account yet.
              </p>
              <p className="text-xs">
                Ask the admin to generate one for you (or DM{" "}
                <a
                  href="https://t.me/ApplyLoopBot"
                  target="_blank"
                  rel="noopener"
                  className="underline font-medium"
                >
                  @ApplyLoopBot
                </a>
                ). If you just completed onboarding, your code should appear here
                once the admin approves your request.
              </p>
              {activationError && (
                <p className="text-xs text-red-600 mt-2">{activationError}</p>
              )}
            </div>
          )}
        </div>

        {/* Learning note */}
        <div className="bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-200 rounded-lg p-4 mb-4">
          <p className="text-sm text-purple-800">
            <span className="font-semibold">Your bot learns as you use it.</span>{" "}
            The more you interact — correcting roles, skipping companies, giving feedback — the smarter it gets.
            By day 3, it runs almost fully on autopilot. Early interactions shape its accuracy, so don&apos;t hold back.
          </p>
        </div>

        {/* What happens next */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-8">
          <h3 className="font-semibold text-blue-900 mb-2">What happens next?</h3>
          <ol className="text-sm text-blue-800 space-y-1 list-decimal list-inside">
            <li>Run the installer for your OS (commands below)</li>
            <li>Paste your activation code when prompted</li>
            <li>The installer pulls Python, Node.js, OpenClaw, and dependencies</li>
            <li>The worker connects to your ApplyLoop account and starts applying</li>
          </ol>
        </div>

        {/* Download section */}
        <div className="space-y-4 mb-8">
          <h2 className="text-lg font-semibold">Install the worker</h2>
          <p className="text-xs text-gray-500">
            The commands below download the installer to a temp file, verify its
            SHA256 hash against the one shown below, and only then execute it —
            so a compromised CDN or DNS response cannot silently swap the
            script. Do <strong>not</strong> paste raw <code>curl | bash</code>{" "}
            snippets from anywhere else.
          </p>

          {/* macOS */}
          <div
            className={`border rounded-lg p-4 ${
              os === "mac" ? "border-brand-500 bg-brand-50" : "border-gray-200"
            }`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="text-2xl">&#63743;</div>
                <div>
                  <p className="font-medium">macOS</p>
                  <p className="text-sm text-gray-500">
                    Paste in Terminal (verifies SHA256 before running)
                  </p>
                </div>
                {os === "mac" && (
                  <span className="px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full">
                    Detected
                  </span>
                )}
              </div>
              <button
                onClick={() => copy("mac", macCmd)}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                {copied === "mac" ? "Copied" : "Copy Command"}
              </button>
            </div>
            <pre className="bg-gray-900 text-green-400 text-xs rounded-lg p-3 overflow-x-auto whitespace-pre">
{macCmd}
            </pre>
            <p className="text-[11px] text-gray-500 mt-2 font-mono break-all">
              SHA256: {SETUP_CHECKSUMS.mac.sha256 || "(unavailable)"}
            </p>
          </div>

          {/* Windows */}
          <div
            className={`border rounded-lg p-4 ${
              os === "windows" ? "border-brand-500 bg-brand-50" : "border-gray-200"
            }`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="text-2xl">&#9783;</div>
                <div>
                  <p className="font-medium">Windows</p>
                  <p className="text-sm text-gray-500">
                    Paste in PowerShell (Admin) — verifies SHA256 before running
                  </p>
                </div>
                {os === "windows" && (
                  <span className="px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full">
                    Detected
                  </span>
                )}
              </div>
              <button
                onClick={() => copy("win", winCmd)}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                {copied === "win" ? "Copied" : "Copy Command"}
              </button>
            </div>
            <pre className="bg-gray-900 text-green-400 text-xs rounded-lg p-3 overflow-x-auto whitespace-pre">
{winCmd}
            </pre>
            <p className="text-[11px] text-gray-500 mt-2 font-mono break-all">
              SHA256: {SETUP_CHECKSUMS.windowsPs1.sha256 || "(unavailable)"}
            </p>
            <p className="text-xs text-gray-500 mt-3">
              Prefer a double-click installer? Download{" "}
              <a href={WIN_BAT_URL} download="ApplyLoop.bat" className="underline text-brand-700">
                ApplyLoop.bat
              </a>{" "}
              and right-click &rarr; <em>Run as administrator</em>. SHA256:{" "}
              <span className="font-mono">{SETUP_CHECKSUMS.windowsBat.sha256 || "(unavailable)"}</span>
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
            <li>Paste in <strong>Settings &rarr; Telegram</strong></li>
          </ol>
        </div>

        {/* After setup */}
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
          <h3 className="font-semibold text-green-900 mb-2">After setup — daily start</h3>
          <p className="text-sm text-green-800">
            <strong>Windows:</strong> Double-click <code>ApplyLoop.bat</code> on your Desktop.<br />
            <strong>Mac:</strong> Open Terminal &rarr; run{" "}
            <code>cd ~/ApplyLoop &amp;&amp; claude --dangerously-skip-permissions &quot;Read AGENTS.md. Start.&quot;</code>
          </p>
          <p className="text-xs text-green-700 mt-2">
            Each launch auto-pulls the latest updates from the admin.
          </p>
        </div>

        {/* Requirements note */}
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-8">
          <h3 className="font-semibold text-yellow-900 mb-2">Requirements</h3>
          <ul className="text-sm text-yellow-800 space-y-1">
            <li>
              &bull; <strong>OpenClaw Pro</strong> ($20/mo) — browser automation engine.{" "}
              <a href="https://openclaw.com/pricing" target="_blank" rel="noopener" className="underline">
                Sign up here
              </a>
            </li>
            <li>
              &bull; <strong>Activation code</strong> — shown above (generated by the admin after approval)
            </li>
            <li>
              &bull; The installer pulls everything else automatically (Python, Node.js, Playwright, etc.)
            </li>
          </ul>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <button
            onClick={() => router.push("/dashboard")}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Skip &mdash; go to dashboard
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
