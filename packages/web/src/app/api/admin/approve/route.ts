import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiSuccess, apiError } from "@/lib/api-response";
import { isAdmin } from "@/lib/admin";
import crypto from "crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

const GITHUB_TOKEN = process.env.GITHUB_PERSONAL_TOKEN || "";
const GITHUB_REPO = "snehitvaddi/AutoApply";

async function addGitHubCollaborator(githubUsername: string): Promise<boolean> {
  if (!GITHUB_TOKEN || !githubUsername) return false;
  try {
    const resp = await fetch(
      `https://api.github.com/repos/${GITHUB_REPO}/collaborators/${githubUsername}`,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
        },
        body: JSON.stringify({ permission: "pull" }), // read-only
      }
    );
    return resp.status === 201 || resp.status === 204;
  } catch {
    return false;
  }
}

function extractGitHubUsername(url: string): string {
  if (!url) return "";
  // Handle: https://github.com/username, github.com/username, @username
  const match = url.match(/github\.com\/([a-zA-Z0-9_-]+)/);
  if (match) return match[1];
  if (url.startsWith("@")) return url.slice(1);
  return url.trim();
}

function generateWorkerToken(userId: string): { token: string; hash: string } {
  const prefix = userId.slice(0, 8);
  const random = crypto.randomBytes(16).toString("hex");
  const token = `al_${prefix}_${random}`;
  const hash = crypto.createHash("sha256").update(token).digest("hex");
  return { token, hash };
}

export async function POST(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");
  if (!(await isAdmin(auth.userId))) return apiError("forbidden");

  const { user_id, action } = await request.json();

  if (!user_id || !["approve", "reject"].includes(action)) {
    return apiError("validation_error", "user_id and action (approve|reject) required");
  }

  const status = action === "approve" ? "approved" : "rejected";

  const { error } = await supabase
    .from("users")
    .update({
      approval_status: status,
      approved_at: new Date().toISOString(),
      approved_by: auth.userId,
    })
    .eq("id", user_id);

  if (error) {
    return apiError("internal_server_error", error.message);
  }

  const result: Record<string, unknown> = { user_id, approval_status: status };

  // On approval: auto-add GitHub collaborator + auto-generate worker token
  if (action === "approve") {
    // 1. Get user's GitHub URL from profile
    const { data: profile } = await supabase
      .from("user_profiles")
      .select("github_url")
      .eq("user_id", user_id)
      .single();

    if (profile?.github_url) {
      const username = extractGitHubUsername(profile.github_url);
      if (username) {
        const added = await addGitHubCollaborator(username);
        result.github_collaborator = added ? username : null;
        result.github_invite_sent = added;
      }
    }

    // 2. Auto-generate worker token
    const { token, hash } = generateWorkerToken(user_id);
    await supabase
      .from("worker_tokens")
      .upsert({ user_id, token_hash: hash, revoked_at: null }, { onConflict: "user_id" });
    result.worker_token = token;
  }

  return apiSuccess(result);
}
