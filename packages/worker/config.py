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
    "mygwork.com",
    "haystackapp.io",
    "indeed.com",
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
    "bae systems", "langchain", "meta", "whoop",
]

# Staffing agencies — never apply (not direct employers)
BLOCKED_STAFFING = [
    "hackajob", "lensa", "jobright", "kforce", "dice", "collabera",
    "wiraa", "synergistic", "aditi", "hirenza", "jobot",
    "insight global", "teksystems", "mphasis", "data annotation",
]

# ─── Scout → Filter → Apply cycle config ────────────────────────────────────

SCOUT_INTERVAL_MINUTES = int(os.environ.get("SCOUT_INTERVAL_MINUTES", "30"))
MAX_COMPANY_APPS_PER_30_DAYS = 5

# Skip these title levels
SKIP_LEVELS = ["lead", "principal", "staff", "director", "manager", "vp", "intern", "co-op"]

# Skip Senior roles at FAANG/big tech (Senior at startups is OK)
SKIP_COMPANIES_SENIOR = [
    "google", "meta", "amazon", "apple", "microsoft",
    "netflix", "nvidia", "uber", "airbnb",
]

# AI/ML keywords — title must contain at least one to qualify
AI_KEYWORDS = [
    "ai", "ml", "machine learning", "data scientist", "nlp", "genai", "llm",
    "deep learning", "computer vision", "mlops", "artificial intelligence",
    "inference", "training", "neural",
]

# Non-US locations — skip jobs with these in location string
SKIP_LOCATIONS = [
    "india", "bengaluru", "dublin", "amsterdam", "japan", "sydney",
    "mexico", "paris", "brazil", "london", "berlin", "singapore",
    "canada", "vancouver",
]

# ─── Ashby board slugs (all discovered) ─────────────────────────────────────

ASHBY_SLUGS = [
    "brellium", "sola", "norm-ai", "poolside", "primeintellect", "reducto",
    "perplexity", "cohere", "modal", "baseten", "anyscale", "notion",
    "writer", "llamaindex", "skydio", "insitro", "harvey", "plaid",
    "cognition", "semgrep", "braintrust", "astronomer", "hackerone",
    "cursor", "ramp", "resend", "deepgram", "openai", "airwallex",
    "regard", "confluent", "benchling", "drata", "whatnot", "snowflake",
    "vanta", "e2b", "graphite", "character", "rogo", "suno", "causal",
    "windmill", "socure", "posthog", "trm-labs", "nomic", "hinge-health",
    "decagon", "dandy", "factory", "sardine",
]

# ─── Greenhouse reCAPTCHA map ────────────────────────────────────────────────

# These companies have NO reCAPTCHA — safe to auto-submit
GREENHOUSE_NO_RECAPTCHA = [
    "coinbase", "figma", "datadog", "torcrobotics",
    "springhealth", "headspace", "flexport", "nuro", "waymo", "aurora",
    "affirm", "chime", "upstart", "verkada", "samsara",
    "snap", "instacart", "doordash", "shopify", "calendly",
]

# These companies HAVE reCAPTCHA — can fill form but submit may be blocked
GREENHOUSE_RECAPTCHA = [
    "stripe", "robinhood", "pinterest", "discord", "reddit",
    "togetherai", "gongio", "abnormalsecurity", "xometry",
    "faire", "duolingo", "oura", "amplitude", "braze",
    "grammarly", "twitch", "toast", "peloton",
]
