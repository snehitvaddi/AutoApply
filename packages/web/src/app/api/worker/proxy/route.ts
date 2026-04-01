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
 *   - check_company_rate: Check 30-day company application count
 */

import { NextRequest } from "next/server";
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
        }
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
        const [userRes, profileRes, resumesRes] = await Promise.all([
          supabase.from("users").select("*").eq("id", userId).single(),
          supabase.from("user_profiles").select("*").eq("user_id", userId).single(),
          supabase.from("user_resumes").select("*").eq("user_id", userId),
        ]);
        return apiSuccess({
          user: userRes.data,
          profile: profileRes.data,
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
        const cutoff = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
        const result = await supabase
          .from("applications")
          .select("id", { count: "exact" })
          .eq("user_id", userId)
          .ilike("company", `%${params.company}%`)
          .gte("applied_at", cutoff);
        const count = result.count || 0;
        return apiSuccess({ within_limit: count < 5, count, max: 5 });
      }

      case "enqueue_jobs": {
        const jobs = params.jobs || [];
        let enqueued = 0;
        for (const job of jobs) {
          // Dedup
          const existing = await supabase
            .from("applications")
            .select("id", { count: "exact" })
            .eq("user_id", userId)
            .eq("company", job.company)
            .eq("title", job.title);
          if ((existing.count || 0) > 0) continue;

          // Upsert discovered job
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
              { onConflict: "apply_url" }
            );
          const jobId = dj.data?.[0]?.id;
          if (!jobId) continue;

          // Queue
          await supabase.from("application_queue").insert({
            user_id: userId,
            job_id: jobId,
            status: "pending",
            company: job.company,
            apply_url: job.apply_url,
          });
          enqueued++;
        }
        return apiSuccess({ enqueued });
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
        const { data: user } = await supabase
          .from("users")
          .select("telegram_chat_id")
          .eq("id", userId)
          .single();
        return apiSuccess({
          chat_id: user?.telegram_chat_id || null,
          bot_token: process.env.TELEGRAM_BOT_TOKEN || null,
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

      default:
        return apiError("validation_error", `Unknown action: ${action}`);
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return apiError("internal_server_error", msg);
  }
}
