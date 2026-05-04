"""Brain-driven scout plan.

Today's scout pipeline is fully deterministic — REGISTERED_SOURCES is
a fixed list, every cycle runs every source against every query in
tenant.search_queries. That's reliable but inflexible: if LinkedIn
is rate-limited today, scout still wastes a cycle on it; if the user
has 5 near-duplicate queries, scout fans out 5×.

This module is the brain's lever to bias the deterministic loop on a
per-cycle basis. The brain writes a small JSON file via the
`scout_set_plan` MCP tool; the worker's run_scout_cycle reads it at
the top of each cycle and narrows source/query iteration accordingly.
The plan has a TTL so a stale brain decision can't keep biasing the
worker indefinitely — once it expires, behavior reverts to the
default REGISTERED_SOURCES + tenant.search_queries.

Plan JSON shape:
  {
    "version": 1,
    "set_at": ISO8601 UTC,
    "ttl_minutes": 240,
    "set_by": "brain" | "operator" | "auto",
    "sources": [<source.name>, ...] | null,    # null = all
    "queries": ["...", ...] | null,            # null = tenant defaults
    "max_per_source": int | null,              # null = unlimited
    "notes": "free-text rationale (human or brain)"
  }

Stored at:
  ~/.autoapply/workspace/scout-plan.json
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Match the LOCAL_DB workspace dir so the plan lives next to the SQLite
# file the worker already manages — one canonical workspace, one bag
# of files. Override via APPLYLOOP_SCOUT_PLAN env if needed for tests.
_DEFAULT_PATH = Path(
    os.environ.get(
        "APPLYLOOP_SCOUT_PLAN",
        os.path.expanduser("~/.autoapply/workspace/scout-plan.json"),
    )
)


def _read() -> dict[str, Any] | None:
    if not _DEFAULT_PATH.exists():
        return None
    try:
        with open(_DEFAULT_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def _write_atomic(plan: dict[str, Any]) -> None:
    """tempfile + os.replace = atomic update; readers never see a half-
    written file even when brain races scout on a refresh."""
    _DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".scout-plan-", suffix=".json.tmp", dir=str(_DEFAULT_PATH.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(plan, f, indent=2, default=str)
            f.write("\n")
        os.replace(tmp_path, _DEFAULT_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_active_plan() -> dict[str, Any] | None:
    """Return the current plan if it's not stale (set_at + ttl_minutes
    is still in the future), else None.

    The worker calls this at the top of run_scout_cycle. None means
    'no plan, run the default loop'. A stale plan never silently keeps
    influencing scout — once expired, it's the same as missing.
    """
    plan = _read()
    if not plan:
        return None
    set_at_raw = plan.get("set_at") or ""
    ttl_min = int(plan.get("ttl_minutes") or 0)
    if not set_at_raw or ttl_min <= 0:
        # No timestamp / no TTL → treat as expired-already, defensive.
        return None
    try:
        set_at = datetime.fromisoformat(set_at_raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if set_at.tzinfo is None:
        set_at = set_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= set_at + timedelta(minutes=ttl_min):
        return None
    return plan


def set_plan(
    sources: list[str] | None = None,
    queries: list[str] | None = None,
    max_per_source: int | None = None,
    ttl_minutes: int = 240,
    notes: str = "",
    set_by: str = "brain",
) -> dict[str, Any]:
    """Persist a new plan, replacing whatever's there.

    `sources`: list of source NAMES to run (others are skipped). None
        keeps the default (run all enabled sources).
    `queries`: list of search queries to use (overrides tenant.search_queries
        for THIS scout). None keeps tenant defaults. Use to deduplicate
        ("Engineer" + "Senior Engineer" + "Sr. Engineer" → just one).
    `max_per_source`: cap the number of jobs PER source per cycle.
        None = unlimited. Use to throttle a noisy source (LinkedIn
        burning bandwidth on irrelevant titles).
    `ttl_minutes`: how long the plan stays in force. After this it
        expires and worker reverts to defaults. Default 4 hours so a
        forgotten plan doesn't lock behavior in for days.
    `notes`: free-text reasoning. Brain should explain why — useful
        for debugging "why didn't scout run X today" questions.
    `set_by`: who wrote the plan ("brain", "operator", "auto").
    """
    plan = {
        "version": 1,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "ttl_minutes": int(ttl_minutes),
        "set_by": set_by,
        "sources": list(sources) if sources is not None else None,
        "queries": list(queries) if queries is not None else None,
        "max_per_source": int(max_per_source) if max_per_source else None,
        "notes": notes or "",
    }
    _write_atomic(plan)
    return plan


def clear_plan() -> bool:
    """Remove any stored plan. Worker reverts to default REGISTERED_SOURCES
    + tenant.search_queries on the next cycle."""
    if _DEFAULT_PATH.exists():
        try:
            _DEFAULT_PATH.unlink()
            return True
        except OSError:
            return False
    return False


def applies_to_source(plan: dict[str, Any] | None, source_name: str) -> bool:
    """True if `source_name` should run under the given plan. With no
    plan or null sources field, all sources run."""
    if plan is None:
        return True
    allowed = plan.get("sources")
    if allowed is None:
        return True
    return source_name in allowed


def effective_queries(
    plan: dict[str, Any] | None, tenant_defaults: list[str]
) -> list[str]:
    """Return the query list for THIS scout cycle. Plan overrides
    tenant defaults when present; otherwise tenant defaults pass through
    unchanged."""
    if plan is None:
        return list(tenant_defaults)
    queries = plan.get("queries")
    if queries is None:
        return list(tenant_defaults)
    return [str(q) for q in queries if str(q).strip()]
