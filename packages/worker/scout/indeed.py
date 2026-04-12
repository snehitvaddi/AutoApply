"""Indeed scout plugin — wraps scanner.indeed.scan_indeed with tenant queries."""
from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.indeed import scan_indeed

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig


class IndeedScout(ScoutSource):
    name = "indeed"
    priority = "medium"
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        try:
            # Indeed scanner takes a location string. Prefer the first
            # preferred_location; fall back to "United States" only if the
            # tenant didn't set any — and even then we still use the tenant's
            # own search_queries, never hardcoded role strings.
            loc = tenant.preferred_locations[0] if tenant.preferred_locations else "United States"
            raw_jobs = scan_indeed(list(tenant.search_queries), location=loc)
        except Exception as e:
            self.logger.warning(f"Indeed scout failed: {e}")
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
                "ats": j.get("ats", "indeed"),
            })
        return filtered
