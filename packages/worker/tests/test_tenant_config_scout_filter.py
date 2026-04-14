"""Regression: single-profile users' scout + filter behavior must be
unchanged from pre-multi-profile. This closes the coverage gap the audit
flagged: the existing test_scout_contract.py only greps for banned strings
in plugin files; it never exercises TenantConfig.load() itself.

We can't hit the real API in a unit test, so we mock db._api_call to
return a synthetic cloud payload that matches what /api/worker/proxy
now emits, and assert the loaded TenantConfig has the expected shape.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenant import TenantConfig, TenantConfigIncompleteError


def _mock_get_tenant_config(bundles=None, profile_overrides=None):
    """Build a fake /api/worker/proxy get_tenant_config payload."""
    return {
        "user_id": "user-123",
        "tenant_email": "user@example.com",
        "search_queries": ["AI Engineer"],  # legacy top-level, ignored now
        "keyword_filter": ["ai"],
        "ashby_boards": None,
        "greenhouse_boards": None,
        "excluded_role_keywords": ["manager"],
        "excluded_levels": ["staff"],
        "excluded_companies": ["Palantir"],
        "preferred_locations": ["United States"],
        "remote_only": False,
        "min_salary": 150000,
        "daily_apply_limit": 25,
        "profile": {
            "first_name": "Test",
            "last_name": "User",
            "email": "user@example.com",
            "work_authorization": "citizen",
            "requires_sponsorship": False,
            **(profile_overrides or {}),
        },
        "profiles": bundles if bundles is not None else [
            {
                "id": "bundle-1",
                "name": "Default",
                "slug": "default",
                "is_default": True,
                "target_titles": ["AI Engineer", "ML Engineer"],
                "target_keywords": ["pytorch"],
                "excluded_role_keywords": ["manager"],
                "excluded_levels": ["staff"],
                "excluded_companies": ["Palantir"],
                "preferred_locations": ["United States"],
                "remote_only": False,
                "min_salary": 150000,
                "ashby_boards": None,
                "greenhouse_boards": None,
                "resume": None,
                "application_email": "apply@example.com",
                "application_email_app_password": "xxxx-yyyy",
                "auto_apply": True,
                "max_daily": None,
            }
        ],
        "complete": True,
    }


def test_single_profile_tenant_loads_with_expected_fields():
    """Single-profile: derived TenantConfig matches the default bundle."""
    with patch("db._api_call", return_value=_mock_get_tenant_config()):
        tc = TenantConfig.load("user-123")
    assert tc.user_id == "user-123"
    assert "AI Engineer" in tc.search_queries
    assert "ML Engineer" in tc.search_queries
    assert "pytorch" in tc.keyword_filter
    # Default bundle's filter fields propagate to top-level.
    assert "manager" in tc.excluded_role_keywords
    assert "staff" in tc.excluded_levels
    assert tc.min_salary == 150000
    assert tc.remote_only is False
    assert len(tc.profiles) == 1
    assert tc.profiles[0].application_email == "apply@example.com"
    assert tc.profiles[0].application_email_app_password == "xxxx-yyyy"


def test_bundle_with_null_email_is_none_not_empty_string():
    """Regression: null application_email from cloud must preserve as
    None (signal to worker to fall back to .env), not stringified."""
    payload = _mock_get_tenant_config(bundles=[
        {
            "id": "b1", "name": "Default", "slug": "default", "is_default": True,
            "target_titles": ["AI Engineer"], "target_keywords": [],
            "excluded_role_keywords": [], "excluded_levels": [],
            "excluded_companies": [], "preferred_locations": ["US"],
            "remote_only": False, "min_salary": None,
            "ashby_boards": None, "greenhouse_boards": None,
            "resume": None,
            "application_email": None,
            "application_email_app_password": None,
            "auto_apply": True, "max_daily": None,
        }
    ])
    with patch("db._api_call", return_value=payload):
        tc = TenantConfig.load("user-123")
    assert tc.profiles[0].application_email is None
    assert tc.profiles[0].application_email_app_password is None


def test_multi_profile_unions_target_titles_for_scout():
    """Scout queries must include titles from EVERY bundle, not just the
    default's legacy top-level list. Was the regression-audit finding #6."""
    payload = _mock_get_tenant_config(bundles=[
        {
            "id": "ai", "name": "AI", "slug": "ai", "is_default": True,
            "target_titles": ["AI Engineer"], "target_keywords": [],
            "excluded_role_keywords": [], "excluded_levels": [],
            "excluded_companies": [], "preferred_locations": ["US"],
            "remote_only": False, "min_salary": None,
            "ashby_boards": None, "greenhouse_boards": None,
            "resume": None,
            "application_email": "ai@example.com",
            "application_email_app_password": "p1",
            "auto_apply": True, "max_daily": None,
        },
        {
            "id": "da", "name": "DA", "slug": "da", "is_default": False,
            "target_titles": ["Data Analyst"], "target_keywords": ["sql"],
            "excluded_role_keywords": [], "excluded_levels": [],
            "excluded_companies": [], "preferred_locations": ["US"],
            "remote_only": False, "min_salary": None,
            "ashby_boards": None, "greenhouse_boards": None,
            "resume": None,
            "application_email": "da@example.com",
            "application_email_app_password": "p2",
            "auto_apply": True, "max_daily": None,
        },
    ])
    with patch("db._api_call", return_value=payload):
        tc = TenantConfig.load("user-123")
    assert "AI Engineer" in tc.search_queries
    assert "Data Analyst" in tc.search_queries
    # keyword_filter picks up per-bundle target_keywords too.
    assert "sql" in tc.keyword_filter


def test_empty_profiles_with_legacy_fields_auto_wraps():
    """When cloud returns profiles=[] (e.g. rows deleted + caller didn't
    re-run backfill), TenantConfig.load should auto-wrap the legacy
    top-level fields into a single default bundle so the worker still
    boots instead of crashing."""
    payload = _mock_get_tenant_config(bundles=[])
    with patch("db._api_call", return_value=payload):
        tc = TenantConfig.load("user-123")
    assert len(tc.profiles) == 1
    assert tc.profiles[0].is_default is True
    assert "AI Engineer" in tc.profiles[0].target_titles
    # Legacy auto-wrap sets application_email to None so worker falls
    # through to .env GMAIL_EMAIL (install.sh's value).
    assert tc.profiles[0].application_email is None


def test_incomplete_tenant_raises():
    """Profile without first_name should raise TenantConfigIncompleteError."""
    payload = _mock_get_tenant_config(profile_overrides={"first_name": ""})
    with patch("db._api_call", return_value=payload):
        try:
            TenantConfig.load("user-123")
            assert False, "expected TenantConfigIncompleteError"
        except TenantConfigIncompleteError as e:
            assert any("first_name" in m for m in e.missing)
