"use client";

import { useEffect, useState } from "react";

type ActivationCode = {
  code: string;
  expires_at: string;
  uses_remaining: number;
  created_at: string;
} | null;

// Distribution point for the macOS desktop build. GitHub Releases is the CDN.
// The page auto-syncs with whichever release is tagged "latest" on GitHub.
const FALLBACK_TAG = "v1.0.4";
const FALLBACK_DMG = "ApplyLoop-1.0.4.dmg";
const GH_LATEST_API =
  "https://api.github.com/repos/snehitvaddi/AutoApply/releases/latest";
const releaseBase = (tag: string) =>
  `https://github.com/snehitvaddi/AutoApply/releases/download/${tag}`;

/**
 * SetupCard
 *
 * The reusable body of the Setup page — activation code display, macOS
 * install command with pre-baked code, learning-note banner, and Telegram
 * recommendation. Used in two places:
 *
 *   1. `/setup-complete` (top-level, post-signup) — full-bleed centered
 *      landing page. Renders with `variant="standalone"` which adds the
 *      "Profile Setup Complete!" success header + "Go to Dashboard" footer.
 *
 *   2. `/dashboard/setup` (in-dashboard, returning users) — sits inside
 *      the DashboardLayout chrome (sidebar visible). Renders with
 *      `variant="inline"` which drops the success header and the footer
 *      navigation buttons since the user is already in the dashboard.
 *
 * Both variants share ALL the actual setup logic (GitHub release fetch,
 * activation code fetch, copy handlers, install command template) so
 * fixing a bug or updating copy in one place propagates everywhere.
 */
export function SetupCard({ variant = "inline" }: { variant?: "standalone" | "inline" }) {
  const [os, setOs] = useState<"mac" | "windows" | "unknown">("unknown");
  const [activation, setActivation] = useState<ActivationCode>(null);
  const [activationLoading, setActivationLoading] = useState(true);
  const [activationError, setActivationError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [releaseTag, setReleaseTag] = useState<string>(FALLBACK_TAG);
  const [dmgName, setDmgName] = useState<string>(FALLBACK_DMG);

  useEffect(() => {
    const platform = navigator.platform.toLowerCase();
    if (platform.includes("mac")) setOs("mac");
    else if (platform.includes("win")) setOs("windows");
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(GH_LATEST_API, { cache: "no-store" });
        if (!r.ok) return;
        const body = await r.json();
        const tag: string | undefined = body?.tag_name;
        type GhAsset = { name: string; browser_download_url: string };
        const assets: GhAsset[] = Array.isArray(body?.assets) ? body.assets : [];
        const dmg = assets.find((a) => a.name?.endsWith(".dmg"));
        if (cancelled || !tag || !dmg) return;
        setReleaseTag(tag);
        setDmgName(dmg.name);
      } catch {
        /* best-effort — page still works with fallback values */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const dmgUrl = `${releaseBase(releaseTag)}/${dmgName}`;

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

  // install.sh v1.0.9+ requires the activation code up front
  const userCode = activation?.code || "AL-XXXX-XXXX";
  const installCmd =
    `curl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh | bash -s -- ${userCode}`;

  return (
    <div className="space-y-6">
      {variant === "standalone" && (
        <div className="text-center mb-2">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg
              className="w-8 h-8 text-green-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-gray-900">Profile Setup Complete!</h2>
          <p className="text-gray-500 mt-2">
            Your profile is saved. Install the ApplyLoop desktop app to start applying.
          </p>
        </div>
      )}

      {/* Activation code */}
      <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
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
              Paste this into the desktop app when it prompts you. Expires{" "}
              {new Date(activation.expires_at).toLocaleString()}. Uses remaining:{" "}
              {activation.uses_remaining}.
            </p>
          </>
        ) : (
          <div className="text-sm text-indigo-800">
            <p className="mb-2">No active activation code found on your account yet.</p>
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
              ). If you just completed onboarding, your code should appear here once the
              admin approves your request.
            </p>
            {activationError && (
              <p className="text-xs text-red-600 mt-2">{activationError}</p>
            )}
          </div>
        )}
      </div>

      {/* Download ApplyLoop.app */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Install ApplyLoop</h2>

        {/* macOS */}
        <div
          className={`border rounded-lg p-5 ${
            os === "mac" ? "border-brand-500 bg-brand-50" : "border-gray-200"
          }`}
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="text-3xl">&#63743;</div>
            <div className="flex-1">
              <p className="font-semibold">macOS Install</p>
              <p className="text-sm text-gray-500">Intel and Apple Silicon</p>
            </div>
            {os === "mac" && (
              <span className="px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full">
                Detected
              </span>
            )}
          </div>

          <p className="text-sm text-gray-700 mb-2">
            Open Terminal and paste this — your activation code is already baked in:
          </p>
          <div className="flex items-center gap-2 mb-4">
            <code className="flex-1 bg-gray-900 text-green-400 border border-gray-800 rounded-lg px-4 py-2 text-xs font-mono overflow-x-auto whitespace-nowrap select-all">
              {installCmd}
            </code>
            <button
              onClick={() => copy("install", installCmd)}
              className="px-3 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
            >
              {copied === "install" ? "Copied" : "Copy"}
            </button>
          </div>

          <p className="text-sm text-gray-700 mb-2">The installer will:</p>
          <ul className="text-sm text-gray-700 space-y-1 list-disc list-inside mb-4">
            <li>
              Verify your activation code (before touching anything on your machine)
            </li>
            <li>Install Homebrew + Python + Node + Claude + OpenClaw</li>
            <li>
              Clone ApplyLoop to <code className="text-xs">~/.applyloop</code> and build
              the UI locally
            </li>
            <li>Configure OpenClaw gateway + sync your profile from this account</li>
            <li>
              Prompt for optional integrations (Telegram, Gmail, AgentMail, Finetune
              Resume — Enter to skip any)
            </li>
            <li>
              Generate <code className="text-xs">/Applications/ApplyLoop.app</code> and
              schedule daily auto-updates
            </li>
          </ul>
          <p className="text-sm text-gray-700">
            Double-click <strong>ApplyLoop</strong> in <strong>/Applications</strong> —
            the wizard is already activated, profile is synced, you just click{" "}
            <strong>Start</strong>.
          </p>

          <hr className="my-4 border-gray-200" />

          <div className="text-xs text-gray-500">
            <p className="font-medium text-gray-600 mb-1">Advanced</p>
            <p>
              Prefer the .dmg?{" "}
              <a
                href={dmgUrl}
                download={dmgName}
                className="underline text-gray-600 hover:text-gray-800"
              >
                Download {releaseTag}
              </a>{" "}
              <span className="text-gray-400">
                (deprecated — known Gatekeeper issues, use the install script instead)
              </span>
            </p>
          </div>
        </div>

        {/* Windows — coming soon */}
        <div
          className={`border rounded-lg p-5 ${
            os === "windows"
              ? "border-brand-500 bg-brand-50"
              : "border-gray-200 opacity-70"
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="text-3xl">&#9783;</div>
              <div>
                <p className="font-semibold">Windows</p>
                <p className="text-sm text-gray-500">Installer build in progress</p>
              </div>
              {os === "windows" && (
                <span className="px-2 py-0.5 bg-yellow-100 text-yellow-800 text-xs rounded-full">
                  Detected
                </span>
              )}
            </div>
            <span className="px-4 py-2 bg-gray-200 text-gray-600 rounded-lg text-sm font-medium">
              Coming soon
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-3">
            Windows users: in the meantime, ping{" "}
            <a
              href="https://t.me/ApplyLoopBot"
              target="_blank"
              rel="noopener"
              className="underline"
            >
              @ApplyLoopBot
            </a>{" "}
            and we&apos;ll set you up manually with a worker token.
          </p>
        </div>
      </div>

      {/* Learning note */}
      <div className="bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-200 rounded-lg p-4">
        <p className="text-sm text-purple-800">
          <span className="font-semibold">Your bot learns as you use it.</span> The more
          you interact — correcting roles, skipping companies, giving feedback — the
          smarter it gets. By day 3, it runs almost fully on autopilot. Early
          interactions shape its accuracy, so don&apos;t hold back.
        </p>
      </div>

      {/* Telegram */}
      <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
        <h3 className="font-semibold text-purple-900 mb-2">
          Enable Telegram notifications (recommended)
        </h3>
        <p className="text-sm text-purple-800 mb-2">
          Get screenshot proof for every application submitted — and chat with your bot
          directly from your phone.
        </p>
        <ol className="text-sm text-purple-800 space-y-1 list-decimal list-inside">
          <li>
            Open{" "}
            <a
              href="https://t.me/ApplyLoopBot"
              target="_blank"
              rel="noopener"
              className="underline font-medium"
            >
              t.me/ApplyLoopBot
            </a>{" "}
            in Telegram
          </li>
          <li>
            Send <span className="font-mono">/start</span>
          </li>
          <li>
            Copy the <strong>Chat ID</strong>
          </li>
          <li>
            Paste in <strong>Settings → Telegram</strong>
          </li>
        </ol>
      </div>
    </div>
  );
}
