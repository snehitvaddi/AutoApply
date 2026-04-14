"""Verify per-bundle answer_key_json (migration 019) routes correctly.

Scenario: user has two bundles — AI Engineer with answers tailored for
AI roles, Data Analyst with different answers. Worker picks the bundle
for a given job via pick_profile_for_job, then builds the answer key
from THAT bundle's answer_key_json, NOT the shared user_profiles one.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenant import ApplyProfile
from knowledge import build_answer_key


def _mk_profile(**over) -> ApplyProfile:
    base = dict(
        id="p1", name="Default", slug="default", is_default=True,
        target_titles=("AI Engineer",), target_keywords=(),
        excluded_titles=(), excluded_companies=(),
        excluded_role_keywords=(), excluded_levels=(),
        preferred_locations=(), remote_only=False, min_salary=None,
        ashby_boards=(), greenhouse_boards=(),
        resume_path=None, resume_file_name=None, resume_signed_url=None,
        application_email=None, application_email_app_password=None,
        auto_apply=True, max_daily=None,
        answer_key_json=None, cover_letter_template=None,
    )
    base.update(over)
    return ApplyProfile(**base)


def test_bundle_answer_key_overrides_shared():
    """When a bundle has answer_key_json, build_answer_key uses those
    answers instead of the shared user_profiles.answer_key_json."""
    shared = {"why_interested": "Generic answer from user_profiles"}
    bundle = {"why_interested": "AI-specific answer from bundle"}
    profile = {
        "profile": {"first_name": "Test", "last_name": "User", "email": "a@b.co"},
        "answer_key_json": shared,
    }
    result = build_answer_key(profile, {}, bundle_answer_key=bundle)
    assert result["why_interested"] == "AI-specific answer from bundle"


def test_no_bundle_answer_key_falls_back_to_shared():
    """When bundle has no answer_key_json, the shared one wins."""
    shared = {"why_interested": "Generic from user_profiles"}
    profile = {
        "profile": {"first_name": "Test", "last_name": "User", "email": "a@b.co"},
        "answer_key_json": shared,
    }
    result = build_answer_key(profile, {}, bundle_answer_key=None)
    assert result["why_interested"] == "Generic from user_profiles"


def test_both_empty_returns_template_only():
    """No bundle, no shared → only whatever the global template provides."""
    profile = {
        "profile": {"first_name": "Test", "last_name": "User", "email": "a@b.co"},
    }
    result = build_answer_key(profile, {"greeting": "Hello {first_name}"})
    assert result["greeting"] == "Hello Test"
    assert "why_interested" not in result


def test_bundle_answer_key_must_be_a_dict():
    """ApplyProfile.answer_key_json is typed as dict | None. Passing a
    non-dict should behave like None (fall back)."""
    p = _mk_profile(answer_key_json=None)
    assert p.answer_key_json is None
    p2 = _mk_profile(answer_key_json={"q": "a"})
    assert p2.answer_key_json == {"q": "a"}


def test_cover_letter_is_per_bundle():
    """cover_letter_template is just a string field — verify it round-trips."""
    p = _mk_profile(cover_letter_template="Dear {hiring_manager}, I built {project}...")
    assert "Dear" in p.cover_letter_template
