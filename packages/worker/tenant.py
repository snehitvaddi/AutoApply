"""TenantConfig — single source of truth for per-user pipeline configuration.

Every opinionated decision in the scout → filter → apply path flows through
this object. No function in the worker should read admin defaults; they all
read from a TenantConfig instance loaded at boot from the cloud API.

Design rules (enforced by tests/test_scout_contract.py):
  1. No hardcoded role strings anywhere in the scout/filter pipeline.
  2. No "system" user_id sentinel — every path has a real tenant.
  3. No silent fallback to admin defaults. If tenant config is incomplete,
     worker boot fails loudly with TenantConfigIncompleteError so the user
     knows to finish setup instead of silently scouting the wrong roles.
  4. Frozen dataclass — once loaded, tenant data can't be mutated mid-run.

Loaded via TenantConfig.load(user_id) which hits
/api/worker/proxy?action=get_tenant_config (added in the same change as
this module). The API resolves user_profiles + user_job_preferences +
default resume in a single round trip.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from default_boards import DEFAULT_ASHBY_BOARDS, DEFAULT_GREENHOUSE_BOARDS

logger = logging.getLogger(__name__)


class TenantConfigIncompleteError(RuntimeError):
    """Raised when a tenant hasn't finished setup and the worker can't run
    for them. Carries a human-readable `reason` that gets surfaced to the
    user via chat + Telegram so they know what to fix. Never caught by a
    bare except — the worker is supposed to exit so the user sees it."""

    def __init__(self, user_id: str, missing: list[str]):
        self.user_id = user_id
        self.missing = missing
        msg = (
            f"Tenant {user_id[:8]} is not fully configured — missing: "
            f"{', '.join(missing)}. Finish setup at Settings → Preferences."
        )
        super().__init__(msg)


# ── Global safety constants (legal/universal truths, NOT role opinions) ───
# These are the ONLY hardcoded filter rules. Role/level/location opinions
# belong on the tenant, not here.

# Companies that require US security clearance. Only applied to tenants
# whose work_auth blocks them ("opt", "h1b"). Citizens/green-card holders
# can apply freely. This replaces the old BLOCKED_COMPANIES constant which
# was applied to everyone regardless of visa status.
DEFAULT_SECURITY_CLEARANCE_COMPANIES: list[str] = [
    "anduril", "anthropic", "bae systems", "booz allen", "cisco",
    "general dynamics", "l3harris", "langchain", "leidos",
    "lockheed martin", "meta", "northrop grumman", "palantir",
    "raytheon", "saic", "whoop",
]


@dataclass(frozen=True)
class TenantConfig:
    """Frozen per-tenant configuration for scout/filter/apply.

    Every field is populated from the cloud API at boot — no fallbacks,
    no defaults baked in. Adding a new config field means:
      1. Add a column to user_job_preferences
      2. Add a field here
      3. Include it in /api/worker/proxy?action=get_tenant_config response
      4. Code that consumes it just reads tenant.new_field
    """
    user_id: str

    # Scout-side
    search_queries: tuple[str, ...]           # from target_titles
    linkedin_seed_queries: tuple[str, ...]    # == search_queries (distinct name for clarity)
    ashby_boards: tuple[str, ...]             # tenant override OR global default
    greenhouse_boards: tuple[str, ...]        # tenant override OR global default

    # Filter-side
    keyword_filter: tuple[str, ...]           # target_keywords OR target_titles lowered
    excluded_role_keywords: tuple[str, ...]   # user-defined, default ()
    excluded_levels: tuple[str, ...]          # user-defined, default ()
    excluded_companies: tuple[str, ...]       # user list + visa-dependent clearance list
    preferred_locations: tuple[str, ...]      # user list; () = no geo filter
    remote_only: bool

    # Apply-side
    min_salary: int | None
    work_auth: str                            # "citizen" | "gc" | "opt" | "h1b" | "unknown"
    requires_sponsorship: bool
    daily_apply_limit: int

    # Full profile + answer key — passed verbatim into BaseApplier
    profile: dict                             # full user_profiles row
    answer_key: dict                          # EEO + standard Q&A

    # Metadata
    tenant_name: str                          # "first_name last_name" for logging/prompts
    tenant_email: str
    complete: bool                            # False → setup unfinished; worker refuses to run

    # ── Loader ─────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, user_id: str) -> "TenantConfig":
        """Load via the worker proxy. Raises TenantConfigIncompleteError
        if the user hasn't finished setup. Never returns a half-loaded
        object — fail fast is the whole point."""
        # Late import to avoid circular: db.py imports config, tenant is
        # imported by worker.py which also imports db.
        from db import _api_call

        raw = _api_call("get_tenant_config")
        if not raw:
            raise TenantConfigIncompleteError(user_id, ["api_unreachable"])

        profile = raw.get("profile") or {}
        prefs = raw  # get_tenant_config flattens prefs into top-level

        target_titles = [t.strip() for t in (prefs.get("search_queries") or []) if t and t.strip()]
        target_keywords = [k.strip() for k in (prefs.get("keyword_filter") or []) if k and k.strip()]
        preferred_locations = [loc.strip() for loc in (prefs.get("preferred_locations") or []) if loc and loc.strip()]

        # Board overrides: None/empty-list from API → use global default
        raw_ashby = prefs.get("ashby_boards")
        ashby_boards = tuple(raw_ashby) if raw_ashby else tuple(DEFAULT_ASHBY_BOARDS)
        raw_gh = prefs.get("greenhouse_boards")
        greenhouse_boards = tuple(raw_gh) if raw_gh else tuple(DEFAULT_GREENHOUSE_BOARDS)

        # Merge excluded_companies: user's list + visa-dependent clearance list
        user_excluded = [c.lower().strip() for c in (prefs.get("excluded_companies") or [])]
        work_auth = (profile.get("work_authorization") or "unknown").lower().strip()
        visa_blocked = work_auth in ("opt", "h1b", "f1", "tn", "l1", "l2", "opt-stem")
        if visa_blocked:
            excluded_companies = tuple(sorted(set(user_excluded + DEFAULT_SECURITY_CLEARANCE_COMPANIES)))
        else:
            excluded_companies = tuple(sorted(set(user_excluded)))

        # Completeness: must have at least one target_title + first_name + email
        missing: list[str] = []
        if not target_titles:
            missing.append("target_titles (Settings → Preferences → Target Roles)")
        if not profile.get("first_name"):
            missing.append("first_name (Settings → Personal)")
        if not profile.get("email") and not prefs.get("tenant_email"):
            missing.append("email (Settings → Personal)")

        tenant_name = f"{profile.get('first_name','')} {profile.get('last_name','')}".strip() or "unknown"
        tenant_email = prefs.get("tenant_email") or profile.get("email") or ""

        if missing:
            raise TenantConfigIncompleteError(user_id, missing)

        return cls(
            user_id=user_id,
            search_queries=tuple(target_titles),
            linkedin_seed_queries=tuple(target_titles),
            ashby_boards=ashby_boards,
            greenhouse_boards=greenhouse_boards,
            keyword_filter=tuple(target_keywords or [t.lower() for t in target_titles]),
            excluded_role_keywords=tuple(k.lower().strip() for k in (prefs.get("excluded_role_keywords") or []) if k),
            excluded_levels=tuple(k.lower().strip() for k in (prefs.get("excluded_levels") or []) if k),
            excluded_companies=excluded_companies,
            preferred_locations=tuple(preferred_locations),
            remote_only=bool(prefs.get("remote_only", False)),
            min_salary=prefs.get("min_salary"),
            work_auth=work_auth,
            requires_sponsorship=bool(profile.get("requires_sponsorship", True)),
            daily_apply_limit=int(prefs.get("daily_apply_limit", 25)),
            profile=profile,
            answer_key=profile.get("answer_key_json") or {},
            tenant_name=tenant_name,
            tenant_email=tenant_email,
            complete=True,
        )

    # ── Filter methods ─────────────────────────────────────────────────────

    def passes_filter(self, title: str, company: str, location: str) -> bool:
        """Tenant-scoped title/company/location filter. No admin fallback.

        A job passes iff:
          - title matches at least one keyword_filter entry (substring,
            with word-boundary for short tokens like "ai", "ml")
          - title doesn't contain any excluded_role_keywords
          - title doesn't contain any excluded_levels
          - company isn't in excluded_companies (which includes the visa-
            dependent clearance list)
          - location matches preferred_locations (if set) OR is remote
            (if remote_only) OR passes unconditionally (if neither set)
        """
        tl = (title or "").lower()
        cl = (company or "").lower()
        ll = (location or "").lower()

        # Keyword match — at least one positive hit required
        if not self.keyword_filter:
            # Should never happen (load() enforces non-empty), but fail closed
            return False
        if not any(_keyword_hit(kw, tl) for kw in self.keyword_filter):
            return False

        # Excluded role keywords (user-defined — replaces admin SKIP_ROLE_KEYWORDS)
        if any(kw in tl for kw in self.excluded_role_keywords):
            return False

        # Excluded seniority levels (user-defined — replaces admin SKIP_LEVELS)
        if any(lvl in tl for lvl in self.excluded_levels):
            return False

        # Excluded companies (user list + visa-blocked clearance list)
        if any(ec in cl for ec in self.excluded_companies):
            return False

        # Location filter — preferred_locations wins if set, then remote_only
        if self.preferred_locations:
            locs = [loc.lower() for loc in self.preferred_locations]
            if ll and not any(loc in ll for loc in locs):
                return False
        elif self.remote_only:
            if "remote" not in ll:
                return False
        # Neither preferred_locations nor remote_only set → no location filter

        return True

    def security_clearance_blocked(self, company: str) -> bool:
        """True iff this tenant is visa-blocked AND the company requires
        security clearance. US citizens / green-card holders get False."""
        work_auth = self.work_auth.lower()
        visa_blocked = work_auth in ("opt", "h1b", "f1", "tn", "l1", "l2", "opt-stem")
        if not visa_blocked:
            return False
        cl = (company or "").lower()
        return any(c in cl for c in DEFAULT_SECURITY_CLEARANCE_COMPANIES)

    def profile_summary_hint(self) -> str:
        """One-line summary for logging / mission prompts. Never includes PII
        beyond what's already in server logs (name + user_id prefix)."""
        roles = ", ".join(self.search_queries[:3])
        locs = ", ".join(self.preferred_locations[:2]) if self.preferred_locations else "any"
        return f"{self.tenant_name} ({self.user_id[:8]}) → {roles} in {locs}"


# ── Internal helpers ────────────────────────────────────────────────────────

# Short keywords need word-boundary matching to avoid false positives
# (e.g. "ai" shouldn't match "Retail Associate"). Longer keywords can use
# plain substring match.
_SHORT_KEYWORDS = frozenset({"ai", "ml", "nlp", "llm", "genai", "ux", "ui", "qa", "ios", "ba"})


def _keyword_hit(kw: str, text: str) -> bool:
    """Case-insensitive substring match with word-boundary protection for
    short keywords. Assumes text is already lowercased by caller."""
    kw = kw.lower().strip()
    if not kw:
        return False
    if kw in _SHORT_KEYWORDS or len(kw) <= 3:
        return bool(re.search(rf'\b{re.escape(kw)}\b', text))
    return kw in text
