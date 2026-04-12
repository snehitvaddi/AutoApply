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

from .base import ScoutSource, JobPost
from .ashby import AshbyScout
from .greenhouse import GreenhouseScout
from .lever import LeverScout
from .indeed import IndeedScout
from .himalayas import HimalayasScout
from .linkedin_public import LinkedInPublicScout

REGISTERED_SOURCES: list[ScoutSource] = [
    AshbyScout(),
    GreenhouseScout(),
    LeverScout(),
    IndeedScout(),
    HimalayasScout(),
    LinkedInPublicScout(),
]

__all__ = ["ScoutSource", "JobPost", "REGISTERED_SOURCES"]
