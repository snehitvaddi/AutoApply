from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ApplyResult:
    success: bool
    screenshot: Optional[str] = None
    error: Optional[str] = None
    retriable: bool = False


class BaseApplier(ABC):
    def __init__(self, profile: dict, answer_key: dict, resume_path: str):
        self.profile = profile
        self.answer_key = answer_key
        self.resume_path = resume_path

    @abstractmethod
    def apply(self, apply_url: str) -> ApplyResult:
        pass

    def profile_summary(self) -> str:
        """Build a concise profile summary for LLM context from the full profile JSON.

        Includes personal info, all work experiences, all education entries,
        legal/EEO data, and standard answers — everything the LLM needs to
        fill any form field.
        """
        p = self.profile
        user = p.get("user", {})
        lines = [
            f"Name: {user.get('first_name', '')} {user.get('last_name', '')}",
            f"Email: {user.get('email', '')}",
            f"Phone: {user.get('phone', '')}",
            f"Location: {user.get('city', '')}, {user.get('state', '')} {user.get('zip_code', '')}",
            f"LinkedIn: {user.get('linkedin_url', '')}",
            f"GitHub: {user.get('github_url', '')}",
            f"Portfolio: {user.get('portfolio_url', '')}",
            "",
            "WORK EXPERIENCE (CRITICAL: fill ALL 4 positions below — never skip or abbreviate any):",
        ]
        for i, exp in enumerate(p.get("work_experience", [])):
            lines.append(
                f"  {i+1}. {exp.get('title','')} @ {exp.get('company','')} "
                f"| {exp.get('start','')} - {exp.get('end','')} | {exp.get('location','')}"
            )
            for ach in exp.get("achievements", []):
                lines.append(f"     - {ach[:150]}")

        lines.append("")
        lines.append("EDUCATION (CRITICAL: fill ALL entries below — both degrees required):")
        for edu in p.get("education", []):
            lines.append(
                f"  - {edu.get('school','')} | {edu.get('degree','')} {edu.get('field','')} "
                f"| {edu.get('start','')} - {edu.get('end','')} | GPA: {edu.get('gpa','N/A')}"
            )

        lines.append("")
        lines.append("SKILLS:")
        skills = p.get("skills", [])
        if isinstance(skills, list):
            lines.append(f"  {', '.join(skills)}")
        elif isinstance(skills, dict):
            for cat, items in skills.items():
                lines.append(f"  {cat}: {', '.join(items) if isinstance(items, list) else items}")

        lines.append("")
        lines.append("LEGAL:")
        lines.append(f"  Work authorized: {user.get('work_authorization', 'Yes')}")
        lines.append(f"  Requires sponsorship: {user.get('requires_sponsorship', True)}")

        lines.append("")
        lines.append("EEO:")
        for key in ("gender", "race_ethnicity", "veteran_status", "disability_status"):
            if user.get(key):
                lines.append(f"  {key}: {user[key]}")

        lines.append("")
        lines.append("STANDARD ANSWERS:")
        ak = self.answer_key
        for key in ("cover_letter_template", "additional_info", "strengths", "why_leaving"):
            val = ak.get("textarea_fields", {}).get(key) or user.get(key, "")
            if val:
                lines.append(f"  {key}: {val[:250]}")

        return "\n".join(lines)
