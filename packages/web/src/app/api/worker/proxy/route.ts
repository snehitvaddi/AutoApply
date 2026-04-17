/**
 * Worker Proxy API — All worker DB operations go through here.
 *
 * The worker sends requests with X-Worker-Token header.
 * This API validates the token, then executes the DB operation
 * using the service role key (which the worker never has).
 *
 * Endpoints (via action parameter):
 *   - claim_job: Claim next pending job from queue
 *   - update_queue: Update application queue status
 *   - log_application: Log a submitted/failed application
 *   - heartbeat: Update worker heartbeat
 *   - load_profile: Fetch user profile + resumes
 *   - load_preferences: Fetch user job preferences
 *   - check_daily_limit: Check if user hit daily limit
 *   - upload_screenshot: Store screenshot URL
 *   - enqueue_jobs: Insert discovered jobs + queue entries
 *   - check_company_rate: Check 7-day company application count (max 3)
 */

import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { apiSuccess, apiError } from "@/lib/api-response";
import crypto from "crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

async function authenticateWorker(request: NextRequest): Promise<string | null> {
  const token = request.headers.get("x-worker-token");
  if (!token) return null;

  const hash = crypto.createHash("sha256").update(token).digest("hex");
  const { data } = await supabase
    .from("worker_tokens")
    .select("user_id")
    .eq("token_hash", hash)
    .is("revoked_at", null)
    .single();

  return data?.user_id || null;
}

export async function POST(request: NextRequest) {
  const userId = await authenticateWorker(request);
  if (!userId) return apiError("unauthorized", "Invalid or revoked worker token");

  const body = await request.json();
  const { action, ...params } = body;

  try {
    switch (action) {
      case "claim_job": {
        const workerId = params.worker_id || "worker-unknown";
        const result = await supabase.rpc("claim_next_job", { p_worker_id: workerId });
        if (!result.data || result.data.length === 0) {
          return apiSuccess({ job: null });
        }
        const queueRow = result.data[0];
        // Enrich with job details
        const { data: jobDetail } = await supabase
          .from("discovered_jobs")
          .select("*")
          .eq("id", queueRow.job_id)
          .single();
        if (jobDetail) {
          queueRow.ats = jobDetail.ats;
          queueRow.apply_url = jobDetail.apply_url;
          queueRow.company = jobDetail.company;
          queueRow.title = jobDetail.title;
          queueRow.posted_at = jobDetail.posted_at;
          queueRow.location = jobDetail.location;
          // external_id is the ATS-assigned job ID used as the dedup-token
          // key in local SQLite (enqueue_to_local_db). Without it, log and
          // enqueue resolve different tokens → stale 'queued' shadow rows.
          queueRow.external_id = jobDetail.external_id;
        }
        // Surface profile binding so the worker can load the right bundle
        // (email, resume, app password, answer_key) for this job.
        queueRow.application_profile_id = queueRow.application_profile_id || null;
        return apiSuccess({ job: queueRow });
      }

      case "update_queue": {
        const updateData: Record<string, unknown> = { status: params.status };
        if (params.error) updateData.error = params.error;
        await supabase
          .from("application_queue")
          .update(updateData)
          .eq("id", params.queue_id);
        return apiSuccess({ updated: true });
      }

      case "log_application": {
        await supabase.from("applications").insert({
          user_id: userId,
          job_id: params.job_id,
          queue_id: params.queue_id,
          company: params.company || "",
          title: params.title || "",
          ats: params.ats || "",
          apply_url: params.apply_url || "",
          status: params.status || "submitted",
          screenshot_url: params.screenshot_url,
          error: params.error,
        });
        return apiSuccess({ logged: true });
      }

      case "heartbeat": {
        await supabase.from("worker_heartbeats").upsert(
          {
            user_id: userId,
            last_action: params.last_action || "",
            details: params.details || "",
            updated_at: new Date().toISOString(),
          },
          { onConflict: "user_id" }
        );
        return apiSuccess({ ok: true });
      }

      case "load_profile": {
        const [userRes, profileRes, resumesRes, defaultBundleRes] = await Promise.all([
          supabase.from("users").select("*").eq("id", userId).single(),
          supabase.from("user_profiles").select("*").eq("user_id", userId).single(),
          supabase.from("user_resumes").select("*").eq("user_id", userId),
          // The default application bundle holds the per-profile
          // `application_email` users fill in via the "Gmail address"
          // field. user_profiles.email is a separate column with no
          // UI writer, so it's null for every user. Resolve it here
          // so the worker's preflight check (which reads profile.email)
          // unblocks instead of looping on awaiting_profile forever.
          supabase
            .from("user_application_profiles")
            .select("application_email")
            .eq("user_id", userId)
            .eq("is_default", true)
            .maybeSingle(),
        ]);
        const profile = profileRes.data as Record<string, unknown> | null;
        if (profile && !profile.email) {
          const bundleEmail = (defaultBundleRes.data as { application_email?: string | null } | null)?.application_email;
          if (bundleEmail) profile.email = bundleEmail;
        }
        return apiSuccess({
          user: userRes.data,
          profile,
          resumes: resumesRes.data || [],
        });
      }

      case "load_preferences": {
        const { data } = await supabase
          .from("user_job_preferences")
          .select("*")
          .eq("user_id", userId)
          .single();
        return apiSuccess({ preferences: data || {} });
      }

      case "get_tenant_config": {
        // HARD FAIL when ENCRYPTION_KEY is unset. Without this check,
        // decryptString silently returns "" for every password, the worker
        // gets empty creds, and every SMTP login silently fails with no
        // surfaced error. Better to 500 here so the operator sees it.
        if (!process.env.ENCRYPTION_KEY) {
          return apiError(
            "internal_server_error",
            "ENCRYPTION_KEY is not configured — cannot decrypt tenant app passwords",
          );
        }
        // Returns identity + integrations + the full profiles[] array.
        // Single-profile users get a one-element array that mirrors the
        // legacy top-level fields — worker's TenantConfig.load() auto-wraps
        // either shape into profiles[].
        const [userRes, profileRes, prefsRes, bundlesRes, resumesRes, emailAccountsRes] = await Promise.all([
          supabase.from("users").select("email,daily_apply_limit").eq("id", userId).single(),
          supabase.from("user_profiles").select("*").eq("user_id", userId).single(),
          supabase.from("user_job_preferences").select("*").eq("user_id", userId).single(),
          supabase.from("user_application_profiles").select("*").eq("user_id", userId).order("is_default", { ascending: false }),
          supabase.from("user_resumes").select("id, storage_path, file_name, is_default, target_keywords").eq("user_id", userId),
          supabase.from("user_email_accounts").select("id, email, app_password_enc, label").eq("user_id", userId),
        ]);

        const profile = (profileRes.data ?? {}) as Record<string, unknown>;
        const prefs = (prefsRes.data ?? {}) as Record<string, unknown>;
        const user = (userRes.data ?? {}) as Record<string, unknown>;
        const bundles = (bundlesRes.data ?? []) as Record<string, unknown>[];
        const resumes = (resumesRes.data ?? []) as Record<string, unknown>[];
        const emailAccounts = (emailAccountsRes.data ?? []) as Record<string, unknown>[];

        const targetTitles: string[] = Array.isArray(prefs.target_titles) ? (prefs.target_titles as string[]) : [];
        const targetKeywords: string[] = Array.isArray(prefs.target_keywords) ? (prefs.target_keywords as string[]) : [];

        // Decrypt app passwords for the worker (only the worker — decrypted
        // values are NEVER returned to web/desktop UI endpoints). Import lazily.
        const { decryptString } = await import("@/lib/crypto");
        const resumeMap = new Map(resumes.map((r) => [r.id, r]));
        const emailAccountMap = new Map(emailAccounts.map((e) => [e.id, e]));

        const signedResumeUrl = async (storage_path: string): Promise<string | null> => {
          const { data } = await supabase.storage.from("resumes").createSignedUrl(storage_path, 3600);
          return data?.signedUrl ?? null;
        };

        const profilesOut = await Promise.all(bundles.map(async (b) => {
          const resume = b.resume_id ? resumeMap.get(b.resume_id) : null;
          const emailAcct = b.email_account_id ? emailAccountMap.get(b.email_account_id) : null;
          // Resolve application_email. Pool binding wins; else inline;
          // else null (signals worker to fall back to .env GMAIL_EMAIL —
          // matches legacy single-profile behavior).
          const rawInline = b.application_email as string | null | undefined;
          const appEmail = (emailAcct?.email as string | undefined) || (rawInline ? rawInline : null);
          let appPassword: string | null = null;
          const enc = (emailAcct?.app_password_enc as string | undefined) || (b.application_email_app_password_enc as string | undefined);
          if (enc) {
            try {
              const dec = decryptString(enc);
              appPassword = dec || null;  // empty string → null (fall back to .env)
            } catch { /* leave null */ }
          }
          let resumeUrl: string | null = null;
          if (resume?.storage_path) {
            try { resumeUrl = await signedResumeUrl(resume.storage_path as string); } catch {}
          }
          return {
            id: b.id,
            name: b.name,
            slug: b.slug,
            is_default: b.is_default,
            target_titles: b.target_titles ?? [],
            target_keywords: b.target_keywords ?? [],
            excluded_titles: b.excluded_titles ?? [],
            excluded_companies: b.excluded_companies ?? [],
            excluded_role_keywords: b.excluded_role_keywords ?? [],
            excluded_levels: b.excluded_levels ?? [],
            preferred_locations: b.preferred_locations ?? [],
            remote_only: !!b.remote_only,
            min_salary: b.min_salary ?? null,
            ashby_boards: b.ashby_boards ?? null,
            greenhouse_boards: b.greenhouse_boards ?? null,
            auto_apply: b.auto_apply !== false,
            max_daily: b.max_daily ?? null,
            resume: resume ? {
              id: resume.id,
              file_name: resume.file_name,
              storage_path: resume.storage_path,
              signed_url: resumeUrl,
            } : null,
            application_email: appEmail,
            application_email_app_password: appPassword,
            // Per-bundle content (migration 019). Falls back to
            // user_profiles.answer_key_json / cover_letter_template on
            // the worker side when the bundle's value is null — that
            // keeps single-profile users and old installs working.
            answer_key_json: b.answer_key_json ?? null,
            cover_letter_template: b.cover_letter_template ?? null,
            // Per-bundle work history (migration 020). Same fallback
            // pattern — null means "inherit from user_profiles".
            work_experience: b.work_experience ?? null,
            education: b.education ?? null,
            skills: b.skills ?? null,
          };
        }));

        // This response contains DECRYPTED Gmail app passwords for the
        // worker. Force no-store so intermediaries (CDN, Vercel edge cache,
        // dev proxies) never retain the body.
        const tenantBody = {
          user_id: userId,
          tenant_email: (user.email as string | undefined) || (profile.email as string | undefined) || "",
          // Legacy top-level fields — mirror the default profile so old
          // worker builds keep working until they switch to profiles[].
          search_queries: targetTitles,
          keyword_filter: targetKeywords.length > 0 ? targetKeywords : targetTitles,
          ashby_boards: (prefs.ashby_boards as string[] | null | undefined) ?? null,
          greenhouse_boards: (prefs.greenhouse_boards as string[] | null | undefined) ?? null,
          excluded_role_keywords: (prefs.excluded_role_keywords as string[] | undefined) ?? [],
          excluded_levels: (prefs.excluded_levels as string[] | undefined) ?? [],
          excluded_companies: (prefs.excluded_companies as string[] | undefined) ?? [],
          preferred_locations: (prefs.preferred_locations as string[] | undefined) ?? [],
          remote_only: !!prefs.remote_only,
          min_salary: (prefs.min_salary as number | null | undefined) ?? null,
          daily_apply_limit: (user.daily_apply_limit as number | undefined) ?? 25,
          profile: profile,
          // NEW: authoritative profile bundles array
          profiles: profilesOut,
          complete: targetTitles.length > 0
            && !!profile.first_name
            && (!!profile.email || !!user.email),
        };
        return NextResponse.json({ data: tenantBody }, {
          status: 200,
          headers: {
            "Cache-Control": "no-store, private, max-age=0, must-revalidate",
            "Pragma": "no-cache",
          },
        });
      }

      case "update_profile": {
        // Upsert the authenticated user's profile row. user_id is derived
        // from the worker token server-side, NOT from params — a worker
        // token can never write another user's profile. Column allowlist
        // prevents setting is_admin / approval_status / other sensitive
        // fields that only belong in other tables.
        // answer_key_json + cover_letter_template are intentionally NOT in
        // this allowlist as of migration 019. Those fields are now per-
        // bundle — edits go through /api/settings/profiles/[id] PUT and
        // land on user_application_profiles.answer_key_json instead. The
        // legacy user_profiles columns stay in the schema as a read-only
        // fallback for older worker builds during rolling deploy but can
        // no longer be written via the worker proxy.
        // AI Import + legacy Work & Education tab still write here.
        // work_experience / education / skills are mirrored into the
        // user's default bundle AFTER the user_profiles upsert so the
        // worker (which reads from the bundle as of mig 020) sees them
        // without forcing every caller to migrate. Per-profile edits
        // via /api/settings/profiles/[id] PUT remain the authoritative
        // path for non-default bundles.
        const PROFILE_COLUMNS = [
          "first_name", "last_name", "email", "phone",
          "linkedin_url", "github_url", "portfolio_url",
          "current_company", "current_title", "years_experience",
          "education_level", "school_name", "degree", "graduation_year",
          "work_authorization", "requires_sponsorship",
          "gender", "race_ethnicity", "veteran_status", "disability_status",
          "work_experience", "education", "skills",
        ] as const;
        const payload: Record<string, unknown> = {
          user_id: userId,
          updated_at: new Date().toISOString(),
        };
        const incoming = (params.profile || params) as Record<string, unknown>;
        for (const key of PROFILE_COLUMNS) {
          if (key in incoming) payload[key] = incoming[key];
        }
        const { error } = await supabase
          .from("user_profiles")
          .upsert(payload, { onConflict: "user_id" });
        if (error) {
          return apiError("internal_server_error", error.message);
        }

        // Mirror work_experience / education / skills onto the user's
        // default application profile bundle. Post mig-020 the worker
        // reads these from the bundle, so a bare update_profile call
        // (AI Import, legacy Work & Edu tab) must propagate or the
        // worker will apply with stale data.
        const bundleMirror: Record<string, unknown> = {};
        if ("work_experience" in incoming) bundleMirror.work_experience = incoming.work_experience;
        if ("education" in incoming) bundleMirror.education = incoming.education;
        if ("skills" in incoming) bundleMirror.skills = incoming.skills;
        if (Object.keys(bundleMirror).length > 0) {
          bundleMirror.updated_at = new Date().toISOString();
          const { error: mirrorErr } = await supabase
            .from("user_application_profiles")
            .update(bundleMirror)
            .eq("user_id", userId)
            .eq("is_default", true);
          if (mirrorErr) {
            // Legacy upsert already succeeded; log and continue so the
            // UI doesn't double-flash. Worker will still see the data
            // via the user_profiles fallback in the meantime.
            console.warn("update_profile → default bundle mirror failed:", mirrorErr.message);
          }
        }

        return apiSuccess({ updated: true });
      }

      case "list_resumes": {
        // Return the authenticated user's resumes so the desktop Settings
        // tab can render a "current resume" widget with download link.
        const { data, error } = await supabase
          .from("user_resumes")
          .select("id, storage_path, file_name, is_default, target_keywords, created_at")
          .eq("user_id", userId)
          .order("created_at", { ascending: false });
        if (error) return apiError("internal_server_error", error.message);
        return apiSuccess({ resumes: data || [] });
      }

      case "upload_resume": {
        // Accept a base64-encoded PDF from the desktop and write it to
        // Supabase Storage + user_resumes. Mirrors the validation in
        // packages/web/src/app/api/onboarding/resume/route.ts (Agent B's
        // fb23c2c fix): 10 MB cap, PDF magic-byte sniff, sanitized filename.
        //
        // Params:
        //   content_base64   required   full PDF body, base64-encoded
        //   file_name        required   user-supplied display name
        //   target_keywords  optional   string[] for resume routing
        //   is_default       optional   boolean — if true, clears other
        //                               rows' is_default flag for this user
        const MAX_BYTES = 10 * 1024 * 1024;
        const contentB64 = params.content_base64 as string | undefined;
        const rawName = (params.file_name as string | undefined) || "resume.pdf";
        const targetKeywords = Array.isArray(params.target_keywords)
          ? (params.target_keywords as string[]).slice(0, 20)
          : [];
        const makeDefault = params.is_default !== false; // default true

        if (!contentB64 || typeof contentB64 !== "string") {
          return apiError("validation_error", "content_base64 is required");
        }

        let buf: Buffer;
        try {
          buf = Buffer.from(contentB64, "base64");
        } catch {
          return apiError("validation_error", "content_base64 is not valid base64");
        }

        if (buf.length === 0) {
          return apiError("validation_error", "resume is empty");
        }
        if (buf.length > MAX_BYTES) {
          return apiError(
            "validation_error",
            `resume exceeds 10 MB cap (got ${buf.length} bytes)`
          );
        }
        // PDF magic byte sniff — first 4 bytes must be "%PDF"
        if (buf.slice(0, 4).toString("ascii") !== "%PDF") {
          return apiError(
            "validation_error",
            "file does not look like a PDF (missing %PDF magic bytes)"
          );
        }

        // Sanitize filename so it can't traverse paths or inject weird chars
        // into the storage_path. Keep only [a-zA-Z0-9._-], collapse the rest.
        const cleanName = rawName
          .replace(/[^a-zA-Z0-9._-]/g, "_")
          .replace(/^_+|_+$/g, "")
          .slice(0, 120) || "resume.pdf";
        // Guarantee .pdf suffix
        const finalName = cleanName.toLowerCase().endsWith(".pdf")
          ? cleanName
          : `${cleanName}.pdf`;

        // Storage path: resumes/{user_id}/{timestamp}_{filename}.pdf
        // Timestamp prefix means re-uploads don't overwrite each other —
        // the user keeps a history and can be routed between them via
        // target_keywords.
        const storagePath = `${userId}/${Date.now()}_${finalName}`;

        const uploadRes = await supabase.storage
          .from("resumes")
          .upload(storagePath, buf, {
            contentType: "application/pdf",
            upsert: false,
          });
        if (uploadRes.error) {
          return apiError(
            "internal_server_error",
            `storage upload failed: ${uploadRes.error.message}`
          );
        }

        // If this upload is being flagged as the default, clear is_default
        // on every other resume row for this user first (the client usually
        // passes is_default=true — so single-resume users get the right row).
        if (makeDefault) {
          await supabase
            .from("user_resumes")
            .update({ is_default: false })
            .eq("user_id", userId);
        }

        const { data: insertRow, error: insertErr } = await supabase
          .from("user_resumes")
          .insert({
            user_id: userId,
            storage_path: storagePath,
            file_name: finalName,
            is_default: makeDefault,
            target_keywords: targetKeywords,
          })
          .select("id, storage_path, file_name, is_default, target_keywords, created_at")
          .single();
        if (insertErr) {
          // Try to roll back the storage write — best effort, don't block
          // the error return.
          try { await supabase.storage.from("resumes").remove([storagePath]); } catch {}
          return apiError("internal_server_error", insertErr.message);
        }

        return apiSuccess({
          resume: insertRow,
          size_bytes: buf.length,
        });
      }

      case "update_preferences": {
        // Upsert the authenticated user's job preferences. Same scoping +
        // allowlist pattern as update_profile.
        const PREFERENCE_COLUMNS = [
          "target_titles", "target_keywords",
          "excluded_titles", "excluded_companies",
          // Per-tenant filter fields added in migration 011 — were
          // silently dropped before this fix, so desktop Settings saves
          // for these never persisted. Audit (Apr 14) surfaced it.
          "excluded_role_keywords", "excluded_levels",
          "ashby_boards", "greenhouse_boards",
          "min_salary", "preferred_locations",
          "remote_only", "auto_apply", "max_daily",
        ] as const;
        const payload: Record<string, unknown> = {
          user_id: userId,
          updated_at: new Date().toISOString(),
        };
        const incoming = (params.preferences || params) as Record<string, unknown>;
        for (const key of PREFERENCE_COLUMNS) {
          if (key in incoming) payload[key] = incoming[key];
        }
        const { error } = await supabase
          .from("user_job_preferences")
          .upsert(payload, { onConflict: "user_id" });
        if (error) {
          return apiError("internal_server_error", error.message);
        }
        return apiSuccess({ updated: true });
      }

      case "check_daily_limit": {
        const { data: user } = await supabase
          .from("users")
          .select("daily_apply_limit")
          .eq("id", userId)
          .single();
        const limit = user?.daily_apply_limit || 5;
        const today = new Date().toISOString().split("T")[0];
        const countResult = await supabase
          .from("applications")
          .select("id", { count: "exact" })
          .eq("user_id", userId)
          .gte("applied_at", `${today}T00:00:00Z`);
        const current = countResult.count || 0;
        return apiSuccess({ within_limit: current < limit, current, limit });
      }

      case "check_company_rate": {
        // Rolling 7-day cap of 3 apps per company. Was 5 per 15 days —
        // simpler rule, easier to reason about, matches real behavior
        // better (listings expire, repeat attempts to same company rarely
        // help within a week).
        const cutoff = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
        const result = await supabase
          .from("applications")
          .select("id", { count: "exact" })
          .eq("user_id", userId)
          .ilike("company", `%${params.company}%`)
          .gte("applied_at", cutoff);
        const count = result.count || 0;
        return apiSuccess({ within_limit: count < 3, count, max: 3 });
      }

      case "enqueue_jobs": {
        const jobs = params.jobs || [];
        const { data: myBundles } = await supabase
          .from("user_application_profiles")
          .select("id")
          .eq("user_id", userId);
        const ownedBundleIds = new Set((myBundles || []).map((b) => b.id));
        let enqueued = 0;
        const drops: Array<{ job: { title?: string; company?: string }; reason: string }> = [];
        for (const job of jobs) {
          const jobTag = { title: job.title, company: job.company };

          // Validate NOT NULL fields up front so the failure mode is a
          // readable reason, not a swallowed Postgres 23502.
          const required = ["title", "company", "apply_url", "ats"] as const;
          const missing = required.filter((k) => !job[k]);
          if (missing.length) {
            drops.push({ job: jobTag, reason: `missing_fields: ${missing.join(",")}` });
            continue;
          }

          const existing = await supabase
            .from("applications")
            .select("id", { count: "exact" })
            .eq("user_id", userId)
            .eq("company", job.company)
            .eq("title", job.title);
          if ((existing.count || 0) > 0) {
            drops.push({ job: jobTag, reason: "dedup: already in applications" });
            continue;
          }

          const dj = await supabase
            .from("discovered_jobs")
            .upsert(
              {
                title: job.title,
                company: job.company,
                location: job.location || "",
                apply_url: job.apply_url,
                external_id: job.external_id || "",
                ats: job.ats,
                discovered_at: new Date().toISOString(),
              },
              { onConflict: "external_id,ats" }
            )
            .select("id")
            .single();
          const jobId = (dj.data as Record<string, unknown> | null)?.id;
          if (dj.error || !jobId) {
            drops.push({ job: jobTag, reason: `upsert_failed: ${dj.error?.message ?? "no id returned"}` });
            continue;
          }

          // Queue dedup — skip if this user already has an ACTIVE queue row
          // for this discovered_jobs.id. "Active" = pending or locked; done /
          // failed / cancelled don't count (re-queue is intentional for retry).
          const qExisting = await supabase
            .from("application_queue")
            .select("id", { count: "exact" })
            .eq("user_id", userId)
            .eq("job_id", jobId)
            .in("status", ["pending", "locked", "in_progress"]);
          if ((qExisting.count || 0) > 0) {
            drops.push({ job: jobTag, reason: "dedup: already queued" });
            continue;
          }

          const taggedProfileId =
            job.application_profile_id && ownedBundleIds.has(job.application_profile_id)
              ? job.application_profile_id
              : null;
          const q = await supabase.from("application_queue").insert({
            user_id: userId,
            job_id: jobId,
            status: "pending",
            application_profile_id: taggedProfileId,
          });
          if (q.error) {
            drops.push({ job: jobTag, reason: `queue_insert_failed: ${q.error.message}` });
            continue;
          }
          enqueued++;
        }
        return apiSuccess({ enqueued, dropped: drops.length, drops });
      }

      case "get_answer_key": {
        const { data } = await supabase
          .from("user_profiles")
          .select("answer_key_json")
          .eq("user_id", userId)
          .single();
        return apiSuccess({ answer_key: data?.answer_key_json || {} });
      }

      case "get_telegram_config": {
        // Source of truth: user_profiles.integrations_encrypted, where the
        // new Settings UI saves user-provided bot tokens. Fall back to the
        // legacy users.telegram_chat_id column, then to the admin's shared
        // bot env var as last resort. Without this fix, the legacy action
        // always returned the env-var placeholder even after the user
        // configured their own bot via the new integrations endpoint.
        const [profileRes, userRes] = await Promise.all([
          supabase.from("user_profiles").select("integrations_encrypted").eq("user_id", userId).single(),
          supabase.from("users").select("telegram_chat_id").eq("id", userId).single(),
        ]);

        let userBotToken: string | null = null;
        let userChatId: string | null = null;
        const rawIntegrations = (profileRes.data as Record<string, unknown> | null)?.integrations_encrypted;
        if (rawIntegrations && typeof rawIntegrations === "object") {
          try {
            const { decryptIntegrationsBlob } = await import("@/lib/crypto");
            const decrypted = decryptIntegrationsBlob(rawIntegrations as Record<string, string>);
            if (decrypted.telegram_bot_token) userBotToken = decrypted.telegram_bot_token;
            if (decrypted.telegram_chat_id) userChatId = decrypted.telegram_chat_id;
          } catch {
            // Decryption failure (e.g. ENCRYPTION_KEY mismatch) — fall through
            // to legacy fields instead of crashing the whole action.
          }
        }

        // Legacy chat_id column as fallback
        if (!userChatId && (userRes.data as { telegram_chat_id?: string } | null)?.telegram_chat_id) {
          userChatId = (userRes.data as { telegram_chat_id?: string }).telegram_chat_id ?? null;
        }

        const sharedBotToken = process.env.TELEGRAM_BOT_TOKEN || null;
        const finalBotToken = userBotToken || sharedBotToken;
        const isSharedBot = !userBotToken && !!sharedBotToken;

        return apiSuccess({
          chat_id: userChatId,
          bot_token: finalBotToken,
          is_shared_bot: isSharedBot,
          source: userBotToken ? "user_integrations" : (sharedBotToken ? "shared_env" : "none"),
        });
      }

      case "download_resume_url": {
        const { data: resumes } = await supabase
          .from("user_resumes")
          .select("*")
          .eq("user_id", userId);
        if (!resumes || resumes.length === 0) {
          return apiError("not_found", "No resume found");
        }
        // Pick best resume based on job title
        let resume = resumes.find((r: Record<string, unknown>) => r.is_default) || resumes[0];
        if (params.job_title) {
          const titleLower = (params.job_title as string).toLowerCase();
          let bestScore = 0;
          for (const r of resumes) {
            const keywords = (r.target_keywords as string[]) || [];
            const score = keywords.filter((kw: string) => titleLower.includes(kw.toLowerCase())).length;
            if (score > bestScore) {
              bestScore = score;
              resume = r;
            }
          }
        }
        // Generate signed URL for download
        const { data: signedUrl } = await supabase.storage
          .from("resumes")
          .createSignedUrl(resume.storage_path, 3600); // 1 hour
        return apiSuccess({
          url: signedUrl?.signedUrl,
          file_name: resume.file_name,
        });
      }

      // ── Desktop Dashboard Stats (read-only) ──────────────────────────────

      case "get_stats": {
        const today = new Date().toISOString().split("T")[0];
        const [todayRes, totalRes, queueRes, failedRes] = await Promise.all([
          supabase
            .from("applications")
            .select("id", { count: "exact" })
            .eq("user_id", userId)
            .gte("applied_at", `${today}T00:00:00Z`),
          supabase
            .from("applications")
            .select("id", { count: "exact" })
            .eq("user_id", userId),
          supabase
            .from("application_queue")
            .select("id", { count: "exact" })
            .eq("user_id", userId)
            .in("status", ["pending", "locked"]),
          supabase
            .from("applications")
            .select("id", { count: "exact" })
            .eq("user_id", userId)
            .eq("status", "failed"),
        ]);
        const total = totalRes.count || 0;
        const failed = failedRes.count || 0;
        const rate = total > 0 ? Math.round(((total - failed) / total) * 100) : 0;
        return apiSuccess({
          applied_today: todayRes.count || 0,
          total_applied: total,
          in_queue: queueRes.count || 0,
          success_rate: rate,
        });
      }

      case "get_daily_breakdown": {
        const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
        const { data: apps } = await supabase
          .from("applications")
          .select("applied_at, status")
          .eq("user_id", userId)
          .gte("applied_at", thirtyDaysAgo)
          .order("applied_at", { ascending: true });
        // Group by date
        const byDate: Record<string, { submitted: number; failed: number }> = {};
        for (const app of apps || []) {
          const d = new Date(app.applied_at).toLocaleDateString("en-US", { month: "short", day: "numeric" });
          if (!byDate[d]) byDate[d] = { submitted: 0, failed: 0 };
          if (app.status === "failed") byDate[d].failed++;
          else byDate[d].submitted++;
        }
        return apiSuccess(Object.entries(byDate).map(([date, counts]) => ({ date, ...counts })));
      }

      case "get_ats_breakdown": {
        const { data: apps } = await supabase
          .from("applications")
          .select("ats")
          .eq("user_id", userId);
        const byAts: Record<string, number> = {};
        for (const app of apps || []) {
          const ats = app.ats || "unknown";
          byAts[ats] = (byAts[ats] || 0) + 1;
        }
        const total = Object.values(byAts).reduce((a, b) => a + b, 0) || 1;
        return apiSuccess(
          Object.entries(byAts)
            .map(([name, count]) => ({ name, value: Math.round((count / total) * 100) }))
            .sort((a, b) => b.value - a.value)
        );
      }

      case "get_pipeline": {
        const { data: queue } = await supabase
          .from("application_queue")
          .select("id, job_id, status, company, apply_url, error, created_at")
          .eq("user_id", userId)
          .order("created_at", { ascending: false })
          .limit(200);

        // Enrich with job details
        const jobIds = [...new Set((queue || []).map((q: Record<string, unknown>) => q.job_id).filter(Boolean))];
        const { data: jobs } = jobIds.length
          ? await supabase.from("discovered_jobs").select("id, title, company, ats, posted_at").in("id", jobIds)
          : { data: [] };
        const jobMap = new Map((jobs || []).map((j: Record<string, unknown>) => [j.id, j]));

        const pipeline: Record<string, unknown[]> = {
          discovered: [],
          queued: [],
          applying: [],
          submitted: [],
          failed: [],
        };

        for (const q of queue || []) {
          const job = jobMap.get(q.job_id) || {};
          const item = {
            id: q.id,
            company: (job as Record<string, unknown>).company || q.company || "",
            title: (job as Record<string, unknown>).title || "",
            ats: (job as Record<string, unknown>).ats || "",
            posted_at: (job as Record<string, unknown>).posted_at || q.created_at,
            status: q.status,
            error: q.error,
          };
          if (q.status === "pending") pipeline.queued.push(item);
          else if (q.status === "locked" || q.status === "processing") pipeline.applying.push(item);
          else if (q.status === "submitted") pipeline.submitted.push(item);
          else if (q.status === "failed") pipeline.failed.push(item);
        }

        // Add recent discovered jobs not yet in queue
        const { data: discovered } = await supabase
          .from("discovered_jobs")
          .select("id, title, company, ats, posted_at")
          .order("discovered_at", { ascending: false })
          .limit(50);

        const queuedJobIds = new Set((queue || []).map((q: Record<string, unknown>) => q.job_id));
        for (const d of discovered || []) {
          if (!queuedJobIds.has(d.id)) {
            pipeline.discovered.push({
              id: d.id,
              company: d.company,
              title: d.title,
              ats: d.ats,
              posted_at: d.posted_at,
              status: "discovered",
            });
          }
        }

        return apiSuccess(pipeline);
      }

      case "get_recent_applications": {
        const limit = params.params?.limit || params.limit || 20;
        const { data } = await supabase
          .from("applications")
          .select("company, title, ats, status, applied_at, error")
          .eq("user_id", userId)
          .order("applied_at", { ascending: false })
          .limit(limit);
        return apiSuccess(data || []);
      }

      case "heartbeat_status": {
        const { data } = await supabase
          .from("worker_heartbeats")
          .select("*")
          .eq("user_id", userId)
          .single();
        return apiSuccess(data || {});
      }

      case "get_next_action": {
        // Cloud-planner brain. Called by the worker every ~60s.
        // Rules-first decision ladder; LLM fallback is Phase 3.
        //
        // Live state inputs:
        //   - in_queue      active queue rows (pending/locked/in_progress)
        //   - applied_today submissions since UTC midnight
        //   - daily_cap     min of users.daily_apply_limit & default bundle.max_daily
        //                   (null means no cap on that side)
        //   - last_scout_*  last 3 scout decisions from worker_plan
        //
        // Writes one row to worker_plan with a 10-min expiry.

        const utcMidnightIso = new Date().toISOString().slice(0, 10) + "T00:00:00Z";

        const [queueRes, appliedRes, userRes, bundleRes, recentRes] = await Promise.all([
          supabase
            .from("application_queue")
            .select("id", { count: "exact", head: true })
            .eq("user_id", userId)
            .in("status", ["pending", "locked", "in_progress"]),
          supabase
            .from("applications")
            .select("id", { count: "exact", head: true })
            .eq("user_id", userId)
            .eq("status", "submitted")
            .gte("applied_at", utcMidnightIso),
          supabase
            .from("users")
            .select("daily_apply_limit")
            .eq("id", userId)
            .maybeSingle(),
          supabase
            .from("user_application_profiles")
            .select("max_daily")
            .eq("user_id", userId)
            .eq("is_default", true)
            .maybeSingle(),
          supabase
            .from("worker_plan")
            .select("action, outcome, decided_at")
            .eq("user_id", userId)
            .order("decided_at", { ascending: false })
            .limit(5),
        ]);

        const inQueue = queueRes.count ?? 0;
        const appliedToday = appliedRes.count ?? 0;

        // Null on either side = no cap on that side. Effective cap is the
        // tighter one. If both null → unlimited.
        const userCap = (userRes.data as { daily_apply_limit?: number | null } | null)?.daily_apply_limit ?? null;
        const bundleCap = (bundleRes.data as { max_daily?: number | null } | null)?.max_daily ?? null;
        const dailyCap: number | null =
          userCap !== null && bundleCap !== null
            ? Math.min(userCap, bundleCap)
            : (userCap ?? bundleCap);

        const recent = (recentRes.data as Array<{ action: string; outcome: string | null; decided_at: string }> | null) ?? [];
        const recentScouts = recent.filter((r) => r.action.startsWith("scout_"));
        const lastScoutAt = recentScouts[0]?.decided_at;
        const lastScoutAgeMin = lastScoutAt
          ? (Date.now() - new Date(lastScoutAt).getTime()) / 60000
          : null;
        const last3Scouts = recentScouts.slice(0, 3);
        const allRecentScoutsEmpty =
          last3Scouts.length >= 3 &&
          last3Scouts.every((s) => s.outcome === "empty");

        // Decision ladder
        let plannedAction: string;
        let reason: string;

        if (dailyCap !== null && appliedToday >= dailyCap) {
          plannedAction = "idle_until_midnight";
          reason = `daily cap reached (${appliedToday}/${dailyCap})`;
        } else if (inQueue > 0) {
          plannedAction = "apply_next";
          reason = `queue=${inQueue}, applied=${appliedToday}${dailyCap !== null ? "/" + dailyCap : ""}`;
        } else if (allRecentScoutsEmpty) {
          plannedAction = "scout_expand_boards";
          reason = `3 consecutive empty scouts — try new companies`;
        } else if (lastScoutAgeMin !== null && lastScoutAgeMin < 5) {
          plannedAction = "scout_title_based";
          reason = `queue empty, primary scout just ran — rotate to title-based`;
        } else {
          plannedAction = "scout_primary";
          reason = lastScoutAgeMin === null
            ? "queue empty, no scout on record — start"
            : `queue empty, primary scout ${lastScoutAgeMin.toFixed(0)}m old`;
        }

        const expiresAt = new Date(Date.now() + 10 * 60 * 1000).toISOString();
        const planInsert = await supabase
          .from("worker_plan")
          .insert({
            user_id: userId,
            action: plannedAction,
            params: {},
            expires_at: expiresAt,
            reason,
          })
          .select("id, action, params, reason, expires_at")
          .single();

        if (planInsert.error || !planInsert.data) {
          return apiError("internal_server_error", `plan insert failed: ${planInsert.error?.message ?? "no row returned"}`);
        }

        return apiSuccess({
          plan_id: planInsert.data.id,
          action: planInsert.data.action,
          params: planInsert.data.params,
          reason: planInsert.data.reason,
          expires_at: planInsert.data.expires_at,
          state: { in_queue: inQueue, applied_today: appliedToday, daily_cap: dailyCap },
        });
      }

      case "report_plan_outcome": {
        // Worker posts back after executing a plan. Outcome values match
        // the CHECK constraint: success / empty / failed / skipped.
        const planId = params.plan_id;
        const outcome = params.outcome;
        const detail = params.outcome_detail || null;
        if (!planId || !outcome) {
          return apiError("validation_error", "plan_id and outcome are required");
        }
        const { error } = await supabase
          .from("worker_plan")
          .update({
            outcome,
            outcome_detail: detail,
            outcome_at: new Date().toISOString(),
          })
          .eq("id", planId)
          .eq("user_id", userId);
        if (error) {
          return apiError("internal_server_error", error.message);
        }
        return apiSuccess({ ok: true });
      }

      default:
        return apiError("validation_error", `Unknown action: ${action}`);
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return apiError("internal_server_error", msg);
  }
}
