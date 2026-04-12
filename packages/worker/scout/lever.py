"""Lever scout plugin — wraps scanner.lever.scan_lever_boards."""
from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.lever import scan_lever_boards

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig

# Default Lever company slugs — curated global pool, same pattern as
# Ashby/Greenhouse. Each tenant uses the full pool; the filter layer
# decides what's relevant per tenant's target_titles.
DEFAULT_LEVER_COMPANIES: list[str] = [
    "netflix", "figma", "stripe", "coinbase", "notion",
    "reddit", "discord", "datadog", "cloudflare", "plaid",
    "airtable", "webflow", "vercel", "linear", "dbt-labs",
    "anyscale", "weights-and-biases", "hugging-face",
    "scale-ai", "labelbox", "snorkel-ai",
    "cruise", "nuro", "aurora-innovation",
    "grammarly", "duolingo", "quora",
]


class LeverScout(ScoutSource):
    name = "lever"
    priority = "high"
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        try:
            raw_jobs = scan_lever_boards(DEFAULT_LEVER_COMPANIES)
        except Exception as e:
            self.logger.warning(f"Lever scout failed: {e}")
            return []

        filtered: list[JobPost] = []
        for j in raw_jobs:
            title = j.get("title", "")
            company = j.get("company", "")
            location = j.get("location", "")
            if not tenant.passes_filter(title, company, location):
                continue
            filtered.append({
                "title": title,
                "company": company,
                "location": location,
                "apply_url": j.get("apply_url", "") or j.get("url", ""),
                "external_id": str(j.get("external_id") or j.get("id") or ""),
                "ats": "lever",
            })
        return filtered
