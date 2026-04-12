"""Curated board slug lists — global default pools for scout sources.

These are the SOURCE pool (where to scrape), not a role opinion. Every tenant
defaults to this full list unless they explicitly override via
user_job_preferences.ashby_boards / greenhouse_boards. The filter layer in
TenantConfig.passes_filter() decides which jobs from these sources are
relevant per tenant — this file just answers "which companies to poll."

Adding a new board here automatically benefits every tenant.
"""
from __future__ import annotations

# ── Ashby boards (discovered via ashby board crawl) ─────────────────────────
DEFAULT_ASHBY_BOARDS: list[str] = [
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
    # langchain lives in DEFAULT_SECURITY_CLEARANCE_COMPANIES — excluded
]


# ── Greenhouse boards ───────────────────────────────────────────────────────
# Split between "submittable" (no recaptcha at apply time) and "recaptcha"
# (forms can be filled but submit may be gated). Scout hits both pools; the
# applier decides at apply time whether submit is feasible.
DEFAULT_GREENHOUSE_SUBMITTABLE: list[str] = [
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

DEFAULT_GREENHOUSE_RECAPTCHA: list[str] = [
    "abnormalsecurity", "amplitude", "braze", "discord",
    "duolingo", "faire", "gongio", "grammarly",
    "oura", "peloton", "pinterest", "reddit",
    "robinhood", "stripe", "toast", "togetherai",
    "twitch", "xometry",
]

DEFAULT_GREENHOUSE_BOARDS: list[str] = (
    DEFAULT_GREENHOUSE_SUBMITTABLE + DEFAULT_GREENHOUSE_RECAPTCHA
)
