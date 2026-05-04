"""Lever scout plugin — wraps scanner.lever.scan_lever_boards.

Honors `tenant.lever_boards` (per-tenant override) and falls back to the
global pool in `default_boards.DEFAULT_LEVER_BOARDS`. Mirrors the
Ashby/Greenhouse override semantics so all three scouts feel the same.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from default_boards import DEFAULT_LEVER_BOARDS
from scanner.lever import scan_lever_boards

from .base import JobPost, ScoutSource

if TYPE_CHECKING:
    from tenant import TenantConfig


class LeverScout(ScoutSource):
    name = "lever"
    priority = "high"
    requires_auth = False

    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        # Tenant override wins; fall back to the curated global pool.
        slugs = list(getattr(tenant, "lever_boards", None) or []) or list(DEFAULT_LEVER_BOARDS)
        if not slugs:
            return []
        try:
            raw_jobs = scan_lever_boards(slugs)
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
            # scanner.lever already converts createdAt → posted_at ISO;
            # forward it so the freshness rule has a real signal.
            filtered.append({
                "title": title,
                "company": company,
                "location": location,
                "apply_url": j.get("apply_url", "") or j.get("url", ""),
                "external_id": str(j.get("external_id") or j.get("id") or ""),
                "ats": "lever",
                "posted_at": j.get("posted_at") or None,
            })
        return filtered
