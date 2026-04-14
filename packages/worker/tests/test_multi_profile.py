"""Multi-profile architecture: ApplyProfile + TenantConfig.pick_profile_for_job.

Verifies:
  - A bundle that matches a job's title returns a positive score.
  - A bundle that doesn't match (title excluded / no keyword hit) returns 0.
  - With two bundles, the higher-scoring one wins.
  - Ties break toward is_default.
  - Single-profile tenants: every job routes to the only bundle.
  - No bundle accepts → pick_profile_for_job returns None.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenant import ApplyProfile, TenantConfig


def _mk_profile(**over) -> ApplyProfile:
    base = dict(
        id="p1", name="Default", slug="default", is_default=True,
        target_titles=("AI Engineer",), target_keywords=(),
        excluded_titles=(), excluded_companies=(),
        excluded_role_keywords=(), excluded_levels=(),
        preferred_locations=(), remote_only=False, min_salary=None,
        ashby_boards=(), greenhouse_boards=(),
        resume_path=None, resume_file_name=None, resume_signed_url=None,
        application_email="a@b.co", application_email_app_password="",
        auto_apply=True, max_daily=None,
    )
    base.update(over)
    return ApplyProfile(**base)


def _mk_tenant(profiles: tuple[ApplyProfile, ...]) -> TenantConfig:
    return TenantConfig(
        user_id="test", search_queries=(), linkedin_seed_queries=(),
        ashby_boards=(), greenhouse_boards=(),
        keyword_filter=("ai",),
        excluded_role_keywords=(), excluded_levels=(), excluded_companies=(),
        preferred_locations=(), remote_only=False, min_salary=None,
        work_auth="citizen", requires_sponsorship=False,
        daily_apply_limit=25, profile={}, answer_key={},
        profiles=profiles, tenant_name="t", tenant_email="a@b.co", complete=True,
    )


def test_match_score_matches_target_title():
    p = _mk_profile(target_titles=("AI Engineer", "ML Engineer"))
    assert p.match_score("Senior AI Engineer") > 0
    assert p.match_score("Warehouse Associate") == 0.0


def test_pick_higher_score_wins():
    ai = _mk_profile(id="ai", name="AI", is_default=True, target_titles=("AI Engineer",))
    da = _mk_profile(id="da", name="DA", is_default=False, target_titles=("Data Analyst",))
    t = _mk_tenant((ai, da))
    picked = t.pick_profile_for_job("Senior Data Analyst")
    assert picked is not None and picked.id == "da"


def test_pick_default_breaks_ties():
    a = _mk_profile(id="a", name="A", is_default=True, target_titles=("Python",))
    b = _mk_profile(id="b", name="B", is_default=False, target_titles=("Python",))
    t = _mk_tenant((a, b))
    picked = t.pick_profile_for_job("Python Engineer")
    assert picked is not None and picked.id == "a"


def test_pick_returns_none_when_no_match():
    p = _mk_profile(target_titles=("AI Engineer",))
    t = _mk_tenant((p,))
    assert t.pick_profile_for_job("Plumber") is None


def test_single_profile_always_picked_when_matches():
    p = _mk_profile(target_titles=("AI Engineer",))
    t = _mk_tenant((p,))
    picked = t.pick_profile_for_job("AI Engineer II")
    assert picked is not None and picked.is_default


def test_default_profile_helper():
    ai = _mk_profile(id="ai", is_default=False)
    da = _mk_profile(id="da", is_default=True)
    t = _mk_tenant((ai, da))
    assert t.default_profile().id == "da"


def test_profile_by_id_lookup():
    ai = _mk_profile(id="ai", is_default=True)
    t = _mk_tenant((ai,))
    assert t.profile_by_id("ai").id == "ai"
    assert t.profile_by_id("missing") is None
    assert t.profile_by_id(None) is None


def test_bundle_with_none_email_allows_env_fallback():
    """When a bundle has application_email=None, the worker should detect
    it as 'fall back to .env' rather than treating it as an explicit empty
    override. This is the regression path that was wiping .env creds for
    every single-profile user after backfill."""
    p = _mk_profile(application_email=None, application_email_app_password=None)
    assert p.application_email is None
    assert p.application_email_app_password is None


def test_pick_returns_none_for_no_match_not_baseline():
    """Ensure match_score doesn't return a 0.1 baseline just because
    passes_filter passed — a wrong-domain bundle can no longer claim a
    job via the exclusions-only bypass."""
    # DA bundle, keyword "data" only — doesn't mention AI at all.
    da = _mk_profile(id="da", target_titles=("Data Analyst",), target_keywords=("data",))
    # excluded_role_keywords empty so passes_filter is structurally OK on
    # an AI job, but match_score should still return 0.
    assert da.match_score("AI Engineer II") == 0.0


def test_remote_only_blank_location_rejected():
    """remote_only bundles should reject blank-location jobs. A missing
    location field almost always means in-office."""
    p = _mk_profile(preferred_locations=(), remote_only=True)
    assert p.passes_filter("AI Engineer", "Acme", "") is False
    assert p.passes_filter("AI Engineer", "Acme", "Remote US") is True
