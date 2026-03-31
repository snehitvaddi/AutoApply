import { NextResponse } from "next/server";
import packageJson from "../../../../../package.json";

export async function GET() {
  return NextResponse.json({
    version: packageJson.version,
    latest_commit: process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 7) ?? "unknown",
    changes: [
      "Hybrid LLM approach (Claude + GPT + Gemini fallback)",
      "Multi-resume support with role tags",
      "AgentMail disposable inbox integration",
      "Himalaya CLI for Gmail reading",
      "Greenhouse, Ashby, Workday ATS support",
    ],
    migration_needed: false,
    released_at: process.env.VERCEL_GIT_COMMIT_SHA
      ? new Date().toISOString()
      : "unknown",
  });
}
