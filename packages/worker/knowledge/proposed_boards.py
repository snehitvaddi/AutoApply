"""Proposed-boards store — brain proposes new ATS slugs for the GLOBAL pool.

The scout's `_expand_tenant_boards()` already auto-grows each tenant's prefs
when `ats_resolver` finds a new slug for a company. But `default_boards.py`
(the global pool that benefits every tenant) is hand-maintained — discovery
on tenant A never reaches tenant B until an operator manually appends.

This module bridges that gap: the brain calls `propose_board(slug, ats,
evidence)` whenever it sees a real ATS slug worth promoting. Proposals
accumulate in `proposed-boards.json`. The operator reviews them
periodically and rolls the high-confidence ones into `default_boards.py`.

Schema for one proposal:
  {
    "ats": "ashby",
    "slug": "newco",
    "evidence": "Found via google search for 'newco careers ashby'",
    "first_seen": "2026-05-04T15:10:00Z",
    "last_seen":  "2026-05-04T17:42:00Z",
    "occurrences": 3
  }

Idempotent on (ats, slug): re-proposing bumps `occurrences` and `last_seen`
instead of appending a duplicate row. High-occurrence proposals float to
the top of the list when sorted, signalling operator priority.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_PATH = Path(__file__).resolve().parent / "proposed-boards.json"


def _read_all() -> dict[str, Any]:
    if not _PATH.exists():
        return {"proposals": []}
    try:
        with open(_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"proposals": []}
        if not isinstance(data.get("proposals"), list):
            data["proposals"] = []
        return data
    except (OSError, json.JSONDecodeError):
        return {"proposals": []}


def _write_atomic(doc: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".proposed-", suffix=".json.tmp", dir=str(_PATH.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(doc, f, indent=2, default=str)
            f.write("\n")
        os.replace(tmp_path, _PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def propose(slug: str, ats: str, evidence: str = "") -> dict[str, Any]:
    """Record a proposal. Idempotent on (ats, slug) — bumps occurrences."""
    slug = (slug or "").strip().lower()
    ats = (ats or "").strip().lower()
    if not slug or not ats:
        return {"ok": False, "error": "slug and ats are required"}

    now = datetime.now(timezone.utc).isoformat()
    doc = _read_all()
    proposals = doc["proposals"]
    for p in proposals:
        if p.get("slug") == slug and p.get("ats") == ats:
            p["occurrences"] = int(p.get("occurrences") or 1) + 1
            p["last_seen"] = now
            if evidence and not p.get("evidence"):
                p["evidence"] = evidence[:500]
            _write_atomic(doc)
            return {"ok": True, "stored": p, "is_new": False}

    entry = {
        "ats": ats,
        "slug": slug,
        "evidence": (evidence or "")[:500],
        "first_seen": now,
        "last_seen": now,
        "occurrences": 1,
    }
    proposals.append(entry)
    _write_atomic(doc)
    return {"ok": True, "stored": entry, "is_new": True}


def list_proposals(min_occurrences: int = 1) -> list[dict[str, Any]]:
    """Return proposals sorted by occurrences desc (highest priority first)."""
    doc = _read_all()
    items = [p for p in doc.get("proposals", [])
             if int(p.get("occurrences") or 0) >= max(1, min_occurrences)]
    items.sort(key=lambda p: (int(p.get("occurrences") or 0), p.get("last_seen") or ""), reverse=True)
    return items
