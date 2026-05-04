"""Self-learning patterns for the brain.

When the brain successfully drives an apply on a new (or quirky) ATS,
it records the field mappings + quirks here via the MCP tool
`knowledge_record_pattern`. Future applies on the same ATS read these
entries through `knowledge_get_ats_playbook` so the brain doesn't
re-derive the form structure from scratch every time.

Storage: a single JSON file
`packages/worker/knowledge/learned-patterns.json`. Append-only by
design — patterns accumulate, success_count increments on a hit,
nothing is mutated in place. Concurrent writers (rare — one brain at
a time) tolerate via a tiny file-lock dance.

Schema for one pattern:
  {
    "ats": "icims",                       # canonical ATS slug
    "hostname": "careers.acme.com",       # apply-URL hostname
    "discovered_at": "2026-05-04T12:00:00Z",
    "last_used_at": "2026-05-04T12:00:00Z",
    "success_count": 1,
    "fields": [
      {"label": "First name", "selector": "input#firstName",
       "value_source": "profile.first_name", "input_kind": "text"},
      ...
    ],
    "quirks": [
      "Submit button is delayed; wait 3s after upload before clicking",
      ...
    ],
    "notes": "Free-text from the brain about anything else worth knowing."
  }
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# File lives alongside ats-playbook.md so brain.prompts.load_ats_playbook
# can find both with one relative path.
_LEARNED_PATH = Path(__file__).resolve().parent / "learned-patterns.json"


def _read_all() -> dict[str, Any]:
    """Return the full document. Empty-but-valid shape on first read or
    on parse error — never raises, since a corrupted file shouldn't kill
    the apply loop."""
    if not _LEARNED_PATH.exists():
        return {"patterns": []}
    try:
        with open(_LEARNED_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"patterns": []}
        if not isinstance(data.get("patterns"), list):
            data["patterns"] = []
        return data
    except (OSError, json.JSONDecodeError):
        return {"patterns": []}


def _write_atomic(doc: dict[str, Any]) -> None:
    """Atomic write so a concurrent reader never sees a half-written
    file. tempfile in the same directory + os.replace is POSIX-atomic."""
    _LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".learned-", suffix=".json.tmp", dir=str(_LEARNED_PATH.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(doc, f, indent=2, default=str)
            f.write("\n")
        os.replace(tmp_path, _LEARNED_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def record_pattern(
    ats: str,
    hostname: str,
    fields: list[dict[str, Any]] | None = None,
    quirks: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Append a new pattern OR bump success_count if (ats, hostname)
    already has one with the same field-set fingerprint.

    Brain MCP wrapper validates inputs before calling, so this stays
    permissive — anything that JSON-serializes is fine. Returns the
    final stored entry so the brain has a confirmation it can log.
    """
    ats = (ats or "").strip().lower()
    hostname = (hostname or "").strip().lower()
    if not ats or not hostname:
        return {"ok": False, "error": "ats and hostname are required"}

    fields = list(fields or [])
    quirks = list(quirks or [])
    now = datetime.now(timezone.utc).isoformat()
    doc = _read_all()
    patterns = doc["patterns"]

    # De-dupe by (ats, hostname, field_label_set) so re-running an
    # apply doesn't double-write. The label set is a coarse fingerprint
    # but it's good enough — the actual selectors evolve as the form
    # changes, so we don't want them in the hash.
    field_labels = tuple(sorted((f.get("label") or "").lower() for f in fields))
    for entry in patterns:
        if (
            entry.get("ats") == ats
            and entry.get("hostname") == hostname
            and tuple(sorted((f.get("label") or "").lower() for f in (entry.get("fields") or []))) == field_labels
        ):
            entry["last_used_at"] = now
            entry["success_count"] = int(entry.get("success_count") or 0) + 1
            # Merge new quirks (brain may have learned more this run).
            existing_quirks = set(entry.get("quirks") or [])
            for q in quirks:
                existing_quirks.add(q)
            entry["quirks"] = sorted(existing_quirks)
            if notes and notes not in (entry.get("notes") or ""):
                # Append rather than replace so we don't lose history.
                entry["notes"] = f"{entry.get('notes', '').rstrip()}\n---\n{notes}".strip()
            _write_atomic(doc)
            return {"ok": True, "action": "incremented", "entry": entry}

    new_entry = {
        "ats": ats,
        "hostname": hostname,
        "discovered_at": now,
        "last_used_at": now,
        "success_count": 1,
        "fields": fields,
        "quirks": quirks,
        "notes": notes or "",
    }
    patterns.append(new_entry)
    _write_atomic(doc)
    return {"ok": True, "action": "created", "entry": new_entry}


def get_learned(ats: str | None = None, hostname: str | None = None) -> list[dict[str, Any]]:
    """Return matching learned patterns, newest first.

    - ats only → all patterns for that ATS, regardless of hostname
    - hostname only → all patterns for that hostname, any ATS
    - both → narrow match
    - neither → all patterns

    Sorted by last_used_at DESC so the most recently confirmed pattern
    surfaces first (brain prefers fresh over stale).
    """
    doc = _read_all()
    out = []
    a = (ats or "").strip().lower() or None
    h = (hostname or "").strip().lower() or None
    for p in doc.get("patterns") or []:
        if a and p.get("ats") != a:
            continue
        if h and p.get("hostname") != h:
            continue
        out.append(p)
    out.sort(key=lambda x: x.get("last_used_at") or "", reverse=True)
    return out


def format_for_prompt(entries: list[dict[str, Any]]) -> str:
    """Render entries as a markdown block the brain can drop into a
    prompt verbatim. Keeps the same shape as ats-playbook.md sections
    so brain doesn't have to learn a new format."""
    if not entries:
        return ""
    lines: list[str] = ["", "### Learned patterns (auto-recorded)", ""]
    for e in entries[:5]:  # cap at 5 so the prompt doesn't bloat
        lines.append(
            f"- **{e.get('ats', '?')} @ {e.get('hostname', '?')}** "
            f"(success_count={e.get('success_count', 0)}, "
            f"last_used={e.get('last_used_at', '?')[:10]})"
        )
        for f in (e.get("fields") or [])[:20]:
            lines.append(
                f"  - field: {f.get('label', '?')!r} → "
                f"selector `{f.get('selector', '?')}` "
                f"({f.get('value_source', '?')}, {f.get('input_kind', 'text')})"
            )
        for q in (e.get("quirks") or [])[:10]:
            lines.append(f"  - quirk: {q}")
        if e.get("notes"):
            lines.append(f"  - notes: {e['notes'][:300]}")
        lines.append("")
    return "\n".join(lines)
