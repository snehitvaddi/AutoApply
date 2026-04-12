"""
Persistent chat history for the ApplyLoop desktop app.

One SQLite file at ~/.autoapply/workspace/chat.db holds every message that
ever flows through the chat pipeline, regardless of whether the source was
the web chat UI, the Claude PTY, or a Telegram message. Survives app
restarts, session restarts, and reinstalls (since workspace/ is not wiped
by `applyloop update`).

Design notes
------------
- WAL mode: the FastAPI app can read while the PTY reader task is writing
  without blocking. Concurrent reads are fine.
- One row per logical message. We do NOT stream PTY output byte-by-byte
  into the DB — that would produce thousands of rows per session with
  mid-word splits. Instead the caller is responsible for chunking at
  sensible boundaries (a complete Claude reply, a full status line, a
  session boundary, a user input event).
- `kind` is a discriminator so the UI can render different row types
  (plain text vs a full-width session divider vs a tool-call summary).
- `meta_json` is a TEXT column holding arbitrary JSON — no schema
  migration needed when we want to add fields like telegram_msg_id or
  pty_session_id.
- Retention: 90 days by default. A `vacuum_old()` helper runs on app
  startup and clears rows older than that. Rough sizing at 200 msgs/day
  is ~7 MB for the full 90-day window — tiny.

Threading
---------
Each call opens its own connection. SQLite in WAL mode is designed for
this. We don't hold a long-lived shared connection because some callers
live in the FastAPI event loop (where sync SQLite would block) and some
live in the PTY async reader task.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("server.chat_log")

# ── Paths ────────────────────────────────────────────────────────────────
_WORKSPACE = Path(os.environ.get("APPLYLOOP_WORKSPACE") or os.path.expanduser("~/.autoapply/workspace"))
DB_PATH = _WORKSPACE / "chat.db"

# ── Retention ────────────────────────────────────────────────────────────
DEFAULT_RETENTION_DAYS = 90

# ── Sender tags ──────────────────────────────────────────────────────────
# We keep these as strings instead of an enum so callers can invent new
# sources (e.g. future "user:ios") without touching this file.
SENDER_USER_UI = "user:ui"           # typed in the desktop chat tab
SENDER_USER_TG = "user:tg"           # came in from Telegram
SENDER_USER_TERMINAL = "user:term"   # typed directly into the xterm tab
SENDER_CLAUDE = "claude"             # PTY output from Claude
SENDER_SYSTEM = "system"             # session boundaries + app-level notices

# ── Kinds ────────────────────────────────────────────────────────────────
KIND_TEXT = "text"
KIND_SESSION_BOUNDARY = "session_boundary"
KIND_TOOL_CALL = "tool_call"
KIND_NOTICE = "notice"  # app-level info like "scout loop started"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL,
  ts_ms       INTEGER NOT NULL,
  sender      TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'text',
  content     TEXT NOT NULL,
  meta_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_ts
  ON chat_messages(session_id, ts_ms);
CREATE INDEX IF NOT EXISTS idx_chat_messages_ts
  ON chat_messages(ts_ms);
"""


# ── Secret redaction ─────────────────────────────────────────────────────
# Conservative regexes: catches Telegram bot tokens, long hex secrets,
# and anything that looks like an API key with a common prefix. We don't
# attempt to be exhaustive — this is a safety net for accidental paste,
# not a defense against a motivated exfiltrator.
_REDACTORS = [
    # Telegram bot tokens: "1234567890:ABCdef-GhIJkl..."
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{25,}\b"), "[redacted-telegram-bot-token]"),
    # Generic bearer secrets: sk_live_, pk_live_, sk_test_, al_, Bearer foo...
    (re.compile(r"\b(sk|pk|rk|ak|al|sbp|fr)_[A-Za-z0-9]{20,}\b"), "[redacted-api-key]"),
    # Long hex strings (32+ hex chars)
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[redacted-hex]"),
    # `password` / `app_password` / `secret` key=value lines
    (re.compile(r"(?i)\b(password|app_password|secret|token)=[^\s]{6,}"), lambda m: m.group(1) + "=[redacted]"),
    # Bearer tokens
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-~+/=]{20,}"), "Bearer [redacted]"),
]


def redact_secrets(text: str) -> str:
    """Strip obvious credentials out of a message body before writing to
    the DB. Not a full DLP solution — a safety net for accidental paste."""
    if not text:
        return text
    for rx, repl in _REDACTORS:
        text = rx.sub(repl if isinstance(repl, str) else repl, text)
    return text


# ── ANSI/control-byte stripping ──────────────────────────────────────────
# We store clean text in the DB, not raw PTY bytes. Strip escape sequences
# and non-printable control characters before persisting.
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()#][\x20-\x7e]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")


def clean_pty_bytes(payload: bytes | str) -> str:
    """Turn raw PTY output into a storable UTF-8 string.

    Drops ANSI color/cursor codes, OSC sequences, and non-printable control
    characters — but keeps newlines, tabs, and regular text. Returns
    empty string if the cleaned payload has no visible characters.
    """
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8", errors="replace")
        except Exception:
            return ""
    else:
        text = payload
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    # Collapse CR-LF / CR to LF so message previews look clean
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


# ── Connection helpers ───────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    """Open a short-lived connection with WAL mode enabled.

    Callers should use this in a with-block (sqlite3 connections are
    context managers) so the commit + close is automatic.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Ensure the schema exists. Safe to call many times; idempotent."""
    try:
        with _connect() as conn:
            conn.executescript(_SCHEMA)
        logger.info(f"chat_log: ready at {DB_PATH}")
    except Exception as e:
        logger.warning(f"chat_log init failed: {e}")


# ── Public API ───────────────────────────────────────────────────────────
def append_message(
    *,
    session_id: str,
    sender: str,
    content: str,
    kind: str = KIND_TEXT,
    meta: dict | None = None,
    ts_ms: int | None = None,
    skip_empty: bool = True,
) -> str | None:
    """Persist one message. Returns the new row id, or None if the row
    was skipped (empty content, DB error).

    Callers MUST pass the chunked-logical-message body, not raw streaming
    bytes. The pty_terminal async reader batches output at newline
    boundaries or idle pauses before calling this.
    """
    try:
        clean = redact_secrets(content or "").strip()
        if skip_empty and not clean:
            return None
        row_id = uuid.uuid4().hex
        now_ms = ts_ms if ts_ms is not None else int(time.time() * 1000)
        meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        with _connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages (id, session_id, ts_ms, sender, kind, content, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row_id, session_id or "unknown", now_ms, sender, kind, clean, meta_json),
            )
        return row_id
    except Exception as e:
        logger.warning(f"chat_log append failed: {e}")
        return None


def get_history(
    *,
    since_ms: int | None = None,
    until_ms: int | None = None,
    limit: int = 200,
    session_id: str | None = None,
) -> list[dict]:
    """Return messages newest-first by default. Use since_ms + limit for
    infinite-scroll-up pagination: pass the oldest ts you already have as
    since_ms, get the next page older than that.

    Returns a list of dicts shaped like the DB row plus parsed meta.
    """
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if since_ms is not None:
            clauses.append("ts_ms > ?")
            params.append(since_ms)
        if until_ms is not None:
            clauses.append("ts_ms < ?")
            params.append(until_ms)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, session_id, ts_ms, sender, kind, content, meta_json "
            f"FROM chat_messages {where} "
            "ORDER BY ts_ms DESC "
            "LIMIT ?"
        )
        params.append(max(1, min(limit, 1000)))
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        # Reverse so the oldest-in-page comes first (natural chat render order)
        out: list[dict] = []
        for r in reversed(rows):
            out.append({
                "id": r["id"],
                "session_id": r["session_id"],
                "ts_ms": r["ts_ms"],
                "sender": r["sender"],
                "kind": r["kind"],
                "content": r["content"],
                "meta": json.loads(r["meta_json"]) if r["meta_json"] else None,
            })
        return out
    except Exception as e:
        logger.warning(f"chat_log get_history failed: {e}")
        return []


def get_sessions(limit: int = 50) -> list[dict]:
    """Return the list of session_boundary rows so the UI can render a
    session-switcher or jump-to-session nav."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, session_id, ts_ms, content, meta_json "
                "FROM chat_messages WHERE kind = ? "
                "ORDER BY ts_ms DESC LIMIT ?",
                (KIND_SESSION_BOUNDARY, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "ts_ms": r["ts_ms"],
                "content": r["content"],
                "meta": json.loads(r["meta_json"]) if r["meta_json"] else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"chat_log get_sessions failed: {e}")
        return []


def vacuum_old(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete rows older than retention_days. Returns the count deleted.

    Called from the FastAPI lifespan startup once per app boot; with
    normal use that's plenty frequent for a 90-day window.
    """
    try:
        cutoff = int((time.time() - retention_days * 86400) * 1000)
        with _connect() as conn:
            cur = conn.execute("DELETE FROM chat_messages WHERE ts_ms < ?", (cutoff,))
            deleted = cur.rowcount or 0
            if deleted > 0:
                conn.execute("VACUUM")
        if deleted > 0:
            logger.info(f"chat_log: vacuumed {deleted} row(s) older than {retention_days}d")
        return deleted
    except Exception as e:
        logger.warning(f"chat_log vacuum failed: {e}")
        return 0


def clear_all() -> int:
    """Nuclear wipe. Returns row count deleted. For DELETE /api/chat/history."""
    try:
        with _connect() as conn:
            cur = conn.execute("DELETE FROM chat_messages")
            deleted = cur.rowcount or 0
            conn.execute("VACUUM")
        logger.info(f"chat_log: cleared all ({deleted} rows)")
        return deleted
    except Exception as e:
        logger.warning(f"chat_log clear_all failed: {e}")
        return 0


def append_session_boundary(session_id: str, pid: int | None = None, cwd: str | None = None) -> str | None:
    """Helper for the PTY spawn path. Writes a kind=session_boundary row
    that the UI renders as a full-width 'New session started' divider."""
    from datetime import datetime
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [f"New session started at {stamp}"]
    if pid is not None:
        parts.append(f"PID {pid}")
    if cwd:
        parts.append(f"cwd={cwd}")
    content = " · ".join(parts)
    return append_message(
        session_id=session_id,
        sender=SENDER_SYSTEM,
        content=content,
        kind=KIND_SESSION_BOUNDARY,
        meta={"pid": pid, "cwd": cwd},
    )
