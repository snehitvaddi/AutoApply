"""Himalayas scout plugin — wraps scanner.himalayas.scan_himalayas."""
from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.himalayas import scan_himalayas

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig


class HimalayasScout(ScoutSource):
    name = "himalayas"
    priority = "medium"
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        try:
            raw_jobs = scan_himalayas(list(tenant.search_queries))
        except Exception as e:
            self.logger.warning(f"Himalayas scout failed: {e}")
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
                "ats": j.get("ats", "himalayas"),
            })
        return filtered
