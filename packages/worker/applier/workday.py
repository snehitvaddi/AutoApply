"""Workday applier — TODO: not yet implemented.

Workday is the most complex ATS platform, requiring:
1. Account creation per-company (each company has its own Workday tenant)
2. A 7-step wizard: Login → Search → Select → Personal Info → Experience → Resume → Review
3. Complex multi-page form navigation with CSRF tokens
4. Company-specific field customizations

Status: Coming Soon (Phase 7+)

Known challenges from OpenClaw learnings:
- Each company has a unique Workday URL (e.g., wd5.myworkday.com/company)
- Account creation requires email verification
- Session management across multiple pages
- Some companies require SSO or additional auth
- Form fields vary significantly between companies
- File upload uses a different mechanism than other ATS platforms
"""

from applier.base import BaseApplier, ApplyResult


class WorkdayApplier(BaseApplier):
    """Placeholder for Workday form filler.

    Workday support is planned but not yet implemented due to the
    complexity of multi-tenant account creation and 7-step wizard flow.
    """

    def apply(self, apply_url: str) -> ApplyResult:
        return ApplyResult(
            success=False,
            error="Workday applier not yet implemented — coming soon",
            retriable=False,
        )
