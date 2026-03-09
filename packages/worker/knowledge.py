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
    user_data = profile.get("user", {})
    profile_data = profile.get("profile", {})

    # Build substitution map from profile fields
    substitutions = {
        "first_name": profile_data.get("first_name", ""),
        "last_name": profile_data.get("last_name", ""),
        "full_name": f"{profile_data.get('first_name', '')} {profile_data.get('last_name', '')}".strip(),
        "email": user_data.get("email", ""),
        "phone": profile_data.get("phone", ""),
        "linkedin_url": profile_data.get("linkedin_url", ""),
        "github_url": profile_data.get("github_url", ""),
        "portfolio_url": profile_data.get("portfolio_url", ""),
        "current_company": profile_data.get("current_company", ""),
        "current_title": profile_data.get("current_title", ""),
        "years_experience": str(profile_data.get("years_experience", "")),
        "work_authorization": profile_data.get("work_authorization", ""),
        "requires_sponsorship": "Yes" if profile_data.get("requires_sponsorship") else "No",
        "school_name": profile_data.get("school_name", ""),
        "degree": profile_data.get("degree", ""),
        "graduation_year": str(profile_data.get("graduation_year", "")),
        "gender": profile_data.get("gender", ""),
        "race_ethnicity": profile_data.get("race_ethnicity", ""),
        "veteran_status": profile_data.get("veteran_status", "I am not a protected veteran"),
        "disability_status": profile_data.get("disability_status", ""),
    }

    # Deep-substitute placeholders in the template
    answer_key = _substitute(global_template, substitutions)

    # Merge user-specific overrides on top
    user_overrides = profile_data.get("answer_key_json") or {}
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
