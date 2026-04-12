"""LinkedIn public scout plugin — wraps scanner.linkedin.scan_linkedin.

This does NOT include the authenticated scraper at linkedin/li-mega-scrape.py —
that one requires a session cookie and is still in the old ad-hoc shape.
If a tenant opts into LinkedIn-auth scraping (via a future setting), a second
plugin can be added here that gates on tenant.linkedin_session_cookie.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.linkedin import scan_linkedin

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig


class LinkedInPublicScout(ScoutSource):
    name = "linkedin_public"
    priority = "medium"
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        try:
            loc = tenant.preferred_locations[0] if tenant.preferred_locations else "United States"
            raw_jobs = scan_linkedin(list(tenant.linkedin_seed_queries), location=loc)
        except Exception as e:
            self.logger.warning(f"LinkedIn scout failed: {e}")
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
                "ats": j.get("ats", "linkedin"),
            })
        return filtered
