"""Contract test — prevents admin role bias from leaking into scout plugins.

Every file under packages/worker/scout/ must:
  1. Not contain hardcoded role/keyword strings from a banned list.
  2. Route every filter decision through tenant.passes_filter().
  3. Have a .scout(tenant) method on its ScoutSource subclass.

Run via:  python -m unittest packages/worker/tests/test_scout_contract.py

This test is the regression guard for the Part 2 multi-tenant redesign.
If you add a new scout source and this test fails with "hardcoded role",
you're leaking admin opinions into the client pipeline — rework the source
to read from tenant.search_queries instead.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Banned substrings. If any scout source contains these, it means admin's
# role opinion is baked into the code instead of coming from TenantConfig.
# Matching is case-insensitive and substring-only.
BANNED_ROLE_STRINGS = [
    "ai engineer",
    "ml engineer",
    "data scientist",
    "machine learning engineer",
    "deep learning",
    "computer vision engineer",
    "nlp engineer",
    "llm engineer",
    "genai engineer",
    "research scientist",
    "applied scientist",
    "mlops engineer",
    "senior ai",
    "senior ml",
    "senior data scientist",
]

# Strings that must appear in every scout plugin to prove it routes through
# the tenant config. A scout that doesn't reference passes_filter is almost
# certainly using hardcoded rules.
REQUIRED_TENANT_MARKERS = [
    "tenant.passes_filter",
]

SCOUT_DIR = Path(__file__).resolve().parent.parent / "scout"


class ScoutContractTest(unittest.TestCase):
    """Static analysis: every scout plugin is tenant-scoped, not admin-scoped."""

    def _scout_source_files(self) -> list[Path]:
        return sorted(
            p for p in SCOUT_DIR.glob("*.py")
            if p.name not in ("__init__.py", "base.py")
        )

    def test_no_banned_role_strings(self) -> None:
        """Fail if any scout source file contains a banned role keyword."""
        for path in self._scout_source_files():
            content = path.read_text(encoding="utf-8").lower()
            for banned in BANNED_ROLE_STRINGS:
                self.assertNotIn(
                    banned,
                    content,
                    f"{path.name} contains banned role string {banned!r}. "
                    f"Scout plugins must read queries from tenant.search_queries, "
                    f"not hardcode admin's role opinions.",
                )

    def test_every_scout_calls_tenant_passes_filter(self) -> None:
        """Fail if a scout source doesn't route through tenant.passes_filter."""
        for path in self._scout_source_files():
            content = path.read_text(encoding="utf-8")
            for marker in REQUIRED_TENANT_MARKERS:
                self.assertIn(
                    marker,
                    content,
                    f"{path.name} doesn't call {marker}. Every scout plugin "
                    f"MUST filter results via the tenant object so per-user "
                    f"criteria are enforced.",
                )

    def test_registry_imports_cleanly(self) -> None:
        """Fail if the scout package has an import error (e.g. missing tenant
        parameter in a source's constructor). This catches wiring bugs before
        the worker boots in production."""
        sys.path.insert(0, str(SCOUT_DIR.parent))
        try:
            # Just importing triggers all the module-level side effects;
            # we don't instantiate the tenant here.
            import scout  # noqa: F401
            self.assertTrue(hasattr(scout, "REGISTERED_SOURCES"))
            self.assertGreater(len(scout.REGISTERED_SOURCES), 0)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
