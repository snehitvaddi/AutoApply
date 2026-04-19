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
class ApplyProfile:
    """A single application bundle within a tenant.

    Each bundle binds target roles + resume + apply-from email + app password
    + per-bundle answer key. The worker picks the matching bundle at apply
    time via TenantConfig.pick_profile_for_job(). Single-profile users have
    exactly one bundle with is_default=True.
    """
    id: str
    name: str
    slug: str
    is_default: bool

    target_titles: tuple[str, ...]
    target_keywords: tuple[str, ...]
    excluded_titles: tuple[str, ...]
    excluded_companies: tuple[str, ...]
    excluded_role_keywords: tuple[str, ...]
    excluded_levels: tuple[str, ...]
    preferred_locations: tuple[str, ...]
    remote_only: bool
    min_salary: int | None
    ashby_boards: tuple[str, ...]
    greenhouse_boards: tuple[str, ...]

    resume_path: str | None            # local cache path of resume PDF
    resume_file_name: str | None
    resume_signed_url: str | None      # cloud URL for lazy download
    # application_email / app_password: None signals "fall back to .env"
    # (install.sh's GMAIL_EMAIL / GMAIL_APP_PASSWORD). Empty string means
    # explicitly blank (which the worker should also treat as "no override").
    application_email: str | None
    application_email_app_password: str | None  # DECRYPTED — in-memory only

    auto_apply: bool
    max_daily: int | None

    # Per-bundle content (mig 019). None falls back to the tenant-wide
    # user_profiles.answer_key_json / cover_letter_template at the worker
    # level — older installs without migration 019 still work this way.
    answer_key_json: dict | None = None
    cover_letter_template: str | None = None
    # Per-bundle work history (mig 020). Each profile tells a different
    # story — AI Eng emphasizes ML projects, DA emphasizes SQL wins.
    # None falls back to user_profiles.work_experience / education / skills.
    work_experience: list | None = None
    education: list | None = None
    skills: list | None = None

    def passes_filter(self, title: str, company: str, location: str) -> bool:
        tl = (title or "").lower()
        cl = (company or "").lower()
        ll = (location or "").lower()
        kwf = self.target_keywords or tuple(t.lower() for t in self.target_titles)
        if not kwf:
            return False
        if not any(_keyword_hit(kw, tl) for kw in kwf):
            return False
        if any(kw in tl for kw in self.excluded_role_keywords):
            return False
        if any(lvl in tl for lvl in self.excluded_levels):
            return False
        if any(ex in tl for ex in self.excluded_titles):
            return False
        if any(ec in cl for ec in self.excluded_companies):
            return False
        if self.preferred_locations:
            locs = [loc.lower() for loc in self.preferred_locations]
            if ll and not any(loc in ll for loc in locs):
                # Intent-aware fallback. If the user asked for "United
                # States" / "USA" / "US", accept any location that LOOKS
                # US-ish — state codes (", CA", "CA,"), "remote", common
                # US metros. Before this, Ashby / Greenhouse / Lever jobs
                # returning "San Francisco, CA" were dropped 100% because
                # they don't contain the literal string "united states",
                # while LinkedIn (which injects "United States" into its
                # search) was the only source passing.
                if _wants_us(locs) and _is_us_location(ll):
                    return True
                return False
        elif self.remote_only:
            # Remote-only tenants: reject blank locations too. A missing
            # location field almost always means in-office.
            if not ll or "remote" not in ll:
                return False
        return True

    def match_score(self, title: str, company: str = "", location: str = "") -> float:
        """Score how well a job matches this bundle. 0.0 means no match
        (passes_filter=False). Higher = better. Ties broken by is_default
        at the TenantConfig level."""
        if not self.passes_filter(title, company, location):
            return 0.0
        tl = (title or "").lower()
        score = 0.0
        for t in self.target_titles:
            if t.lower() in tl:
                score += 2.0
        for kw in self.target_keywords:
            if kw.lower() in tl:
                score += 1.0
        # No baseline — if zero titles/keywords actually substring-hit the
        # title, this bundle does not claim the job. Previously we returned
        # 0.1 which let a DA bundle claim an "AI Engineer" job whenever
        # its excluded_role_keywords didn't explicitly blacklist "ai".
        return score


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

    # Application bundles (1..N). Single-profile users have exactly one
    # with is_default=True that mirrors the top-level fields above.
    profiles: tuple[ApplyProfile, ...] = ()

    # Metadata
    tenant_name: str = ""                     # "first_name last_name" for logging/prompts
    tenant_email: str = ""
    complete: bool = False                    # False → setup unfinished; worker refuses to run

    def default_profile(self) -> "ApplyProfile":
        for p in self.profiles:
            if p.is_default:
                return p
        if self.profiles:
            return self.profiles[0]
        raise TenantConfigIncompleteError(self.user_id, ["application_profile"])

    def profile_by_id(self, pid: str | None) -> "ApplyProfile | None":
        if not pid:
            return None
        for p in self.profiles:
            if p.id == pid:
                return p
        return None

    def pick_profile_for_job(self, title: str, company: str = "", location: str = "") -> "ApplyProfile | None":
        """Score each bundle, return the best match. Ties broken by is_default.
        Returns None if NO bundle accepts the job — caller should drop it
        (or fall back to default if default has a resume)."""
        if not self.profiles:
            return None
        scored = [(p.match_score(title, company, location), p) for p in self.profiles]
        scored = [(s, p) for (s, p) in scored if s > 0]
        if not scored:
            return None
        scored.sort(key=lambda sp: (sp[0], 1 if sp[1].is_default else 0), reverse=True)
        return scored[0][1]

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
        prefs = raw  # get_tenant_config flattens fields into top-level

        work_auth = (profile.get("work_authorization") or "unknown").lower().strip()
        visa_blocked = work_auth in ("opt", "h1b", "f1", "tn", "l1", "l2", "opt-stem")

        tenant_name = f"{profile.get('first_name','')} {profile.get('last_name','')}".strip() or "unknown"
        tenant_email = prefs.get("tenant_email") or profile.get("email") or ""

        # Build profiles[] FIRST — bundles are the source of truth after the
        # multi-profile refactor. The legacy top-level fields on `prefs` are
        # only a fallback for the auto-wrap path when cloud returned no
        # bundles (which now never happens post-backfill, but we keep the
        # path for robustness against deleted rows).
        raw_profiles = raw.get("profiles") or []
        profile_tuple: tuple[ApplyProfile, ...]
        if raw_profiles:
            profile_tuple = tuple(_build_apply_profile(rp, fallback_email=tenant_email) for rp in raw_profiles)
        else:
            # Legacy auto-wrap: build one default bundle from top-level prefs.
            legacy_titles = [t.strip() for t in (prefs.get("search_queries") or []) if t and t.strip()]
            legacy_keywords = [k.strip() for k in (prefs.get("keyword_filter") or []) if k and k.strip()]
            legacy_locs = [loc.strip() for loc in (prefs.get("preferred_locations") or []) if loc and loc.strip()]
            legacy_user_excluded = [c.lower().strip() for c in (prefs.get("excluded_companies") or [])]
            legacy_excluded_companies = (
                tuple(sorted(set(legacy_user_excluded + DEFAULT_SECURITY_CLEARANCE_COMPANIES)))
                if visa_blocked else tuple(sorted(set(legacy_user_excluded)))
            )
            raw_ashby = prefs.get("ashby_boards")
            legacy_ashby = tuple(raw_ashby) if raw_ashby else tuple(DEFAULT_ASHBY_BOARDS)
            raw_gh = prefs.get("greenhouse_boards")
            legacy_gh = tuple(raw_gh) if raw_gh else tuple(DEFAULT_GREENHOUSE_BOARDS)
            profile_tuple = (ApplyProfile(
                id=f"legacy-{user_id[:8]}",
                name="Default",
                slug="default",
                is_default=True,
                target_titles=tuple(legacy_titles),
                target_keywords=tuple(legacy_keywords),
                excluded_titles=(),
                excluded_companies=legacy_excluded_companies,
                excluded_role_keywords=tuple(k.lower().strip() for k in (prefs.get("excluded_role_keywords") or []) if k),
                excluded_levels=tuple(k.lower().strip() for k in (prefs.get("excluded_levels") or []) if k),
                preferred_locations=tuple(legacy_locs),
                remote_only=bool(prefs.get("remote_only", False)),
                min_salary=prefs.get("min_salary"),
                ashby_boards=legacy_ashby,
                greenhouse_boards=legacy_gh,
                resume_path=None,
                resume_file_name=None,
                resume_signed_url=None,
                application_email=None,  # fall through to .env GMAIL_EMAIL
                application_email_app_password=None,
                auto_apply=True,
                max_daily=None,
                # Legacy path: read content from user_profiles (shared) as
                # a safety net. Post-mig-019 every real user has a bundle
                # so this branch only runs when someone deletes their row.
                answer_key_json=(profile.get("answer_key_json") if isinstance(profile.get("answer_key_json"), dict) else None),
                cover_letter_template=(profile.get("cover_letter_template") or None),
                work_experience=(profile.get("work_experience") if isinstance(profile.get("work_experience"), list) else None),
                education=(profile.get("education") if isinstance(profile.get("education"), list) else None),
                skills=(profile.get("skills") if isinstance(profile.get("skills"), list) else None),
            ),)

        # Invariant: every loaded tenant has at least one bundle.
        assert profile_tuple, "TenantConfig.load: profile_tuple must be non-empty"

        # Derive top-level fields from bundles. The default bundle wins for
        # scalar fields (remote_only, min_salary, excluded_* — used only by
        # legacy passes_filter fallback). Lists are UNIONED across all
        # bundles for scout queries so every bundle's roles get scouted.
        default_bundle = next((p for p in profile_tuple if p.is_default), profile_tuple[0])

        union_titles: list[str] = []
        union_keywords: list[str] = []
        for p in profile_tuple:
            for t in p.target_titles:
                if t and t not in union_titles:
                    union_titles.append(t)
            for k in p.target_keywords:
                if k and k not in union_keywords:
                    union_keywords.append(k)
        # If a bundle has no target_keywords, its titles still drive filter
        # matches via the lowered-titles fallback in ApplyProfile.passes_filter.
        target_titles = union_titles
        target_keywords = union_keywords

        # Board overrides: take default bundle's override, else global list.
        ashby_boards = default_bundle.ashby_boards or tuple(DEFAULT_ASHBY_BOARDS)
        greenhouse_boards = default_bundle.greenhouse_boards or tuple(DEFAULT_GREENHOUSE_BOARDS)

        # Excluded companies: default bundle's list + visa-dependent clearance.
        user_excluded = [c.lower().strip() for c in default_bundle.excluded_companies]
        if visa_blocked:
            excluded_companies = tuple(sorted(set(user_excluded + DEFAULT_SECURITY_CLEARANCE_COMPANIES)))
        else:
            excluded_companies = tuple(sorted(set(user_excluded)))

        preferred_locations = list(default_bundle.preferred_locations)

        # Completeness checks. A bundle with zero target_titles is unusable.
        missing: list[str] = []
        if not target_titles:
            missing.append("target_titles (Settings → Profiles → Target Roles)")
        if not profile.get("first_name"):
            missing.append("first_name (Settings → Personal)")
        if not profile.get("email") and not tenant_email:
            missing.append("email (Settings → Personal)")
        if missing:
            raise TenantConfigIncompleteError(user_id, missing)

        return cls(
            user_id=user_id,
            search_queries=tuple(target_titles),
            linkedin_seed_queries=tuple(target_titles),
            ashby_boards=ashby_boards,
            greenhouse_boards=greenhouse_boards,
            keyword_filter=tuple(target_keywords or [t.lower() for t in target_titles]),
            excluded_role_keywords=tuple(k.lower() for k in default_bundle.excluded_role_keywords),
            excluded_levels=tuple(k.lower() for k in default_bundle.excluded_levels),
            excluded_companies=excluded_companies,
            preferred_locations=tuple(preferred_locations),
            remote_only=bool(default_bundle.remote_only),
            min_salary=default_bundle.min_salary,
            work_auth=work_auth,
            requires_sponsorship=bool(profile.get("requires_sponsorship", True)),
            # Default matches the SQL schema (001_schema.sql:20) so the
            # Python fallback doesn't silently diverge from what the DB
            # would use if users.daily_apply_limit were ever NULL.
            daily_apply_limit=int(prefs.get("daily_apply_limit", 5)),
            profile=profile,
            # Answer key precedence: default bundle's per-profile answer_key
            # (mig 019) → user_profiles.answer_key_json (legacy shared) → {}.
            # Non-default bundles' answer keys are applied per-job in
            # worker.py via knowledge.build_answer_key; this top-level
            # value is the tenant default used when no bundle override fires.
            answer_key=(default_bundle.answer_key_json
                        or profile.get("answer_key_json")
                        or {}),
            profiles=profile_tuple,
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


def _build_apply_profile(raw: dict, fallback_email: str = "") -> ApplyProfile:
    """Construct an ApplyProfile from a cloud profiles[] entry."""
    def _tup(key: str) -> tuple[str, ...]:
        v = raw.get(key) or []
        return tuple(str(x).strip() for x in v if str(x).strip())

    resume = raw.get("resume") or {}
    return ApplyProfile(
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or "Default"),
        slug=str(raw.get("slug") or "default"),
        is_default=bool(raw.get("is_default", False)),
        target_titles=_tup("target_titles"),
        target_keywords=_tup("target_keywords"),
        excluded_titles=_tup("excluded_titles"),
        excluded_companies=_tup("excluded_companies"),
        excluded_role_keywords=tuple(k.lower() for k in _tup("excluded_role_keywords")),
        excluded_levels=tuple(k.lower() for k in _tup("excluded_levels")),
        preferred_locations=_tup("preferred_locations"),
        remote_only=bool(raw.get("remote_only", False)),
        min_salary=raw.get("min_salary"),
        ashby_boards=tuple(raw.get("ashby_boards") or ()) or tuple(DEFAULT_ASHBY_BOARDS),
        greenhouse_boards=tuple(raw.get("greenhouse_boards") or ()) or tuple(DEFAULT_GREENHOUSE_BOARDS),
        resume_path=None,  # filled in by desktop when the file is cached locally
        resume_file_name=(resume.get("file_name") if isinstance(resume, dict) else None),
        resume_signed_url=(resume.get("signed_url") if isinstance(resume, dict) else None),
        # None means "fall back to .env" — preserved so worker can detect it.
        application_email=(raw.get("application_email") if raw.get("application_email") else None),
        application_email_app_password=(raw.get("application_email_app_password") if raw.get("application_email_app_password") else None),
        auto_apply=bool(raw.get("auto_apply", True)),
        max_daily=raw.get("max_daily"),
        # Per-bundle content from mig 019. None means "fall back to
        # user_profiles.answer_key_json" — handled by the caller.
        answer_key_json=(raw.get("answer_key_json") if isinstance(raw.get("answer_key_json"), dict) else None),
        cover_letter_template=(raw.get("cover_letter_template") if raw.get("cover_letter_template") else None),
        # Per-bundle history from mig 020. Same None-as-inherit semantics.
        work_experience=(raw.get("work_experience") if isinstance(raw.get("work_experience"), list) else None),
        education=(raw.get("education") if isinstance(raw.get("education"), list) else None),
        skills=(raw.get("skills") if isinstance(raw.get("skills"), list) else None),
    )


def _keyword_hit(kw: str, text: str) -> bool:
    """Case-insensitive substring match with word-boundary protection for
    short keywords. Assumes text is already lowercased by caller."""
    kw = kw.lower().strip()
    if not kw:
        return False
    if kw in _SHORT_KEYWORDS or len(kw) <= 3:
        return bool(re.search(rf'\b{re.escape(kw)}\b', text))
    return kw in text


# US-aware location matching. When a user sets preferred_locations=["United
# States"], they intend "US jobs" — but ATS APIs return "San Francisco, CA"
# or "Austin, TX" or "Remote", none of which literally contain the phrase
# "united states." We treat all of those as a match.

_US_TOKENS = (
    "united states", "usa", "u.s.a", "u.s.", " us ", ",us", "us,",
    ", us", "(us)", "remote - us", "remote, us", "remote us",
)

_US_STATE_CODES = (
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il",
    "in","ia","ks","ky","la","me","md","ma","mi","mn","ms","mo","mt",
    "ne","nv","nh","nj","nm","ny","nc","nd","oh","ok","or","pa","ri",
    "sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy","dc",
)

# Pre-compiled: matches ", XX" or " XX," or " XX " where XX is a US state code.
_US_STATE_CODE_RE = re.compile(
    r"(?:[,\s]|^)(" + "|".join(_US_STATE_CODES) + r")(?:[,\s.)]|$)",
    re.IGNORECASE,
)


def _wants_us(preferred_lower_list: list[str]) -> bool:
    """True if any preferred_locations entry indicates 'US' intent."""
    return any(
        any(tok in loc for tok in ("united states", "usa", "us", "u.s"))
        for loc in preferred_lower_list
    )


# Non-US location tokens. Matching one of these in a lowercased location
# string means the job is almost certainly outside the US. Kept conservative:
# only include unambiguous country/region/city names. "Paris, TX" in the US
# is rare; we accept the false-positive rate for the vast simplification
# compared to enumerating ~30 000 US cities.
_FOREIGN_TOKENS = (
    # Europe
    "united kingdom", "england", "scotland", "wales", "northern ireland", " uk",
    "(uk)", "uk)", " uk,", ",uk",
    "germany", "berlin", "munich", "hamburg",
    "france", "paris", "lyon",
    "italy", "milan", "rome",
    "spain", "madrid", "barcelona",
    "netherlands", "amsterdam", "rotterdam",
    "belgium", "brussels",
    "switzerland", "zurich", "geneva",
    "austria", "vienna",
    "sweden", "stockholm",
    "norway", "oslo",
    "denmark", "copenhagen",
    "finland", "helsinki",
    "ireland", "dublin",
    "poland", "warsaw",
    "czech", "prague",
    "hungary", "budapest",
    "portugal", "lisbon",
    "greece", "athens",
    "romania", "bulgaria",
    "ukraine", "russia", "moscow",
    "turkey", "istanbul",
    # Americas
    "canada", "toronto", "vancouver", "montreal", "ottawa", "calgary", "edmonton",
    "mexico", "mexico city", "guadalajara",
    "brazil", "sao paulo", "são paulo", "rio de janeiro",
    "argentina", "buenos aires",
    "chile", "santiago",
    # APAC
    "australia", "sydney", "melbourne", "brisbane", "perth",
    "new zealand", "auckland",
    "japan", "tokyo", "osaka",
    "korea", "seoul",
    "china", "beijing", "shanghai", "shenzhen", "guangzhou",
    "hong kong",
    "taiwan", "taipei",
    "singapore",
    "malaysia", "kuala lumpur",
    "india", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad",
    "chennai", "pune", "gurgaon", "noida", "kolkata",
    "philippines", "manila",
    "thailand", "bangkok",
    "vietnam", "ho chi minh", "hanoi",
    "indonesia", "jakarta",
    "pakistan", "lahore", "karachi", "islamabad",
    "bangladesh", "dhaka",
    # MEA
    "united arab emirates", "uae", "dubai", "abu dhabi",
    "saudi arabia", "riyadh",
    "qatar", "doha",
    "israel", "tel aviv",
    "egypt", "cairo",
    "south africa", "cape town", "johannesburg",
    "nigeria", "lagos",
    "kenya", "nairobi",
    # Region tags
    "emea", "apac", "mena", "latam", "europe",
)


def _is_us_location(loc_lower: str) -> bool:
    """True if the given (already-lowercased) location string looks US-ish.

    Three-tier check:
      1. Explicit US tokens ("united states", "usa", etc.) → yes.
      2. "Remote" (US-based ATSes default to US-only unless tagged "global"/
         a region) → yes.
      3. State-code pattern (", CA" etc.) → yes.
      4. Bare city ("San Francisco") — permissive: accept UNLESS the string
         contains a foreign token (see _FOREIGN_TOKENS). Avoids having to
         enumerate US cities.

    Empty string is rejected; callers short-circuit on blank locations.
    """
    if not loc_lower:
        return False
    # Fast accept: explicit US tokens
    if any(tok in loc_lower for tok in _US_TOKENS):
        return True
    # Fast reject: explicit foreign tokens
    if any(tok in loc_lower for tok in _FOREIGN_TOKENS):
        return False
    # Accept "remote" unless already flagged foreign
    if "remote" in loc_lower:
        return True
    # Accept state-code pattern
    if _US_STATE_CODE_RE.search(loc_lower):
        return True
    # Permissive default — no foreign token found, assume US.
    # Coded appliers will refuse a non-US address if it slips through.
    return True
