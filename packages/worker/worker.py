import time
import signal
import logging
import subprocess
from datetime import date
from urllib.parse import urlparse
from config import (
    WORKER_ID, POLL_INTERVAL, APPLY_COOLDOWN, ATS_COOLDOWNS,
    MAX_SYSTEM_APPS_PER_HOUR, BLOCKED_DOMAINS, COMPANY_PAUSES, BLOCKED_COMPANIES,
)
from db import claim_next_job, load_user_profile, update_queue_status, log_application, check_daily_limit, get_answer_key, download_resume, upload_screenshot
from notifier import send_application_result, send_failure
from knowledge import build_answer_key, load_global_template
from applier.greenhouse import GreenhouseApplier
from applier.lever import LeverApplier
from applier.ashby import AshbyApplier
from applier.smartrecruiters import SmartRecruitersApplier

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger(f'worker-{WORKER_ID}')

APPLIERS = {
    'greenhouse': GreenhouseApplier,
    'lever': LeverApplier,
    'ashby': AshbyApplier,
    'smartrecruiters': SmartRecruitersApplier,
}

running = True


def shutdown(signum, frame):
    global running
    logger.info("Shutdown signal received")
    running = False


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


def is_blocked_url(apply_url: str) -> bool:
    """Check if the apply URL is from a known aggregator/spam domain."""
    try:
        host = urlparse(apply_url).hostname or ""
        return any(domain in host for domain in BLOCKED_DOMAINS)
    except Exception:
        return False


def is_paused_company(company: str) -> bool:
    """Check if the company is temporarily paused."""
    company_lower = (company or "").lower().strip()
    pause_until = COMPANY_PAUSES.get(company_lower)
    if pause_until and date.today() < pause_until:
        return True
    return False


def is_blocked_company(company: str) -> bool:
    """Check if the company is permanently blocked (defense/clearance)."""
    company_lower = (company or "").lower().strip()
    return any(blocked in company_lower for blocked in BLOCKED_COMPANIES)


def restart_browser_gateway() -> bool:
    """Restart OpenClaw browser gateway after a timeout/crash."""
    try:
        subprocess.run("openclaw gateway restart", shell=True, timeout=15, capture_output=True)
        time.sleep(3)
        r = subprocess.run("openclaw gateway status", shell=True, timeout=5, capture_output=True, text=True)
        if "running" in r.stdout.lower():
            logger.info("Browser gateway restarted successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to restart browser gateway: {e}")
    return False


def main():
    logger.info(f"Worker {WORKER_ID} starting...")
    global_template = load_global_template()
    hourly_count = 0
    hour_start = time.time()
    consecutive_timeouts = 0

    while running:
        # Reset hourly counter
        if time.time() - hour_start > 3600:
            hourly_count = 0
            hour_start = time.time()

        if hourly_count >= MAX_SYSTEM_APPS_PER_HOUR:
            logger.info("Hourly system limit reached, sleeping...")
            time.sleep(60)
            continue

        job = claim_next_job(WORKER_ID)
        if not job:
            time.sleep(POLL_INTERVAL)
            continue

        user_id = job['user_id']
        company = job.get('company', '')
        apply_url = job.get('apply_url', '')
        logger.info(f"Processing job {job['id']} for user {user_id}: {company}")

        # Pre-flight checks: blocked URL, paused/blocked company
        if is_blocked_url(apply_url):
            logger.info(f"Skipping blocked aggregator URL: {apply_url}")
            update_queue_status(job['id'], 'cancelled', error='blocked aggregator domain')
            continue

        if is_blocked_company(company):
            logger.info(f"Skipping blocked company: {company}")
            update_queue_status(job['id'], 'cancelled', error='blocked company (defense/clearance)')
            continue

        if is_paused_company(company):
            pause_until = COMPANY_PAUSES.get(company.lower().strip())
            logger.info(f"Skipping paused company {company} (until {pause_until})")
            update_queue_status(job['id'], 'pending', error=f'company paused until {pause_until}')
            continue

        # Check daily limit
        if not check_daily_limit(user_id):
            logger.info(f"User {user_id} daily limit reached, skipping")
            update_queue_status(job['id'], 'pending')  # put back
            time.sleep(5)
            continue

        try:
            profile = load_user_profile(user_id)
            answer_key = build_answer_key(profile, global_template)
            resume_path = download_resume(user_id, job.get('title'))

            # Get ATS-specific cooldown
            ats = job.get('ats', 'greenhouse')
            cooldown = ATS_COOLDOWNS.get(ats, APPLY_COOLDOWN)

            # Get the right applier
            ApplierClass = APPLIERS.get(ats)
            if not ApplierClass:
                update_queue_status(job['id'], 'failed', error=f'Unknown ATS: {ats}')
                continue

            applier = ApplierClass(profile, answer_key, resume_path)
            result = applier.apply(apply_url)

            if result.success:
                consecutive_timeouts = 0
                screenshot_url = None
                if result.screenshot:
                    screenshot_url = upload_screenshot(user_id, result.screenshot)
                update_queue_status(job['id'], 'submitted')
                log_application(user_id, job, {'status': 'submitted', 'screenshot_url': screenshot_url})
                send_application_result(user_id, job, result.screenshot)
                hourly_count += 1
            else:
                # Browser timeout recovery
                if result.error and "timeout" in result.error.lower():
                    consecutive_timeouts += 1
                    if consecutive_timeouts >= 3:
                        logger.warning("3 consecutive timeouts — restarting browser gateway")
                        restart_browser_gateway()
                        consecutive_timeouts = 0
                else:
                    consecutive_timeouts = 0

                if result.retriable and job.get('attempts', 0) < job.get('max_attempts', 3):
                    update_queue_status(job['id'], 'pending', error=result.error)
                else:
                    update_queue_status(job['id'], 'failed', error=result.error)
                    log_application(user_id, job, {'status': 'failed', 'error': result.error})
                    send_failure(user_id, company, job.get('title', ''), result.error)

            time.sleep(cooldown)

        except Exception as e:
            logger.exception(f"Error processing job {job['id']}")
            update_queue_status(job['id'], 'failed', error=str(e))
            time.sleep(10)


if __name__ == '__main__':
    main()
