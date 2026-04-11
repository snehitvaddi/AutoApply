/**
 * Public activation endpoint.
 *
 * POST /api/activate { code, install_id?, app_version? }
 *
 * Validates an activation code (created by an admin in /admin), generates a fresh
 * worker token for the associated user, and returns it along with the user's
 * profile + preferences so the ApplyLoop desktop app can hydrate itself in one call.
 *
 * NOT authenticated — gated by possession of the activation code. Uses the service
 * role key to bypass RLS since the code itself IS the auth factor.
 *
 * Error responses use apiError("validation_error", message, { code: "<short>" }) so
 * the desktop can key off { details.code } for specific remediation messages:
 *   - not_found:     code doesn't exist
 *   - expired:       code past expires_at
 *   - used_up:       uses_remaining <= 0
 *   - not_approved:  the target user is not in approval_status='approved'
 */
import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";
import crypto from "crypto";
import { apiSuccess, apiError } from "@/lib/api-response";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

// IP-scoped rate limiter. Protects against brute-force sweeps of the 32^8
// activation-code alphabet. In-process Map means it's per-lambda-container,
// so a sufficiently distributed attacker could still make progress — but it
// blocks single-container sprays and buys us time. For stronger guarantees
// we'd need a shared backend (Upstash Redis / Vercel KV).
const RATE_WINDOW_MS = 60_000;
const RATE_MAX = 10;
type RateRecord = { count: number; resetAt: number };
const ipRateMap: Map<string, RateRecord> = new Map();

function clientIp(request: NextRequest): string {
  const fwd = request.headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0].trim();
  return request.headers.get("x-real-ip") || "unknown";
}

function checkIpRateLimit(ip: string): boolean {
  const now = Date.now();
  const rec = ipRateMap.get(ip);
  if (!rec || rec.resetAt < now) {
    ipRateMap.set(ip, { count: 1, resetAt: now + RATE_WINDOW_MS });
    return true;
  }
  if (rec.count >= RATE_MAX) return false;
  rec.count += 1;
  return true;
}

function hashToken(token: string): string {
  return crypto.createHash("sha256").update(token).digest("hex");
}

function generateWorkerToken(): string {
  const prefix = "al";
  const mid = crypto.randomUUID().replace(/-/g, "").slice(0, 8);
  const secret = crypto.randomBytes(16).toString("hex");
  return `${prefix}_${mid}_${secret}`;
}

export async function POST(request: NextRequest) {
  // IP-based rate limit — runs before any DB work so a brute-forcer can't
  // exhaust Supabase quota even if they somehow bypass the alphabet entropy.
  const ip = clientIp(request);
  if (!checkIpRateLimit(ip)) {
    return apiError(
      "rate_limit_exceeded",
      "Too many activation attempts. Wait a minute and try again."
    );
  }

  const body = await request.json().catch(() => ({}));
  const rawCode: string = (body.code || "").toString().trim().toUpperCase();
  const install_id: string | null = body.install_id ? String(body.install_id) : null;
  const app_version: string | null = body.app_version ? String(body.app_version) : null;

  if (!rawCode) {
    return apiError("validation_error", "Activation code is required", {
      code: "not_found",
    });
  }

  // 1) Look up the code (read-only — expiry + user lookup only; decrement is atomic below).
  const { data: codeRow, error: codeErr } = await supabase
    .from("activation_codes")
    .select("code, user_id, expires_at, uses_remaining, last_used_at")
    .eq("code", rawCode)
    .single();

  if (codeErr || !codeRow) {
    return apiError("validation_error", "Invalid activation code", {
      code: "not_found",
    });
  }

  // 2) Check expiry.
  const now = new Date();
  const expiresAt = new Date(codeRow.expires_at);
  if (expiresAt.getTime() < now.getTime()) {
    return apiError("validation_error", "This activation code has expired", {
      code: "expired",
      expires_at: codeRow.expires_at,
    });
  }

  // 3) Fast-path sanity check on uses_remaining (the authoritative check is the
  // atomic UPDATE below — this just short-circuits obviously dead codes without
  // touching the user row).
  if (!codeRow.uses_remaining || codeRow.uses_remaining <= 0) {
    return apiError("validation_error", "This activation code has been used up", {
      code: "used_up",
    });
  }

  // 4) Check the target user is approved.
  const { data: userRow, error: userErr } = await supabase
    .from("users")
    .select(
      "id, email, full_name, tier, daily_apply_limit, telegram_chat_id, approval_status"
    )
    .eq("id", codeRow.user_id)
    .single();

  if (userErr || !userRow) {
    return apiError("validation_error", "User not found", {
      code: "not_found",
    });
  }
  if (userRow.approval_status !== "approved") {
    return apiError("validation_error", "Your account is not approved yet", {
      code: "not_approved",
      approval_status: userRow.approval_status,
    });
  }

  // 5) ATOMIC decrement — the authoritative race-safe redemption step. This
  // replaces the old read-modify-write pattern that let 5 parallel requests all
  // observe uses_remaining=1 and all proceed to mint tokens. By filtering on
  // `uses_remaining > 0` and using PostgREST's returning=representation, exactly
  // one concurrent caller will get a row back for a 1-use code. Everyone else
  // sees an empty result and is rejected as used_up.
  //
  // The activation_codes.uses_remaining CHECK (uses_remaining >= 0) constraint
  // in migration 009 provides a belt-and-suspenders guarantee at the DB level.
  const { data: decremented, error: decErr } = await supabase
    .from("activation_codes")
    .update({
      uses_remaining: codeRow.uses_remaining - 1,
      last_used_at: now.toISOString(),
    })
    .eq("code", codeRow.code)
    .eq("uses_remaining", codeRow.uses_remaining) // compare-and-swap against the value we just read
    .select("code, uses_remaining")
    .maybeSingle();

  if (decErr) {
    return apiError("internal_server_error", decErr.message);
  }
  if (!decremented) {
    // Another concurrent request redeemed this use before we could. Re-check:
    // if uses_remaining is still > 0, it's a CAS collision; if it's 0, it's
    // genuinely used up. Either way the user-facing answer is the same.
    return apiError("validation_error", "This activation code has been used up", {
      code: "used_up",
    });
  }

  const remainingUsesAfterRedemption = (decremented as { uses_remaining: number }).uses_remaining;

  // 6) Only AFTER we successfully hold a redemption do we mint a new worker token.
  // Any failure here does NOT re-increment the code — the user can request a new
  // one from the admin. This is the safe direction (no free extra redemptions).
  const workerToken = generateWorkerToken();
  const tokenHash = hashToken(workerToken);

  // Replace any existing tokens for this user (same pattern as /api/admin/worker-token).
  await supabase.from("worker_tokens").delete().eq("user_id", userRow.id);

  const { error: insertErr } = await supabase.from("worker_tokens").insert({
    user_id: userRow.id,
    token_hash: tokenHash,
  });
  if (insertErr) {
    return apiError("internal_server_error", insertErr.message);
  }

  // 7) Load profile + preferences + default resume metadata in parallel so the
  // desktop can hydrate everything from one round trip.
  const [profileRes, prefsRes, resumesRes] = await Promise.all([
    supabase.from("user_profiles").select("*").eq("user_id", userRow.id).single(),
    supabase
      .from("user_job_preferences")
      .select("*")
      .eq("user_id", userRow.id)
      .single(),
    supabase.from("user_resumes").select("file_name, is_default, target_keywords").eq(
      "user_id",
      userRow.id
    ),
  ]);

  const resumes = resumesRes.data || [];
  const defaultResume =
    resumes.find((r) => (r as { is_default?: boolean }).is_default) || resumes[0] || null;

  // Synthesis fallback: if the DB profile has empty work_experience/education
  // arrays but has the flat fields (current_company, current_title,
  // school_name, degree, graduation_year), build minimal array entries from
  // them before serializing. This keeps /api/activate in sync with
  // /api/settings/cli-config so installers don't have to hit both endpoints
  // to get the richer shape, and keeps the shipping profile.json useful even
  // when the onboarding flow only captured the flat fields.
  const profileRow = profileRes.data
    ? ({ ...(profileRes.data as Record<string, unknown>) })
    : null;
  if (profileRow) {
    const wx = profileRow.work_experience;
    const hasFlatWork =
      typeof profileRow.current_company === "string" && profileRow.current_company.length > 0;
    if ((!Array.isArray(wx) || wx.length === 0) && hasFlatWork) {
      profileRow.work_experience = [{
        company: profileRow.current_company || "",
        title: profileRow.current_title || "",
        location: "",
        start_date: "",
        end_date: "Present",
        current: true,
        achievements: [],
      }];
    }
    const ed = profileRow.education;
    const hasFlatEd =
      typeof profileRow.school_name === "string" && profileRow.school_name.length > 0;
    if ((!Array.isArray(ed) || ed.length === 0) && hasFlatEd) {
      profileRow.education = [{
        school: profileRow.school_name || "",
        degree: profileRow.degree || "",
        field: "",
        start_date: "",
        end_date: profileRow.graduation_year ? String(profileRow.graduation_year) : "",
        gpa: "",
      }];
    }
  }

  // 8) Optional: log the install_id + app_version for admin visibility (best effort).
  if (install_id || app_version) {
    try {
      await supabase.from("activation_codes").update({
        notes: `Last install: ${install_id || "?"} (app ${app_version || "?"}) at ${now.toISOString()}`,
      }).eq("code", codeRow.code);
    } catch {
      /* ignore */
    }
  }

  return apiSuccess({
    worker_token: workerToken,
    user_id: userRow.id,
    email: userRow.email,
    full_name: (userRow as { full_name?: string }).full_name || null,
    tier: userRow.tier,
    daily_apply_limit: userRow.daily_apply_limit,
    telegram_chat_id: userRow.telegram_chat_id,
    profile: profileRow || null,
    preferences: prefsRes.data || null,
    default_resume: defaultResume,
    remaining_uses_after_this_redemption: remainingUsesAfterRedemption,
  });
}
