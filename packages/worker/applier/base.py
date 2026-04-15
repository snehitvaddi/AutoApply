from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ApplyResult:
    success: bool
    screenshot: Optional[str] = None
    error: Optional[str] = None
    retriable: bool = False


class MissingResumeError(FileNotFoundError):
    """Raised when the configured resume_path doesn't exist on disk.

    The worker catches this and marks the application as failed with a
    clean "resume file missing" reason instead of letting the browser
    automation crash halfway through the form.
    """


class BaseApplier(ABC):
    def __init__(
        self,
        profile: dict,
        answer_key: dict,
        resume_path: str,
        *,
        profile_email: str | None = None,
        profile_app_password: str | None = None,
    ):
        self.profile = profile
        self.answer_key = answer_key
        self.resume_path = resume_path
        # Explicit per-bundle credentials — passed by worker.py at apply
        # time. When None, falls back to os.environ (install.sh default).
        self.profile_email = profile_email
        self.profile_app_password = profile_app_password
        # Fail fast: no resume means no upload, and every ATS applier
        # eventually hits `page.set_input_files(...)` with this path. We
        # check now so we error before any browser automation starts.
        if not resume_path:
            raise MissingResumeError("resume_path is empty")
        if not os.path.isfile(resume_path):
            raise MissingResumeError(f"resume file not found: {resume_path}")
        if os.path.getsize(resume_path) == 0:
            raise MissingResumeError(f"resume file is empty: {resume_path}")

    @abstractmethod
    def apply(self, apply_url: str) -> ApplyResult:
        pass

    def profile_summary(self) -> str:
        """Build a concise profile summary for LLM context from the full profile JSON.

        Includes personal info, all work experiences, all education entries,
        legal/EEO data, and standard answers — everything the LLM needs to
        fill any form field.
        """
        import os as _os
        p = self.profile
        # The API returns { user: {email,...}, profile: {first_name,...}, resumes: [...] }
        # OR the profile may be flat (fields at top level). Check both shapes.
        user = p.get("user", {}) or {}
        prof = p.get("profile", {}) or {}

        # Application email: explicit profile_email (bundle-bound) > env
        # GMAIL_EMAIL > signup email. Explicit kwarg eliminates the env-
        # as-IPC footgun that worker.py used to use for bundle routing.
        _explicit = (self.profile_email or "").strip() if self.profile_email else ""
        _gmail_email = _os.environ.get("GMAIL_EMAIL", "").strip()
        _app_email = _explicit or _gmail_email or prof.get("email") or p.get("email") or user.get("email") or ""

        # Helper: check profile sub-object first, then top-level, then user
        def _f(key: str, default: str = "") -> str:
            if key == "email":
                return _app_email or default
            return prof.get(key) or p.get(key) or user.get(key) or default
        work_exp = prof.get("work_experience") or p.get("work_experience") or []
        edu_entries = prof.get("education") or p.get("education") or []
        lines = [
            f"Name: {_f('first_name')} {_f('last_name')}",
            f"Email: {_f('email')}",
            f"Phone: {_f('phone')}",
            f"Location: {_f('city')}, {_f('state')} {_f('zip_code')}",
            f"LinkedIn: {_f('linkedin_url')}",
            f"GitHub: {_f('github_url')}",
            f"Portfolio: {_f('portfolio_url')}",
            "",
            f"WORK EXPERIENCE (CRITICAL: fill ALL {len(work_exp)} positions below — never skip or abbreviate any):",
        ]
        for i, exp in enumerate(work_exp):
            lines.append(
                f"  {i+1}. {exp.get('title','')} @ {exp.get('company','')} "
                f"| {exp.get('start','')} - {exp.get('end','')} | {exp.get('location','')}"
            )
            for ach in exp.get("achievements", []):
                lines.append(f"     - {ach[:150]}")

        lines.append("")
        lines.append(f"EDUCATION (CRITICAL: fill ALL {len(edu_entries)} entries below):")
        for edu in edu_entries:
            lines.append(
                f"  - {edu.get('school','')} | {edu.get('degree','')} {edu.get('field','')} "
                f"| {edu.get('start','')} - {edu.get('end','')} | GPA: {edu.get('gpa','N/A')}"
            )

        lines.append("")
        lines.append("SKILLS:")
        skills = prof.get("skills") or p.get("skills") or []
        if isinstance(skills, list):
            lines.append(f"  {', '.join(skills)}")
        elif isinstance(skills, dict):
            for cat, items in skills.items():
                lines.append(f"  {cat}: {', '.join(items) if isinstance(items, list) else items}")

        lines.append("")
        lines.append("LEGAL:")
        lines.append(f"  Work authorized: {_f('work_authorization', 'Yes')}")
        lines.append(f"  Requires sponsorship: {_f('requires_sponsorship', 'True')}")

        lines.append("")
        lines.append("EEO:")
        for key in ("gender", "race_ethnicity", "veteran_status", "disability_status"):
            val = _f(key)
            if val:
                lines.append(f"  {key}: {val}")

        lines.append("")
        lines.append("STANDARD ANSWERS:")
        ak = self.answer_key
        for key in ("cover_letter_template", "additional_info", "strengths", "why_leaving"):
            val = ak.get("textarea_fields", {}).get(key) or _f(key, "")
            if val:
                lines.append(f"  {key}: {val[:250]}")

        return "\n".join(lines)
