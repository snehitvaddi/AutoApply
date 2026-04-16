"""Scout plugin registry.

Every entry in REGISTERED_SOURCES is a concrete ScoutSource that the worker
calls with the current tenant's TenantConfig. Adding a new source (e.g.
Dice, YCombinator jobs page) means:
  1. Create packages/worker/scout/<name>.py subclassing ScoutSource
  2. Implement .scout(tenant) using ONLY tenant.* fields (no hardcoded roles)
  3. Add it to REGISTERED_SOURCES below
  4. Ship. Every tenant's next scout cycle will use it with their own criteria.

tests/test_scout_contract.py enforces that no source file contains hardcoded
role strings like "AI Engineer", "Machine Learning", or "Data Scientist".
"""
from __future__ import annotations

import logging

from .base import ScoutSource, JobPost
from .ashby import AshbyScout
from .greenhouse import GreenhouseScout
from .lever import LeverScout
from .indeed import IndeedScout
from .himalayas import HimalayasScout

_logger = logging.getLogger(__name__)

REGISTERED_SOURCES: list[ScoutSource] = [
    AshbyScout(),
    GreenhouseScout(),
    LeverScout(),
    IndeedScout(),
    HimalayasScout(),
]

# LinkedInPublicScout is registered conditionally. It depends on scrapling,
# which in turn eagerly imports optional deps (curl_cffi, browserforge, ...)
# that aren't always installable on every platform (Windows CI, minimal
# installs). Lazy-import so the registry survives a missing dep and the
# worker can still scout the five primary sources.
try:
    from .linkedin_public import LinkedInPublicScout
    REGISTERED_SOURCES.append(LinkedInPublicScout())
except ImportError as _e:
    _logger.warning(
        "LinkedInPublicScout unavailable — scout/__init__.py skipped it. "
        "Missing optional dep: %s. Install scrapling + its transitives "
        "(curl_cffi, browserforge) to enable.", _e,
    )

__all__ = ["ScoutSource", "JobPost", "REGISTERED_SOURCES"]
