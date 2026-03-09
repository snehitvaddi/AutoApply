import os
import logging
from datetime import datetime, timezone
from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, RESUME_DIR

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


def claim_next_job(worker_id: str) -> dict | None:
    """Claim next pending job and enrich with discovered_jobs data."""
    client = get_client()
    result = client.rpc("claim_next_job", {"p_worker_id": worker_id}).execute()
    if not result.data or len(result.data) == 0:
        return None

    queue_row = result.data[0]

    # Fetch job details from discovered_jobs
    job_detail = (
        client.table("discovered_jobs")
        .select("*")
        .eq("id", queue_row["job_id"])
        .single()
        .execute()
    )
    if job_detail.data:
        queue_row["ats"] = job_detail.data.get("ats", "greenhouse")
        queue_row["apply_url"] = job_detail.data.get("apply_url", "")
        queue_row["company"] = job_detail.data.get("company", "")
        queue_row["title"] = job_detail.data.get("title", "")
        queue_row["posted_at"] = job_detail.data.get("posted_at")
        queue_row["location"] = job_detail.data.get("location")

    return queue_row


def load_user_profile(user_id: str) -> dict:
    """Fetch user record joined with profile and resumes."""
    client = get_client()
    user = (
        client.table("users")
        .select("*")
        .eq("id", user_id)
        .single()
        .execute()
    )
    profile = (
        client.table("user_profiles")
        .select("*")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    resumes = (
        client.table("user_resumes")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    return {
        "user": user.data,
        "profile": profile.data,
        "resumes": resumes.data or [],
    }


def update_queue_status(queue_id: str, status: str, error: str | None = None):
    """Update application_queue row status."""
    client = get_client()
    update_data: dict = {"status": status}
    if error:
        update_data["error"] = error

    client.table("application_queue").update(update_data).eq("id", queue_id).execute()


def log_application(user_id: str, job: dict, result: dict):
    """Insert a record into the applications table."""
    client = get_client()
    client.table("applications").insert({
        "user_id": user_id,
        "job_id": job.get("job_id"),
        "queue_id": job.get("id"),
        "company": job.get("company", ""),
        "title": job.get("title", ""),
        "ats": job.get("ats", ""),
        "apply_url": job.get("apply_url", ""),
        "status": result.get("status", "submitted"),
        "screenshot_url": result.get("screenshot_url"),
        "error": result.get("error"),
    }).execute()


def get_user_telegram_chat_id(user_id: str) -> str | None:
    """Return the Telegram chat_id for a user, if configured."""
    client = get_client()
    result = (
        client.table("users")
        .select("telegram_chat_id")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if result.data:
        return result.data.get("telegram_chat_id")
    return None


def upload_screenshot(user_id: str, screenshot_path: str) -> str | None:
    """Upload a screenshot to Supabase storage and return the public URL."""
    client = get_client()
    filename = os.path.basename(screenshot_path)
    storage_path = f"{user_id}/{filename}"
    try:
        with open(screenshot_path, "rb") as f:
            client.storage.from_("screenshots").upload(
                storage_path, f, {"content-type": "image/png"}
            )
        url = client.storage.from_("screenshots").get_public_url(storage_path)
        return url
    except Exception as e:
        logger.error(f"Failed to upload screenshot: {e}")
        return None


def download_resume(user_id: str, job_title: str | None = None) -> str:
    """Download the user's default resume to a local path and return the path."""
    client = get_client()
    os.makedirs(RESUME_DIR, exist_ok=True)

    resumes = (
        client.table("user_resumes")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    resume = None
    if resumes.data:
        if job_title:
            for r in resumes.data:
                keywords = r.get("target_keywords") or []
                if any(kw.lower() in job_title.lower() for kw in keywords):
                    resume = r
                    break
        if not resume:
            for r in resumes.data:
                if r.get("is_default"):
                    resume = r
                    break
        if not resume:
            resume = resumes.data[0]

    if not resume:
        raise ValueError(f"No resume found for user {user_id}")

    storage_path = resume["storage_path"]
    local_path = os.path.join(RESUME_DIR, f"{user_id}_{resume['file_name']}")

    if not os.path.exists(local_path):
        data = client.storage.from_("resumes").download(storage_path)
        with open(local_path, "wb") as f:
            f.write(data)
        logger.info(f"Downloaded resume to {local_path}")

    return local_path


def check_daily_limit(user_id: str) -> bool:
    """Return True if the user has not exceeded their daily application limit."""
    client = get_client()
    user = (
        client.table("users")
        .select("daily_apply_limit")
        .eq("id", user_id)
        .single()
        .execute()
    )
    limit = (user.data or {}).get("daily_apply_limit", 5)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count_result = (
        client.table("applications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .gte("applied_at", f"{today}T00:00:00Z")
        .execute()
    )
    current_count = count_result.count or 0
    return current_count < limit


def get_answer_key(user_id: str) -> dict:
    """Fetch the user's answer_key_json from user_profiles."""
    client = get_client()
    result = (
        client.table("user_profiles")
        .select("answer_key_json")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return (result.data or {}).get("answer_key_json") or {}


def get_global_knowledge(key: str) -> dict | None:
    """Fetch a value from the knowledge_base table by key."""
    client = get_client()
    result = (
        client.table("knowledge_base")
        .select("value")
        .eq("key", key)
        .single()
        .execute()
    )
    if result.data:
        return result.data.get("value")
    return None
