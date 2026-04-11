"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type ActivationCode = {
  code: string;
  expires_at: string;
  uses_remaining: number;
  created_at: string;
} | null;

// Distribution point for the macOS desktop build. GitHub Releases is our CDN —
// it's free, unlimited bandwidth, version-tagged, and the repo is public so
// anyone can pull the binary. Security lives in the activation-code pipeline,
// not in hiding the artifact: the app is useless until the user pastes a
// valid AL-XXXX-XXXX that the admin generated for their account.
//
// When cutting a new release, update RELEASE_TAG and DMG_NAME in lockstep.
// The SHA256 is fetched at runtime from the sidecar file on the release, so
// the hash is always in sync without having to edit this file per release.
const RELEASE_TAG = "v1.0.4";
const DMG_NAME = "ApplyLoop-1.0.4.dmg";
const RELEASE_BASE = `https://github.com/snehitvaddi/AutoApply/releases/download/${RELEASE_TAG}`;
const DMG_URL = `${RELEASE_BASE}/${DMG_NAME}`;
const DMG_SHA256_URL = `${RELEASE_BASE}/${DMG_NAME}.sha256`;

export default function SetupCompletePage() {
  const router = useRouter();
  const [os, setOs] = useState<"mac" | "windows" | "unknown">("unknown");
  const [activation, setActivation] = useState<ActivationCode>(null);
  const [activationLoading, setActivationLoading] = useState(true);
  const [activationError, setActivationError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [dmgSha256, setDmgSha256] = useState<string | null>(null);

  useEffect(() => {
    const platform = navigator.platform.toLowerCase();
    if (platform.includes("mac")) setOs("mac");
    else if (platform.includes("win")) setOs("windows");
  }, []);

  // Pull the SHA256 sidecar from the release so the displayed hash is always
  // in sync with whatever binary is currently at DMG_URL.
  useEffect(() => {
    let cancelled = false;
    fetch(DMG_SHA256_URL, { cache: "no-store" })
      .then((r) => (r.ok ? r.text() : null))
      .then((text) => {
        if (cancelled || !text) return;
        // File format is `<hash>  <filename>` per `shasum -a 256` output.
        const hash = text.trim().split(/\s+/)[0];
        if (hash && /^[a-f0-9]{64}$/.test(hash)) setDmgSha256(hash);
      })
      .catch(() => {
        /* best-effort — page still works without the hash */
      });
    return () => {
      cancelled = true;
    };
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

  const verifyCommand = dmgSha256
    ? `shasum -a 256 ~/Downloads/${DMG_NAME}\n# expected: ${dmgSha256}`
    : `shasum -a 256 ~/Downloads/${DMG_NAME}\n# compare against the sha256 shown on the release page`;

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full bg-white rounded-xl shadow-sm border p-8">
        {/* Success header */}
        <div className="text-center mb-8">
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
          <h1 className="text-2xl font-bold text-gray-900">
            Profile Setup Complete!
          </h1>
          <p className="text-gray-500 mt-2">
            Your profile is saved. Install the ApplyLoop desktop app to start
            applying.
          </p>
        </div>

        {/* Activation code */}
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 mb-6">
          <h3 className="font-semibold text-indigo-900 mb-2">
            Your activation code
          </h3>
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
                {new Date(activation.expires_at).toLocaleString()}. Uses
                remaining: {activation.uses_remaining}.
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
                ). If you just completed onboarding, your code should appear
                here once the admin approves your request.
              </p>
              {activationError && (
                <p className="text-xs text-red-600 mt-2">{activationError}</p>
              )}
            </div>
          )}
        </div>

        {/* Download ApplyLoop.app */}
        <div className="space-y-4 mb-8">
          <h2 className="text-lg font-semibold">Install ApplyLoop</h2>

          {/* macOS */}
          <div
            className={`border rounded-lg p-5 ${
              os === "mac"
                ? "border-brand-500 bg-brand-50"
                : "border-gray-200"
            }`}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="text-3xl">&#63743;</div>
                <div>
                  <p className="font-semibold">macOS</p>
                  <p className="text-sm text-gray-500">
                    Intel and Apple Silicon
                  </p>
                </div>
                {os === "mac" && (
                  <span className="px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full">
                    Detected
                  </span>
                )}
              </div>
              <a
                href={DMG_URL}
                download={DMG_NAME}
                className="px-5 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
              >
                Download {RELEASE_TAG}
              </a>
            </div>

            <ol className="text-sm text-gray-700 space-y-1 list-decimal list-inside mb-4">
              <li>
                Click <strong>Download {RELEASE_TAG}</strong> above (~15 MB)
              </li>
              <li>
                Double-click the <code>.dmg</code> and drag{" "}
                <strong>ApplyLoop.app</strong> to <strong>/Applications</strong>
              </li>
              <li>
                First launch: right-click <strong>ApplyLoop.app</strong> →{" "}
                <em>Open</em> (one-time Gatekeeper prompt — we&apos;re not
                Apple-signed yet)
              </li>
              <li>
                Paste your activation code in the setup wizard
              </li>
            </ol>

            <div className="bg-gray-900 text-green-400 text-xs rounded-lg p-3 overflow-x-auto whitespace-pre font-mono">
              {verifyCommand}
            </div>
            <p className="text-[11px] text-gray-500 mt-2 break-all">
              SHA256:{" "}
              <span className="font-mono">
                {dmgSha256 ?? "loading…"}
              </span>{" "}
              <a
                href={DMG_SHA256_URL}
                target="_blank"
                rel="noopener"
                className="underline"
              >
                sidecar
              </a>
            </p>
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
                  <p className="text-sm text-gray-500">
                    Installer build in progress
                  </p>
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
        <div className="bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-200 rounded-lg p-4 mb-6">
          <p className="text-sm text-purple-800">
            <span className="font-semibold">Your bot learns as you use it.</span>{" "}
            The more you interact — correcting roles, skipping companies, giving
            feedback — the smarter it gets. By day 3, it runs almost fully on
            autopilot. Early interactions shape its accuracy, so don&apos;t hold
            back.
          </p>
        </div>

        {/* Telegram */}
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-8">
          <h3 className="font-semibold text-purple-900 mb-2">
            Enable Telegram notifications (recommended)
          </h3>
          <p className="text-sm text-purple-800 mb-2">
            Get screenshot proof for every application submitted — and chat with
            your bot directly from your phone.
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
