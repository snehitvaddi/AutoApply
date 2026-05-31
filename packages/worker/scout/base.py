"""ScoutSource — the plugin contract every scout implementation must follow.

The whole point of this abstraction is to separate "mechanism R&D" (the code
for scraping Dice, LinkedIn, etc. — shared across all tenants) from "role
R&D" (what to search for — strictly per-tenant data). Admin writes a new
ScoutSource subclass once, every tenant benefits with their own criteria.

Contract (enforced by tests/test_scout_contract.py):
  - .scout(tenant) MUST read queries from tenant.search_queries / .linkedin_seed_queries
  - .scout(tenant) MUST call tenant.passes_filter() before returning jobs
  - .scout(tenant) MUST NOT contain hardcoded role strings like "AI Engineer"
  - .scout(tenant) MUST tag each returned JobPost with .source == self.name
  - .scout(tenant) MUST handle its own errors and never raise up to the caller
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from tenant import TenantConfig


class JobPost(TypedDict, total=False):
    """Canonical job payload a scout source must return."""
    title: str
    company: str
    location: str
    apply_url: str
    external_id: str
    ats: str
    source: str  # populated by dispatcher; sources don't set this themselves
    posted_at: str
    posted_text: str
    # Right-pane fields — populated by deep extractors (e.g. LinkedIn
    # scroll scout's card-body click). Optional and best-effort: empty
    # string when the source can't supply it. Consumers MUST tolerate
    # missing keys.
    description: str
    applicants: str


class ScoutSource(ABC):
    """Abstract scout plugin.

    Subclasses override .scout(). The dispatcher in worker.run_scout_cycle
    calls .is_enabled_for(tenant) to decide whether to run this source for
    a given tenant (e.g. LinkedIn disabled unless session cookie exists),
    then calls .scout(tenant) and tags results with self.name.
    """

    name: str = "unknown"
    priority: str = "low"  # "high" | "medium" | "low"
    requires_auth: bool = False

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"scout.{self.name}")
        # Per-run diagnostics — populated by .scout() so the MCP tool can
        # distinguish "0 jobs because nothing new" from "0 jobs because every
        # board fetch raised ConnectError". Reset at the start of each
        # .scout() call. Sources that don't track fetches leave these at
        # defaults (no failures recorded ≠ "everything was fine", just "this
        # source doesn't expose fetch-level diagnostics").
        self.last_attempts: int = 0
        self.last_failures: int = 0
        self.last_error: str | None = None

    @abstractmethod
    def scout(self, tenant: "TenantConfig") -> list[JobPost]:
        """Query this source using THIS tenant's criteria. Must never use
        admin defaults or hardcoded role keywords. Implementations should
        catch all their own exceptions and return [] on failure so a single
        source never crashes the whole scout cycle."""
        ...

    def is_enabled_for(self, tenant: "TenantConfig") -> bool:
        """Override to gate on tenant-specific capabilities (e.g. LinkedIn
        session cookie present). Default: always enabled."""
        return True
