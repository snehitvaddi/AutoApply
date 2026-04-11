/**
 * GET /api/updates/check
 *
 * Lightweight version manifest consumed by the desktop app's auto-update
 * pinger. Must never throw on missing env vars — if Vercel metadata is
 * absent (local dev, preview build outside Vercel), we return sensible
 * defaults so the desktop doesn't panic.
 *
 * Response shape (stable — desktop unmarshals this):
 *   {
 *     version:         semver from packages/web/package.json
 *     latest_commit:   7-char git SHA of this deploy, or "unknown"
 *     commit_message:  commit message of latest deploy, or null
 *     changes:         string[] — human-readable changelog (from env var)
 *     migration_needed:false — reserved for future force-migration flag
 *     released_at:     ISO8601 of deploy time (Vercel build time), or null
 *     checked_at:      ISO8601 of this request time
 *   }
 */
import { NextResponse } from "next/server";
import packageJson from "../../../../../package.json";

export const dynamic = "force-dynamic";

function parseChanges(raw: string | undefined): string[] {
  if (!raw) return [];
  // Allow either JSON array or pipe-separated single line (Vercel env vars
  // don't always survive JSON escaping cleanly).
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.map((s) => String(s));
  } catch {
    /* fall through to pipe split */
  }
  return raw
    .split("|")
    .map((s) => s.trim())
    .filter(Boolean);
}

export async function GET() {
  const sha = process.env.VERCEL_GIT_COMMIT_SHA || "";
  const commitMessage = process.env.VERCEL_GIT_COMMIT_MESSAGE || null;
  // Prefer the explicit Vercel deployment timestamp if present; otherwise null.
  const releasedAt = process.env.VERCEL_DEPLOYMENT_CREATED_AT || null;

  return NextResponse.json({
    version: packageJson.version,
    latest_commit: sha ? sha.slice(0, 7) : "unknown",
    commit_message: commitMessage,
    changes: parseChanges(process.env.APPLYLOOP_RELEASE_NOTES),
    migration_needed: false,
    released_at: releasedAt,
    checked_at: new Date().toISOString(),
  });
}
