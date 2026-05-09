"""Brain-callable single-job apply.

Stage 1 of the brain-as-conductor architecture. Today's worker.py
runs as a daemon: a separate process that loops on its own and shares
state with the brain only through SQLite. That model has a
fundamental limit — Python is synchronous, so when the daemon hits
mid-form uncertainty there's no way to ask the brain "what now?"
without losing the form state.

This module exposes the per-job apply path as a SYNCHRONOUS function
the brain can call directly via the new `worker_apply_one_job` MCP
tool. When the brain calls it:

  1. Function loads the tenant, claims the next queued job (or the
     job_id the brain specified).
  2. Runs the standard preflight (resume, profile, daily limit,
     company rate, blocked-URL).
  3. If the ATS has a coded recipe, runs it synchronously. The recipe
     lives in `applier/<ats>.py` and only does deterministic work.
  4. If recipe missing OR fails (and brain-fallback is enabled), the
     row is marked `awaiting_brain` and the function returns
     immediately with a `handoff` outcome. The browser is left on the
     same page so the brain can take over without losing state.
  5. Returns a structured `JobOutcome` dict the brain can reason about
     directly — no scraping logs, no polling SQLite, no race.

The brain is now the loop. It calls this in a sequence:
  outcome = worker_apply_one_job()
  ... brain decides what to do based on outcome.handoff_reason ...
  outcome = worker_apply_one_job()
  ...

Daemon mode (`worker.py main()`) still works for users who want the
old behavior. This module is purely additive.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# Apply-in-progress marker — preflight reads this to skip the deep
# browser probe (and the gateway-restart fallback) while an apply is
# actively driving the same Chrome session. Without this signal,
# preflight's 10-min deep probe could shell `openclaw gateway restart`
# mid-apply, killing the session. See plan
# `hey-i-understand-the-hashed-sutherland.md` Fix 3.
_APPLY_MARKER_PATH = os.path.join(
    os.environ.get("APPLYLOOP_HOME") or os.path.expanduser("~/.applyloop"),
    ".apply-in-progress",
)
# Auto-expire after 5 min — a real apply can take a couple minutes
# (resume upload, captcha wait), but if the marker outlives that the
# brain almost certainly crashed and we shouldn't hold preflight off
# forever.
_APPLY_MARKER_TTL_S = 300


def _write_apply_marker() -> None:
    try:
        os.makedirs(os.path.dirname(_APPLY_MARKER_PATH), exist_ok=True)
        with open(_APPLY_MARKER_PATH, "w") as f:
            f.write(str(int(time.time())))
    except OSError as e:
        logger.debug(f"could not write apply marker: {e}")


def _clear_apply_marker() -> None:
    try:
        os.unlink(_APPLY_MARKER_PATH)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug(f"could not clear apply marker: {e}")


def _make_outcome(
    status: str,
    job: dict | None = None,
    error: str | None = None,
    detail: str | None = None,
    handoff_reason: str | None = None,
    screenshot_url: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Standard outcome shape so brain doesn't have to memorize many.

    status:
      submitted     — recipe applied successfully
      handoff       — recipe missing / failed; brain should drive next
      skipped       — preflight rejected (blocked company, daily cap)
      empty         — queue had nothing to claim
      profile_gap   — user setup incomplete (resume/profile/titles)
      auth_expired  — worker token rejected; brain must reauth
      error         — unexpected exception

    handoff_reason set ONLY when status='handoff', tells brain why
    (no_recipe / recipe_failed / captcha_v2 / unknown_form_state).
    """
    out: dict[str, Any] = {"status": status, "at": datetime.now(timezone.utc).isoformat()}
    if job:
        out["job"] = {
            "id": job.get("id"),
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "ats": job.get("ats", ""),
            "apply_url": job.get("apply_url", ""),
        }
    if error: out["error"] = error
    if detail: out["detail"] = detail
    if handoff_reason: out["handoff_reason"] = handoff_reason
    if screenshot_url: out["screenshot_url"] = screenshot_url
    if extra: out.update(extra)
    return out


def apply_one_job(
    job_id: str | None = None,
    enable_brain_fallback: bool = True,
) -> dict[str, Any]:
    """Run preflight + apply for ONE job synchronously and return the
    outcome.

    job_id: optional. If given, the brain wants THIS specific job
        applied (must be in 'queued' status locally). If omitted,
        claims the oldest queued row.
    enable_brain_fallback: when a recipe fails non-retriably (or no
        recipe exists for the ATS), mark the row 'skipped' with an
        `awaiting_brain:` notes prefix and return status='handoff'
        instead of failing. Brain takes over from there.
    """
    # Lazy imports — keep this module importable in environments
    # where the heavy worker deps (sqlite, supabase httpx client) are
    # not yet installed (e.g. doctests). Brain calls it from the MCP
    # server which has everything available.
    from tenant import TenantConfig, TenantConfigIncompleteError
    from db import (
        WorkerAuthError, claim_next_job_locally,
        update_queue_status, update_local_status,
        log_application, upload_screenshot, update_heartbeat,
        load_user_profile, fetch_user_job_preferences,
        check_daily_limit_locally, check_company_rate_locally,
        download_resume, download_resume_by_url,
    )
    from applier.base import MissingResumeError
    from notifier import send_application_result, send_failure
    from knowledge import build_answer_key, load_global_template
    from config import is_staffing_agency
    # APPLIERS + lightweight helpers in worker.py — same registry
    # daemon mode uses; importing avoids drift between callers.
    from worker import (
        APPLIERS, WORKER_ID, is_blocked_url, is_blocked_company,
        is_paused_company,
    )

    user_id = os.environ.get("APPLYLOOP_USER_ID", "").strip()
    if not user_id:
        # Brain shouldn't call this without env set up. Surface clearly.
        return _make_outcome(
            "error",
            error="APPLYLOOP_USER_ID not set in env. Brain must run inside the desktop's PTY environment.",
        )

    # Tenant load — same path daemon uses, same error contracts.
    try:
        tenant = TenantConfig.load(user_id)
    except TenantConfigIncompleteError as e:
        return _make_outcome(
            "profile_gap",
            error=str(e),
            detail=f"missing: {', '.join(e.missing)}",
        )
    except WorkerAuthError as e:
        return _make_outcome("auth_expired", error=str(e))
    except Exception as e:
        return _make_outcome("error", error=f"tenant load failed: {e}")

    # Claim. Local-first matches default daemon mode.
    try:
        if job_id:
            # When brain asked for a specific row, look it up + flip
            # status atomically so two brain calls can't race on it.
            import sqlite3
            from contextlib import closing
            from db import LOCAL_DB_PATH
            now = datetime.now(timezone.utc).isoformat()
            with closing(sqlite3.connect(LOCAL_DB_PATH, timeout=5.0)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    UPDATE applications
                    SET status='applying', updated_at=?
                    WHERE id=? AND status='queued'
                    RETURNING id, company, role, url, ats, source, location,
                              posted_at, scouted_at, dedup_token, application_profile_id
                    """,
                    (now, job_id),
                ).fetchone()
                conn.commit()
            if not row:
                return _make_outcome("empty", detail=f"job {job_id} not found in 'queued' state")
            ext_id = ""
            if row["dedup_token"] and "|" in row["dedup_token"]:
                ext_id = row["dedup_token"].split("|", 1)[1]
            job = {
                "id": str(row["id"]), "user_id": user_id, "job_id": None,
                "company": row["company"] or "", "title": row["role"] or "",
                "ats": row["ats"] or "", "source": row["source"] or "",
                "apply_url": row["url"] or "", "location": row["location"] or "",
                "posted_at": row["posted_at"], "scouted_at": row["scouted_at"],
                "external_id": ext_id,
                "application_profile_id": row["application_profile_id"],
                "_local": True,
            }
        else:
            job = claim_next_job_locally(user_id, WORKER_ID)
    except WorkerAuthError as e:
        return _make_outcome("auth_expired", error=str(e))
    except Exception as e:
        return _make_outcome("error", error=f"claim failed: {e}")
    if not job:
        return _make_outcome("empty")

    company = job.get("company", "")
    apply_url = job.get("apply_url", "")
    ats = (job.get("ats") or "").lower()
    title = job.get("title", "")
    update_heartbeat(user_id, "applying", f"{company} — {title}")
    update_local_status(job, "applying")

    # ── Preflight: blocked URL / company / staffing / rate / daily ──
    if is_blocked_url(apply_url):
        update_queue_status(job["id"], "cancelled", error="blocked aggregator domain")
        update_local_status(job, "skipped", "blocked aggregator domain")
        return _make_outcome("skipped", job=job, detail="blocked aggregator domain")
    if is_blocked_company(company, tenant=tenant):
        update_queue_status(job["id"], "cancelled", error="blocked company")
        update_local_status(job, "skipped", "blocked company")
        return _make_outcome("skipped", job=job, detail="blocked company")
    if is_staffing_agency(company):
        update_queue_status(job["id"], "cancelled", error="staffing agency")
        update_local_status(job, "skipped", "staffing agency")
        return _make_outcome("skipped", job=job, detail="staffing agency")
    if not check_company_rate_locally(user_id, company):
        update_queue_status(job["id"], "cancelled", error="company rate limit")
        update_local_status(job, "skipped", "company rate limit (3/7d)")
        return _make_outcome("skipped", job=job, detail="company rate limit")
    if is_paused_company(company):
        update_queue_status(job["id"], "pending", error="company paused")
        return _make_outcome("skipped", job=job, detail="company paused")
    if not check_daily_limit_locally(user_id, tenant.daily_apply_limit):
        update_queue_status(job["id"], "pending")
        return _make_outcome("skipped", job=job, detail="daily limit reached")

    # ── Profile preflight (same checks daemon does) ────────────────
    try:
        raw_bundle = load_user_profile(user_id) or {}
    except WorkerAuthError as e:
        return _make_outcome("auth_expired", job=job, error=str(e))
    except Exception:
        raw_bundle = {}
    pf = raw_bundle.get("profile") or {}
    missing = [f for f in ("first_name", "last_name", "email") if not (pf.get(f) or "").strip()]
    if missing:
        update_queue_status(job["id"], "pending", error=f"awaiting_profile ({', '.join(missing)})")
        update_local_status(job, "queued", "awaiting profile completion")
        return _make_outcome("profile_gap", job=job, detail=f"missing: {', '.join(missing)}")
    try:
        prefs = fetch_user_job_preferences(user_id) or {}
    except Exception:
        prefs = {}
    if not (prefs.get("target_titles") or []):
        update_queue_status(job["id"], "pending", error="no target_titles")
        return _make_outcome("profile_gap", job=job, detail="target_titles empty")

    # ── Dispatch: recipe or brain handoff ──────────────────────────
    ApplierClass = APPLIERS.get(ats)
    if not ApplierClass:
        # No coded recipe — hand to brain. Notes prefix is the marker
        # queue_claim_brain_fallback looks for. Status 'skipped' so
        # the daemon doesn't re-claim its own brain-pending work.
        update_queue_status(job["id"], "pending", error=f"awaiting_brain:{ats}")
        update_local_status(job, "skipped", f"awaiting_brain:{ats}")
        update_heartbeat(user_id, "handed_to_brain", f"{company} — no recipe for {ats}")
        return _make_outcome(
            "handoff", job=job,
            handoff_reason="no_recipe",
            detail=f"no coded applier for ATS '{ats}' — drive manually then call knowledge_record_pattern",
        )

    # Resolve bundle for the recipe (matches daemon's selection logic).
    try:
        tagged_pid = job.get("application_profile_id")
        bundle = (
            tenant.profile_by_id(tagged_pid) if tagged_pid else None
        ) or tenant.pick_profile_for_job(title, company, job.get("location", "")) \
          or tenant.default_profile()
    except Exception as e:
        update_queue_status(job["id"], "failed", error=f"bundle resolve: {e}")
        update_local_status(job, "failed", f"bundle resolve: {e}")
        return _make_outcome("error", job=job, error=f"bundle resolve: {e}")

    # Resume — bundle's signed URL first, fallback to legacy
    # download_resume(user_id, title) which respects the user's resumes
    # picker. Awaiting-upload state mirrors daemon behavior: row goes
    # back to 'pending' with the well-known marker.
    try:
        if getattr(bundle, "resume_signed_url", None):
            resume_path = download_resume_by_url(
                bundle.resume_signed_url,
                getattr(bundle, "resume_file_name", None) or "resume.pdf",
                cache_key=getattr(bundle, "id", "")[:8] or "default",
            )
        else:
            resume_path = download_resume(user_id, title)
    except WorkerAuthError as e:
        return _make_outcome("auth_expired", job=job, error=str(e))
    except Exception as e:
        msg = str(e).lower()
        if "no resume" in msg or "resume not found" in msg:
            update_queue_status(job["id"], "pending", error="awaiting_resume_upload")
            update_local_status(job, "queued", "awaiting resume upload")
            return _make_outcome("profile_gap", job=job, detail="resume not uploaded")
        update_queue_status(job["id"], "failed", error=f"resume download: {e}")
        update_local_status(job, "failed", f"resume download: {e}")
        return _make_outcome("error", job=job, error=f"resume download: {e}")

    # Build profile + answer_key the same way daemon does so brain
    # invocation gives identical applier behavior.
    try:
        profile_obj = load_user_profile(user_id) or {}
        # Merge bundle overrides for work history (mig 020).
        if getattr(bundle, "work_experience", None) is not None:
            profile_obj = {**profile_obj, "work_experience": bundle.work_experience}
        if getattr(bundle, "education", None) is not None:
            profile_obj = {**profile_obj, "education": bundle.education}
        if getattr(bundle, "skills", None) is not None:
            profile_obj = {**profile_obj, "skills": bundle.skills}
        global_tpl = load_global_template()
        answer_key = build_answer_key(
            profile_obj, global_tpl,
            profile_email=getattr(bundle, "application_email", None),
            bundle_answer_key=getattr(bundle, "answer_key_json", None),
        )
        applier = ApplierClass(
            profile_obj, answer_key, resume_path,
            profile_email=getattr(bundle, "application_email", None),
            profile_app_password=getattr(bundle, "application_email_app_password", None),
        )
    except MissingResumeError as e:
        update_queue_status(job["id"], "failed", error=f"resume missing: {e}")
        update_local_status(job, "failed", f"resume missing: {e}")
        log_application(user_id, job, {"status": "failed", "error": f"resume missing: {e}"})
        return _make_outcome("error", job=job, error=f"resume missing: {e}")
    except Exception as e:
        update_queue_status(job["id"], "failed", error=f"applier init: {e}")
        update_local_status(job, "failed", f"applier init: {e}")
        return _make_outcome("error", job=job, error=f"applier init: {e}")

    # Run the recipe. Marker tells preflight "an apply is driving this
    # Chrome session — do NOT deep-probe / restart the gateway". Cleared
    # in finally so a crash, success, or non-success all release it.
    # keep_awake.start() blocks Windows sleep during the apply (no-op on
    # Mac/Linux where jiggler.sh handles wake-state externally).
    import keep_awake as _keep_awake
    _write_apply_marker()
    _keep_awake.start()
    try:
        result = applier.apply(apply_url)
    except Exception as e:
        update_queue_status(job["id"], "failed", error=f"applier raised: {e}")
        update_local_status(job, "failed", f"applier raised: {e}")
        log_application(user_id, job, {"status": "failed", "error": f"applier raised: {e}"})
        return _make_outcome("error", job=job, error=f"applier raised: {e}")
    finally:
        _clear_apply_marker()
        _keep_awake.stop()

    if result.success:
        screenshot_url = None
        if result.screenshot:
            try:
                screenshot_url = upload_screenshot(user_id, result.screenshot)
            except Exception as e:
                logger.debug(f"screenshot upload failed: {e}")
        update_queue_status(job["id"], "submitted")
        log_application(user_id, job, {"status": "submitted", "screenshot_url": screenshot_url})
        try:
            send_application_result(
                user_id, job, result.screenshot,
                profile_name=getattr(bundle, "name", None) if len(tenant.profiles) > 1 else None,
                screenshot_url=screenshot_url,
            )
        except Exception as e:
            logger.debug(f"telegram notify failed: {e}")
        update_heartbeat(user_id, "applied", f"{company} — {title}")
        return _make_outcome("submitted", job=job, screenshot_url=screenshot_url)

    # Recipe returned non-success.
    if result.retriable:
        # Bump attempts and re-queue. Brain shouldn't drive retriable
        # fails (they need transient recovery, not intelligence).
        prior = int(job.get("attempts") or 0)
        max_attempts = int(job.get("max_attempts") or 3)
        new_attempts = prior + 1
        if new_attempts < max_attempts:
            update_queue_status(job["id"], "pending", error=result.error, attempts=new_attempts)
            update_local_status(job, "queued", f"retry {new_attempts}/{max_attempts}: {str(result.error)[:120]}")
            return _make_outcome(
                "skipped", job=job,
                detail=f"retriable {new_attempts}/{max_attempts}: {str(result.error)[:160]}",
            )

    # Non-retriable (or out of retries) — brain fallback or hard fail.
    if enable_brain_fallback:
        marker = f"awaiting_brain:recipe_failed:{ats}:{str(result.error)[:120]}"
        update_queue_status(job["id"], "pending", error=marker)
        update_local_status(job, "skipped", marker)
        update_heartbeat(user_id, "handed_to_brain", f"{company} — recipe failed, brain takes over")
        return _make_outcome(
            "handoff", job=job,
            handoff_reason="recipe_failed",
            error=result.error,
            detail=f"recipe failed for {ats}; browser left on failed page; brain should take over",
        )

    # No fallback — hard fail (matches daemon's pre-fallback behavior).
    fail_screenshot_url = None
    if result.screenshot:
        try:
            fail_screenshot_url = upload_screenshot(user_id, result.screenshot)
        except Exception as e:
            logger.debug(f"failure screenshot upload failed: {e}")
    update_queue_status(job["id"], "failed", error=result.error)
    update_local_status(job, "failed", result.error)
    log_application(
        user_id, job,
        {"status": "failed", "error": result.error, "screenshot_url": fail_screenshot_url},
    )
    try:
        send_failure(
            user_id, company, title, result.error,
            screenshot_path=result.screenshot, screenshot_url=fail_screenshot_url,
        )
    except Exception:
        pass
    return _make_outcome(
        "error", job=job, error=result.error,
        screenshot_url=fail_screenshot_url,
    )
