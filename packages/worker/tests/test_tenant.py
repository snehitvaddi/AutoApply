"""Behavioral tests for TenantConfig — verify that client-specific values
flow through the scout/filter pipeline instead of hardcoded admin defaults.

Each test class represents a different kind of client the SaaS needs to
support. If admin-bias leaks back into the codebase, one of these will
fail LOUDLY instead of silently scouting the wrong roles.

Run:  cd packages/worker && python3 -m unittest tests.test_tenant -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Make worker/ importable without needing to be run from that directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tenant import TenantConfig, DEFAULT_SECURITY_CLEARANCE_COMPANIES  # noqa: E402


def _build(
    *,
    user_id: str = "test-user-0000",
    target_titles: list[str],
    target_keywords: list[str] | None = None,
    excluded_role_keywords: list[str] | None = None,
    excluded_levels: list[str] | None = None,
    excluded_companies: list[str] | None = None,
    preferred_locations: list[str] | None = None,
    remote_only: bool = False,
    work_auth: str = "citizen",
    tenant_name: str = "Test Client",
    tenant_email: str = "test@example.com",
) -> TenantConfig:
    """Hand-build a TenantConfig for tests without hitting the network.
    Mirrors what TenantConfig.load() produces from a cloud API response.
    """
    # If visa-blocked, union the clearance list into excluded_companies
    # (same logic as TenantConfig.load). The test calls this helper AFTER
    # providing work_auth so the merge matches production behavior.
    user_excluded = [c.lower() for c in (excluded_companies or [])]
    visa_blocked = work_auth.lower() in ("opt", "h1b", "f1", "tn", "l1", "l2", "opt-stem")
    if visa_blocked:
        merged_excluded = tuple(sorted(set(user_excluded + DEFAULT_SECURITY_CLEARANCE_COMPANIES)))
    else:
        merged_excluded = tuple(sorted(set(user_excluded)))

    return TenantConfig(
        user_id=user_id,
        search_queries=tuple(target_titles),
        linkedin_seed_queries=tuple(target_titles),
        ashby_boards=("figma", "stripe"),  # arbitrary — not under test here
        greenhouse_boards=("brex", "datadog"),
        keyword_filter=tuple((target_keywords or target_titles) or []),
        excluded_role_keywords=tuple(k.lower() for k in (excluded_role_keywords or [])),
        excluded_levels=tuple(k.lower() for k in (excluded_levels or [])),
        excluded_companies=merged_excluded,
        preferred_locations=tuple(preferred_locations or []),
        remote_only=remote_only,
        min_salary=None,
        work_auth=work_auth.lower(),
        requires_sponsorship=visa_blocked,
        daily_apply_limit=25,
        profile={"first_name": "Test", "last_name": "Client", "email": tenant_email},
        answer_key={},
        tenant_name=tenant_name,
        tenant_email=tenant_email,
        complete=True,
    )


class BackendEngineerTenantTest(unittest.TestCase):
    """A backend engineer client whose target_titles have zero ML content
    must not see AI/ML/DS jobs scouted for them — only backend matches.
    This is the core regression that killed SaaS multi-tenancy before.
    """

    def setUp(self) -> None:
        self.tenant = _build(
            target_titles=[
                "Backend Engineer",
                "Platform Engineer",
                "Infrastructure Engineer",
                "Distributed Systems Engineer",
            ],
            preferred_locations=["San Francisco", "Remote US"],
        )

    def test_backend_role_passes(self) -> None:
        self.assertTrue(
            self.tenant.passes_filter("Backend Engineer", "stripe", "San Francisco, CA"),
            "A backend engineer job at Stripe must pass for a backend tenant.",
        )
        self.assertTrue(
            self.tenant.passes_filter("Platform Engineer", "datadog", "Remote US"),
            "Platform Engineer must pass — matches target_titles.",
        )

    def test_ai_role_rejected(self) -> None:
        self.assertFalse(
            self.tenant.passes_filter("AI Engineer", "openai", "San Francisco"),
            "An AI Engineer role must NOT pass for a backend tenant — no admin-default leak.",
        )
        self.assertFalse(
            self.tenant.passes_filter("Machine Learning Engineer", "anthropic", "SF"),
            "ML Engineer must NOT pass — target_titles are backend-only.",
        )
        self.assertFalse(
            self.tenant.passes_filter("Data Scientist", "brex", "Remote US"),
            "Data Scientist must NOT pass — no backend keyword match.",
        )

    def test_location_filter_respected(self) -> None:
        self.assertFalse(
            self.tenant.passes_filter("Backend Engineer", "monzo", "London, UK"),
            "Backend role outside preferred_locations must NOT pass.",
        )


class UXDesignerTenantTest(unittest.TestCase):
    """A UX designer client whose admin-era code had "designer" hardcoded
    in SKIP_ROLE_KEYWORDS. With Part 2, that list is gone — designer jobs
    must pass if they match the tenant's target_titles.
    """

    def setUp(self) -> None:
        self.tenant = _build(
            target_titles=["Product Designer", "UX Designer", "Senior UX Designer"],
            preferred_locations=["New York", "Remote"],
        )

    def test_designer_role_passes(self) -> None:
        self.assertTrue(
            self.tenant.passes_filter("Product Designer", "figma", "Remote"),
            "Product Designer must pass for a designer tenant. "
            "The old admin SKIP_ROLE_KEYWORDS with 'designer' must be gone.",
        )
        self.assertTrue(
            self.tenant.passes_filter("Senior UX Designer", "linear", "New York, NY"),
        )

    def test_backend_role_rejected(self) -> None:
        self.assertFalse(
            self.tenant.passes_filter("Backend Engineer", "stripe", "SF"),
            "Backend role must NOT pass for a designer tenant — no match.",
        )


class StaffLevelTenantTest(unittest.TestCase):
    """A senior engineer client targeting Staff+ roles. The old admin
    SKIP_LEVELS list contained 'staff', 'principal' — meaning staff-level
    clients got filtered out entirely. Part 2 makes excluded_levels per-user
    (empty by default) so Staff/Principal pass.
    """

    def setUp(self) -> None:
        self.tenant = _build(
            target_titles=["Staff Engineer", "Staff Software Engineer", "Principal Engineer"],
            excluded_levels=[],  # explicitly empty — wants Staff+
            preferred_locations=["Remote"],
        )

    def test_staff_role_passes(self) -> None:
        self.assertTrue(
            self.tenant.passes_filter("Staff Software Engineer", "datadog", "Remote"),
            "Staff SWE must pass. The old SKIP_LEVELS=['staff'] admin default is gone.",
        )
        self.assertTrue(
            self.tenant.passes_filter("Principal Engineer", "gitlab", "Remote"),
        )


class LondonTenantTest(unittest.TestCase):
    """A client based in London. Admin's hardcoded SKIP_LOCATIONS included
    'london', so every London job got rejected. Part 2 uses only the
    tenant's preferred_locations — no global geo blocklist.
    """

    def setUp(self) -> None:
        self.tenant = _build(
            target_titles=["Backend Engineer", "Platform Engineer"],
            preferred_locations=["London, UK", "London, United Kingdom", "Remote EU"],
        )

    def test_london_role_passes(self) -> None:
        self.assertTrue(
            self.tenant.passes_filter("Backend Engineer", "monzo", "London, United Kingdom"),
            "London job must pass for a London tenant. The old SKIP_LOCATIONS=['london'] admin default is gone.",
        )

    def test_us_role_rejected(self) -> None:
        self.assertFalse(
            self.tenant.passes_filter("Backend Engineer", "stripe", "San Francisco, CA"),
            "SF job must NOT pass for a tenant whose preferred_locations is London-only.",
        )


class VisaBlockedTenantTest(unittest.TestCase):
    """Security clearance companies only apply to visa-blocked tenants.
    A citizen can apply to Anduril/Palantir freely; an OPT tenant cannot.
    """

    def test_citizen_not_blocked(self) -> None:
        tenant = _build(
            target_titles=["Software Engineer"],
            work_auth="citizen",
        )
        # Anduril is in DEFAULT_SECURITY_CLEARANCE_COMPANIES
        self.assertFalse(
            tenant.security_clearance_blocked("anduril"),
            "A US citizen must NOT be blocked from clearance-required companies.",
        )
        self.assertFalse(
            tenant.security_clearance_blocked("palantir"),
            "A US citizen must NOT be blocked from Palantir.",
        )
        # passes_filter should also allow Anduril because it's not merged into excluded_companies
        self.assertTrue(
            tenant.passes_filter("Software Engineer", "anduril", "Remote US"),
            "Citizen tenant must be allowed to scout Anduril.",
        )

    def test_opt_blocked(self) -> None:
        tenant = _build(
            target_titles=["Software Engineer"],
            work_auth="opt",
        )
        self.assertTrue(
            tenant.security_clearance_blocked("anduril"),
            "An OPT tenant MUST be blocked from clearance-required companies.",
        )
        self.assertTrue(
            tenant.security_clearance_blocked("lockheed martin"),
        )
        # And passes_filter should reject because excluded_companies was merged at build
        self.assertFalse(
            tenant.passes_filter("Software Engineer", "anduril", "Remote US"),
            "OPT tenant's passes_filter must reject Anduril.",
        )


class ExcludedRoleKeywordsTest(unittest.TestCase):
    """If a tenant explicitly excludes certain keywords (e.g. "sales",
    "recruiter"), the filter must honor that list — and ONLY that list,
    not an admin-opinion default.
    """

    def test_user_defined_exclusions_work(self) -> None:
        tenant = _build(
            target_titles=["Software Engineer"],
            excluded_role_keywords=["sales", "manager"],
        )
        self.assertFalse(
            tenant.passes_filter("Sales Software Engineer", "stripe", "Remote"),
            "User excluded 'sales' — must reject.",
        )
        self.assertFalse(
            tenant.passes_filter("Software Engineer Manager", "stripe", "Remote"),
            "User excluded 'manager' — must reject.",
        )
        # But a plain Software Engineer passes
        self.assertTrue(
            tenant.passes_filter("Software Engineer", "stripe", "Remote"),
        )

    def test_empty_exclusions_dont_block(self) -> None:
        """A tenant with excluded_role_keywords=[] must NOT fall back to an
        admin default (the old bug). Nothing gets excluded."""
        tenant = _build(
            target_titles=["Marketing Coordinator"],
            excluded_role_keywords=[],
        )
        # "marketing" used to be in admin SKIP_ROLE_KEYWORDS. With Part 2,
        # a marketing tenant with empty exclusions must get marketing jobs.
        self.assertTrue(
            tenant.passes_filter("Marketing Coordinator", "hubspot", "Remote"),
            "Marketing role must pass for a marketing tenant — no admin-default leak.",
        )


class ShortKeywordBoundaryTest(unittest.TestCase):
    """Short keywords like "ai" and "ml" need word-boundary matching or
    they'd match "Retail Associate" (ai in retAIler) and "HTML Developer".
    """

    def setUp(self) -> None:
        self.tenant = _build(target_titles=["AI Engineer", "ML Engineer"])

    def test_ai_keyword_word_boundary(self) -> None:
        # "Retail Associate" must NOT match "ai"
        self.assertFalse(
            self.tenant.passes_filter("Retail Associate", "target", "NYC"),
        )
        # "AI Engineer" must match
        self.assertTrue(
            self.tenant.passes_filter("AI Engineer", "openai", "SF"),
        )

    def test_ml_keyword_word_boundary(self) -> None:
        # "HTML Developer" must NOT match "ml"
        self.assertFalse(
            self.tenant.passes_filter("HTML Developer", "wix", "Remote"),
        )
        # "ML Engineer" must match
        self.assertTrue(
            self.tenant.passes_filter("ML Engineer", "anthropic", "SF"),
        )


class RemoteOnlyTenantTest(unittest.TestCase):
    """A remote-only tenant must reject any non-remote job."""

    def setUp(self) -> None:
        self.tenant = _build(
            target_titles=["Software Engineer"],
            preferred_locations=[],
            remote_only=True,
        )

    def test_remote_passes(self) -> None:
        self.assertTrue(
            self.tenant.passes_filter("Software Engineer", "gitlab", "Remote US"),
        )

    def test_onsite_rejected(self) -> None:
        self.assertFalse(
            self.tenant.passes_filter("Software Engineer", "stripe", "San Francisco"),
        )


if __name__ == "__main__":
    unittest.main()
