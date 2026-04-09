"""
Read application data from the local SQLite database.

Database: ~/.openclaw/agents/job-bot/workspace/applications.db

Schema:
  applications(id, company, role, url, ats, source, location, posted_at,
               scouted_at, applied_at, updated_at, status, notes, screenshot, dedup_token)

  status enum: scouted, queued, applying, submitted, failed, skipped, blocked, interview, rejected, offer
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get(
    "APPLYLOOP_DB",
    Path.home() / ".autoapply" / "workspace" / "applications.db"
))

# Fallback: check the legacy OpenClaw path if the default doesn't exist
if not DB_PATH.exists():
    _legacy = Path.home() / ".openclaw" / "agents" / "job-bot" / "workspace" / "applications.db"
    if _legacy.exists():
        DB_PATH = _legacy
        logger.info(f"Using legacy DB path: {DB_PATH}")


def _connect() -> sqlite3.Connection | None:
    """Open a read-only connection to the SQLite database."""
    if not DB_PATH.exists():
        logger.warning(f"Database not found: {DB_PATH}")
        return None
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a query and return list of dicts."""
    conn = _connect()
    if not conn:
        return []
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _query_one(sql: str, params: tuple = ()) -> dict:
    """Run a query and return single dict."""
    conn = _connect()
    if not conn:
        return {}
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def get_stats() -> dict:
    """Dashboard stat cards."""
    conn = _connect()
    if not conn:
        return {"applied_today": 0, "total_applied": 0, "in_queue": 0, "success_rate": 0}
    try:
        total_submitted = conn.execute("SELECT COUNT(*) FROM applications WHERE status='submitted'").fetchone()[0]
        total_failed = conn.execute("SELECT COUNT(*) FROM applications WHERE status='failed'").fetchone()[0]
        in_queue = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('queued','scouted')").fetchone()[0]
        today_submitted = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status='submitted' AND applied_at LIKE ? || '%'",
            (__import__('datetime').date.today().isoformat(),)
        ).fetchone()[0]

        total = total_submitted + total_failed
        rate = round(total_submitted / total * 100) if total > 0 else 0

        return {
            "applied_today": today_submitted,
            "total_applied": total_submitted,
            "in_queue": in_queue,
            "success_rate": rate,
            "total_failed": total_failed,
        }
    finally:
        conn.close()


def get_daily_breakdown() -> list[dict]:
    """Applications per day for the area chart."""
    rows = _query("""
        SELECT
            strftime('%Y-%m-%d', applied_at) as date,
            SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) as submitted,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed
        FROM applications
        WHERE status IN ('submitted','failed') AND applied_at IS NOT NULL
        GROUP BY strftime('%Y-%m-%d', applied_at)
        ORDER BY date
    """)
    # Format dates as "Mar 9" style
    from datetime import datetime
    result = []
    for r in rows[-30:]:
        try:
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            label = dt.strftime("%b %-d")
        except (ValueError, TypeError):
            label = r["date"] or "?"
        result.append({"date": label, "submitted": r["submitted"], "failed": r["failed"]})
    return result


def get_ats_breakdown() -> list[dict]:
    """Applications by ATS platform (submitted only)."""
    rows = _query("""
        SELECT COALESCE(ats, '') as ats, COUNT(*) as count
        FROM applications
        WHERE status='submitted'
        GROUP BY ats
        ORDER BY count DESC
        LIMIT 6
    """)
    total = sum(r["count"] for r in rows) or 1
    return [{"name": _normalize_ats(r["ats"]) or "Other", "value": round(r["count"] / total * 100)} for r in rows]


def get_recent_applications(limit: int = 20) -> list[dict]:
    """Most recent applications — balanced mix of submitted and failed."""
    # Get recent submitted
    submitted = _query("""
        SELECT company, role as title, ats, status, applied_at
        FROM applications WHERE status='submitted'
        ORDER BY applied_at DESC LIMIT ?
    """, (int(limit * 0.7),))

    # Get recent failed
    failed = _query("""
        SELECT company, role as title, ats, status, applied_at
        FROM applications WHERE status='failed'
        ORDER BY applied_at DESC LIMIT ?
    """, (limit - len(submitted),))

    # Merge and sort
    mixed = submitted + failed
    mixed.sort(key=lambda e: e.get("applied_at") or "", reverse=True)

    for r in mixed:
        r["ats"] = _normalize_ats(r.get("ats", ""))
    return mixed[:limit]


def get_pipeline() -> dict:
    """Pipeline/queue view grouped by status."""
    pipeline = {"discovered": [], "queued": [], "applying": [], "submitted": [], "failed": []}

    for status_key, sql_status in [
        ("queued", "('queued','scouted')"),
        ("applying", "('applying')"),
        ("submitted", "('submitted')"),
        ("failed", "('failed')"),
    ]:
        rows = _query(f"""
            SELECT id, company, role as title, ats, applied_at as posted_at, status, notes as error
            FROM applications
            WHERE status IN {sql_status}
            ORDER BY applied_at DESC
            LIMIT 50
        """)
        for r in rows:
            r["ats"] = _normalize_ats(r.get("ats", ""))
        pipeline[status_key] = rows

    return pipeline


def _write_connect() -> sqlite3.Connection | None:
    """Open a writable connection to the SQLite database."""
    if not DB_PATH or not DB_PATH.exists():
        return None
    return sqlite3.connect(str(DB_PATH))


def delete_from_queue(job_id: int) -> bool:
    """Delete a job from the queue (only queued/scouted status)."""
    conn = _write_connect()
    if not conn:
        return False
    try:
        result = conn.execute(
            "DELETE FROM applications WHERE id=? AND status IN ('queued','scouted')",
            (job_id,)
        )
        conn.commit()
        return result.rowcount > 0
    finally:
        conn.close()


def clear_queue() -> int:
    """Delete ALL queued/scouted jobs. Returns count deleted."""
    conn = _write_connect()
    if not conn:
        return 0
    try:
        result = conn.execute("DELETE FROM applications WHERE status IN ('queued','scouted')")
        conn.commit()
        return result.rowcount
    finally:
        conn.close()


def get_recent_activity(since: str | None = None, limit: int = 50) -> list[dict]:
    """
    Get recent activity for the Chat status feed.
    Returns newest entries first, optionally since a timestamp.
    """
    if since:
        rows = _query("""
            SELECT id, company, role as title, ats, status, applied_at, notes
            FROM applications
            WHERE applied_at > ? AND status IN ('submitted','failed','queued','scouted')
            ORDER BY applied_at DESC LIMIT ?
        """, (since, limit))
    else:
        rows = _query("""
            SELECT id, company, role as title, ats, status, applied_at, notes
            FROM applications
            WHERE status IN ('submitted','failed','queued','scouted')
            ORDER BY applied_at DESC LIMIT ?
        """, (limit,))

    for r in rows:
        r["ats"] = _normalize_ats(r.get("ats", ""))
    return rows


def get_queue_count() -> int:
    """Get current queue size."""
    result = _query("SELECT COUNT(*) as c FROM applications WHERE status IN ('queued','scouted')")
    return result[0]["c"] if result else 0


def _normalize_ats(raw: str | None) -> str:
    """Normalize ATS names for display."""
    if not raw:
        return ""
    lower = raw.lower()
    if "greenhouse" in lower:
        return "Greenhouse"
    if "ashby" in lower:
        return "Ashby"
    if "lever" in lower:
        return "Lever"
    if "workday" in lower:
        return "Workday"
    if "smartrecruiters" in lower:
        return "SmartRecruiters"
    if "icims" in lower:
        return "iCIMS"
    return raw.title() if raw else ""
