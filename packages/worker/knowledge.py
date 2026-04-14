import json
import os
import logging

from db import get_global_knowledge

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "knowledge")


def load_global_template() -> dict:
    """Load the global answer-key template from local file or DB fallback."""
    local_path = os.path.join(KNOWLEDGE_DIR, "answer-key-template.json")
    if os.path.exists(local_path):
        with open(local_path) as f:
            return json.load(f)

    template = get_global_knowledge("answer_key_template")
    if template:
        return template

    logger.warning("No global answer-key template found, returning empty dict")
    return {}


def build_answer_key(profile: dict, global_template: dict) -> dict:
    """Build a filled answer_key by substituting profile values into the global template.

    The template contains {placeholder} strings that map to profile fields.
    For example, {first_name} is replaced with profile["profile"]["first_name"].

    The user's own answer_key_json overrides are merged on top.
    """
    # The profile dict can arrive in THREE shapes depending on the caller:
    #   A) Flat cloud response (from /api/worker/proxy load_profile):
    #      { first_name, email, work_experience, ... }
    #   B) Nested local cache (~/.applyloop/profile.json written by
    #      install.sh + pty_terminal._pull_profile_from_cloud):
    #      { personal: {first_name}, user: {email}, work: {current_company},
    #        legal: {work_authorization}, eeo: {gender}, experience: [...] }
    #   C) Wrapped cloud response (from some older callers):
    #      { user: {email}, profile: {first_name, ...} }
    # Rather than forcing callers to normalize, we defensively read from ALL
    # three shapes. This is the same pattern applier/base.py uses.
    user_data = profile.get("user", {}) or {}
    profile_data = profile.get("profile", {}) or {}
    personal = profile.get("personal", {}) or {}
    work = profile.get("work", {}) or {}
    legal = profile.get("legal", {}) or {}
    eeo = profile.get("eeo", {}) or {}
    edu_sum = profile.get("education_summary", {}) or {}

    def _f(key: str, default: str = "") -> str:
        """Look up `key` in every known location, first match wins."""
        for src in (profile_data, personal, work, legal, eeo, edu_sum, profile, user_data):
            v = src.get(key)
            if v not in (None, "", []):
                return v
        return default

    # Application email: prefer GMAIL_EMAIL from .env (the email the user
    # wants on applications + where OTPs land) over profile emails. A user
    # may sign up with personal@gmail.com but apply with professional@gmail.com
    # (which has the app password configured).
    gmail_email = os.environ.get("GMAIL_EMAIL", "").strip()
    app_email = gmail_email or _f("email", "")

    # Build substitution map from profile fields
    first_name = _f("first_name", "")
    last_name = _f("last_name", "")
    substitutions = {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{first_name} {last_name}".strip(),
        "email": app_email,
        "phone": _f("phone", ""),
        "linkedin_url": _f("linkedin_url", ""),
        "github_url": _f("github_url", ""),
        "portfolio_url": _f("portfolio_url", ""),
        "current_company": _f("current_company", ""),
        "current_title": _f("current_title", ""),
        "years_experience": str(_f("years_experience", "")),
        "work_authorization": _f("work_authorization", ""),
        "requires_sponsorship": "Yes" if _f("requires_sponsorship", False) else "No",
        "school_name": _f("school_name", ""),
        "degree": _f("degree", ""),
        "graduation_year": str(_f("graduation_year", "")),
        "gender": _f("gender", ""),
        "race_ethnicity": _f("race_ethnicity", ""),
        "veteran_status": _f("veteran_status", "I am not a protected veteran"),
        "disability_status": _f("disability_status", ""),
    }

    # Deep-substitute placeholders in the template
    answer_key = _substitute(global_template, substitutions)

    # Merge user-specific overrides on top. Key name varies by source:
    # cloud → answer_key_json, local nested → standard_answers.
    user_overrides = (
        profile_data.get("answer_key_json")
        or profile.get("answer_key_json")
        or profile.get("standard_answers")
        or {}
    )
    answer_key = _deep_merge(answer_key, user_overrides)

    return answer_key


def _substitute(obj, subs: dict):
    """Recursively substitute {placeholder} strings in a nested dict/list."""
    if isinstance(obj, str):
        for key, val in subs.items():
            obj = obj.replace(f"{{{key}}}", str(val))
        return obj
    elif isinstance(obj, dict):
        return {k: _substitute(v, subs) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_substitute(item, subs) for item in obj]
    return obj


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Merge overrides into base dict, preferring override values."""
    result = base.copy()
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
