import os
from datetime import date

# Supabase keys are no longer needed by the worker — all DB access goes through
# the API proxy at /api/worker/proxy using the worker token.
# These are kept for backward compatibility but default to empty.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
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

# ─── GLOBAL SAFETY FILTERS (always enforced, not per-user) ─────────────────

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
    "anduril", "anthropic", "bae systems", "booz allen", "cisco",
    "general dynamics", "l3harris", "langchain", "leidos",
    "lockheed martin", "meta", "northrop grumman", "palantir",
    "raytheon", "saic", "whoop",
]

# Staffing agencies — never apply (not direct employers)
BLOCKED_STAFFING = [
    "hackajob", "lensa", "jobright", "kforce", "dice", "collabera",
    "wiraa", "synergistic", "aditi", "hirenza", "jobot",
    "insight global", "teksystems", "mphasis", "data annotation",
]

# ─── Scout → Filter → Apply cycle config ────────────────────────────────────

SCOUT_INTERVAL_MINUTES = int(os.environ.get("SCOUT_INTERVAL_MINUTES", "30"))
MAX_COMPANY_APPS_PER_DAY = 2  # Max 2 per company per day (rank by fit, pick top 2)
MAX_COMPANY_APPS_PER_15_DAYS = 5  # Hard cap: 5 per company per 15-day window
JOB_TIMEOUT_SECONDS = 120  # Max time per application before skip

# ─── DEFAULT FILTERS (fallback when user has no preferences) ───────────────

# Skip these title levels
SKIP_LEVELS = ["lead", "principal", "staff", "director", "manager", "vp", "intern", "co-op"]

# Skip irrelevant role types (sales, legal, marketing, etc.)
SKIP_ROLE_KEYWORDS = [
    "sales", "account executive", "account manager", "business development",
    "sales development", "solutions architect",
    "legal", "counsel", "attorney", "paralegal",
    "marketing", "marketing analyst", "content", "copywriter", "social media",
    "recruiter", "talent acquisition", "people ops", "trainer",
    "designer", "product designer", "graphic design", "ux design",
    "security architect", "identity architect", "security engineer", "iam", "soc analyst",
    "datacenter", "electrical engineer", "facilities", "office manager",
    "customer success", "support engineer", "technical support",
]

# Short AI keywords that need word-boundary matching (to avoid "Retailer" matching "ai")
AI_KEYWORDS_SHORT = {"ai", "ml", "nlp", "llm", "genai"}

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
    "airwallex", "anyscale", "astronomer", "baseten", "benchling",
    "braintrust", "brellium", "character", "cognition", "cohere",
    "confluent", "cursor", "dandy", "decagon", "deepgram",
    "drata", "e2b", "factory", "graphite", "hackerone",
    "harvey", "hinge-health", "insitro", "llamaindex", "modal",
    "nomic", "norm-ai", "notion", "openai", "perplexity",
    "plaid", "poolside", "posthog", "primeintellect", "ramp",
    "reducto", "regard", "resend", "rogo", "sardine",
    "semgrep", "skydio", "snowflake", "socure", "sola",
    "suno", "trm-labs", "vanta", "whatnot", "windmill",
    "writer",
    # langchain is in BLOCKED_COMPANIES — excluded from scouting
]

# ─── Greenhouse reCAPTCHA map ────────────────────────────────────────────────

# These companies have NO reCAPTCHA — safe to auto-submit
GREENHOUSE_SUBMITTABLE = [
    "affirm", "airtable", "asana", "assemblyai", "attentive", "aurora",
    "benchling", "block", "brex", "calendly", "canva", "carta", "chime",
    "cloudflare", "cockroachlabs", "coinbase", "coursera", "cresta",
    "crowdstrike", "databricks", "datadog", "deel", "doordash", "drata",
    "elastic", "fastly", "figma", "fireworksai", "flexport", "forethought",
    "ginkgo", "gitlab", "gusto", "hashicorp", "headspace", "hebbia",
    "hightouch", "instacart", "intercom", "iterable", "justworks",
    "klaviyo", "labelbox", "lattice", "launchdarkly", "lyft", "marqeta",
    "mercury", "mixpanel", "mongodb", "motional", "moveworks", "netlify",
    "netskope", "newrelic", "notion", "nuro", "okta", "openai",
    "pagerduty", "postman", "ramp", "replicate", "rippling", "roblox",
    "root", "runway", "samsara", "sendbird", "sentinelone", "shopify",
    "snap", "snorkelai", "sofi", "springhealth", "squarespace", "stability",
    "tempus", "tenstorrent", "thumbtack", "together", "torcrobotics",
    "twilio", "upstart", "vanta", "vercel", "verkada", "waymo",
    "webflow", "wiz", "ziprecruiter",
]

# These companies HAVE reCAPTCHA — can fill form but submit may be blocked
GREENHOUSE_RECAPTCHA = [
    "abnormalsecurity", "amplitude", "braze", "discord",
    "duolingo", "faire", "gongio", "grammarly",
    "oura", "peloton", "pinterest", "reddit",
    "robinhood", "stripe", "toast", "togetherai",
    "twitch", "xometry",
]

# Combined list — used by scanner to discover ALL jobs
GREENHOUSE_ALL_BOARDS = GREENHOUSE_SUBMITTABLE + GREENHOUSE_RECAPTCHA
