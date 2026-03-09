import os
from datetime import date

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
WORKER_ID = os.environ.get("WORKER_ID", f"worker-{os.getpid()}")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
APPLY_COOLDOWN = int(os.environ.get("APPLY_COOLDOWN", "30"))
RESUME_DIR = os.environ.get("RESUME_DIR", "/tmp/autoapply/resumes")
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/tmp/autoapply/screenshots")

ATS_COOLDOWNS = {
    "greenhouse": 30,
    "lever": 20,
    "ashby": 15,
    "smartrecruiters": 20,
}

MAX_SYSTEM_APPS_PER_HOUR = 60

# Aggregator/spam domains — jobs from these sites are never real employers
BLOCKED_DOMAINS = [
    "jobright.ai",
    "wiraa.com",
    "bestjobtool.com",
    "hirenza.com",
]

# Temporary company pauses — {company_name_lower: resume_date}
# Jobs from these companies are skipped until the resume date
COMPANY_PAUSES: dict[str, date] = {
    "stripe": date(2026, 3, 25),
    "ramp": date(2026, 6, 9),
}

# Defense/clearance companies — never apply (visa incompatible)
BLOCKED_COMPANIES = [
    "anduril", "palantir", "lockheed martin", "raytheon",
    "northrop grumman", "general dynamics", "l3harris",
    "booz allen", "leidos", "saic",
]
