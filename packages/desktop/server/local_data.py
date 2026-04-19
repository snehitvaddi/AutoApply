"""
Read application data from the local SQLite database.

Database: $APPLYLOOP_DB or ~/.autoapply/workspace/applications.db.
config.py propagates APPLYLOOP_WORKSPACE into APPLYLOOP_DB so every
per-tenant instance picks up its own file.

Schema:
  applications(id, company, role, url, ats, source, location, posted_at,
               scouted_at, applied_at, updated_at, status, notes, screenshot, dedup_token)

  status enum: scouted, queued, applying, submitted, failed, skipped, blocked, interview, rejected, offer
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

def _resolve_db_path() -> Path:
    """Pick the database path at call time so APPLYLOOP_DB / WORKSPACE changes stick."""
    env = os.environ.get("APPLYLOOP_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".autoapply" / "workspace" / "applications.db"


DB_PATH = _resolve_db_path()


# Schema mirrors packages/worker/pipeline.py::get_db — kept in sync so
# the desktop server can bootstrap a fresh workspace before the worker runs.
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL, role TEXT NOT NULL, url TEXT, ats TEXT,
    source TEXT, location TEXT, posted_at TEXT, scouted_at TEXT,
    applied_at TEXT, updated_at TEXT,
    status TEXT NOT NULL DEFAULT 'scouted'
        CHECK(status IN ('scouted','queued','applying','submitted','failed','skipped','blocked','interview','rejected','offer')),
    notes TEXT, screenshot TEXT, dedup_token TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_company ON applications(company);
CREATE INDEX IF NOT EXISTS idx_applied_at ON applications(applied_at);
CREATE INDEX IF NOT EXISTS idx_dedup ON applications(dedup_token);
"""


def _ensure_db_exists() -> Path:
    """Auto-create the workspace DB + schema on first call.

    Previously the desktop module would return empty dicts forever if the
    worker hadn't run yet, because the SQLite file didn't exist. Now we
    bootstrap an empty schema so every dashboard call at least returns valid
    (zero-row) results instead of silent failures.
    """
    global DB_PATH
    DB_PATH = _resolve_db_path()
    if DB_PATH.exists():
        return DB_PATH
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()
        logger.info(f"Bootstrapped empty applications.db at {DB_PATH}")
    except Exception as e:
        logger.warning(f"Could not bootstrap DB at {DB_PATH}: {e}")
    return DB_PATH


def _connect() -> sqlite3.Connection | None:
    """Open a read-only connection to the SQLite database.

    Auto-creates the workspace DB + schema if missing so the desktop dashboard
    never sits in a silent-empty state on a brand-new install.
    """
    path = _ensure_db_exists()
    if not path.exists():
        logger.warning(f"Database not found: {path}")
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
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
    """Dashboard stat cards.

    All "today" counting uses the USER'S LOCAL day. SQLite's `strftime` with
    the 'localtime' modifier converts the stored UTC timestamp to the local
    tz the server process is running in. This keeps applied_today, the daily
    chart, and the recent-activity list consistent — previously get_stats
    filtered by UTC-date (via Python's date.today()) while the chart grouped
    by UTC-date too, but Python's date.today() actually returns local date,
    so they disagreed whenever the user was west of UTC at night.
    """
    conn = _connect()
    if not conn:
        return {"applied_today": 0, "total_applied": 0, "in_queue": 0, "success_rate": 0}
    try:
        total_submitted = conn.execute("SELECT COUNT(*) FROM applications WHERE status='submitted'").fetchone()[0]
        total_failed = conn.execute("SELECT COUNT(*) FROM applications WHERE status='failed'").fetchone()[0]
        in_queue = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('queued','scouted')").fetchone()[0]
        # Count rows where applied_at (stored UTC) falls on today's LOCAL date.
        # strftime('%Y-%m-%d', applied_at, 'localtime') handles both tz-aware
        # ISO strings ("...+00:00") AND naked ISO ("...123456") consistently.
        today_submitted = conn.execute("""
            SELECT COUNT(*) FROM applications
            WHERE status='submitted'
              AND strftime('%Y-%m-%d', applied_at, 'localtime') = date('now', 'localtime')
        """).fetchone()[0]

        total = total_submitted + total_failed
        rate = round(total_submitted / total * 100) if total > 0 else 0
        # Live counters that were previously computed ad-hoc or not at all.
        # Surface them in get_stats() so the dashboard can render them
        # without adding a second polling endpoint.
        applying_now = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status='applying'"
        ).fetchone()[0]

        return {
            "applied_today": today_submitted,
            "total_applied": total_submitted,
            "in_queue": in_queue,
            "success_rate": rate,
            "total_failed": total_failed,
            "applying_now": applying_now,
            # Minutes since the last scout cycle. None if scout has never
            # run on this install. Rendered as "Last scout: Xm ago".
            "last_scout_min_ago": get_scout_age_minutes(),
        }
    finally:
        conn.close()


def get_daily_breakdown() -> list[dict]:
    """Applications per day for the area chart. Grouped by LOCAL date so it
    matches the 'applied_today' stat card and Recent Applications list."""
    rows = _query("""
        SELECT
            strftime('%Y-%m-%d', applied_at, 'localtime') as date,
            SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) as submitted,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed
        FROM applications
        WHERE status IN ('submitted','failed') AND applied_at IS NOT NULL
        GROUP BY strftime('%Y-%m-%d', applied_at, 'localtime')
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

    # Note: 'discovered' bucket collects scouted jobs (waiting to be queued). The UI
    # merges them with 'queued' for display, so both show up as "waiting to apply".
    for status_key, status_val, order_col in [
        ("discovered", "scouted", "scouted_at"),
        ("queued", "queued", "scouted_at"),
        ("applying", "applying", "updated_at"),
        ("submitted", "submitted", "applied_at"),
        ("failed", "failed", "updated_at"),
    ]:
        rows = _query(f"""
            SELECT id, company, role as title, url, ats, location,
                   COALESCE(applied_at, scouted_at, updated_at) as posted_at,
                   scouted_at, applied_at, updated_at,
                   status, notes as error, screenshot
            FROM applications
            WHERE status = ?
            ORDER BY
                CASE WHEN screenshot IS NOT NULL AND screenshot != '' THEN 0 ELSE 1 END,
                {order_col} DESC
            LIMIT 50
        """, (status_val,))
        for r in rows:
            r["ats"] = _normalize_ats(r.get("ats", ""))
        pipeline[status_key] = rows

    return pipeline


def get_currently_applying() -> dict | None:
    """Get the job currently being applied to (if any)."""
    row = _query_one("""
        SELECT id, company, role as title, url, ats, location, updated_at
        FROM applications WHERE status = 'applying'
        ORDER BY updated_at DESC LIMIT 1
    """)
    if row:
        row["ats"] = _normalize_ats(row.get("ats", ""))
    return row or None


def _write_connect() -> sqlite3.Connection | None:
    """Open a writable connection to the SQLite database."""
    path = _ensure_db_exists()
    if not path or not path.exists():
        return None
    return sqlite3.connect(str(path))


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


def get_stuck_jobs() -> list[dict]:
    """Get jobs stuck in 'applying' for more than 10 minutes."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    rows = _query(
        "SELECT id, company, role as title, url, ats, location, updated_at "
        "FROM applications WHERE status = 'applying' AND updated_at < ?",
        (cutoff,)
    )
    for r in rows:
        r["ats"] = _normalize_ats(r.get("ats", ""))
    return rows


def reset_stuck_jobs() -> int:
    """Reset jobs stuck in 'applying' for >10 min back to 'queued'. Returns count reset."""
    from datetime import datetime, timedelta, timezone
    conn = _write_connect()
    if not conn:
        return 0
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        result = conn.execute(
            "UPDATE applications SET status = 'queued', updated_at = ? "
            "WHERE status = 'applying' AND updated_at < ?",
            (now, cutoff)
        )
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Reset {count} stuck job(s) back to queue")
        return count
    finally:
        conn.close()


# ─── Worker heartbeat (filesystem-visible, PTY-independent) ─────────────────
#
# The PTY watchdog uses these to detect worker drift without depending on
# PTY byte flow. worker.py writes worker.pid at main() start and touches
# scout.ts after each scout cycle. See packages/worker/worker.py for the
# writer side.


def _workspace_dir() -> Path:
    """Resolve workspace dir at call time so APPLYLOOP_WORKSPACE changes stick."""
    env = os.environ.get("APPLYLOOP_WORKSPACE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".autoapply" / "workspace"


def get_worker_heartbeat() -> tuple[int | None, int | None]:
    """Return (pid, last_seen_ms) from ~/.autoapply/workspace/worker.pid.

    Returns (None, None) if the file doesn't exist or can't be parsed.
    The PTY watchdog calls this every 5 min; a missing file with recent
    scout activity means the worker crashed and Claude should restart it.
    """
    path = _workspace_dir() / "worker.pid"
    if not path.exists():
        return (None, None)
    try:
        content = path.read_text().strip().splitlines()
        pid = int(content[0]) if content else None
        ts = int(content[1]) if len(content) > 1 else None
        return (pid, ts)
    except Exception as e:
        logger.debug(f"worker.pid parse failed: {e}")
        return (None, None)


def is_worker_alive() -> bool:
    """Check if the worker process recorded in worker.pid is still running.

    Uses os.kill(pid, 0) which succeeds if the process exists and we have
    permission to signal it. Returns False if the pid file is stale or the
    process has exited.
    """
    pid, _ = get_worker_heartbeat()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _read_scout_last_line() -> str | None:
    path = _workspace_dir() / "scout.ts"
    if not path.exists():
        return None
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        return lines[-1] if lines else None
    except Exception:
        return None


def get_scout_age_minutes() -> float | None:
    """Return minutes since the last scout cycle. Reads scout.ts.

    Tolerates two formats:
      - legacy: single int (ms since epoch) in the file
      - current: one JSON line per cycle `{"ts":<ms>,"enqueued":N,"raw":M}`

    In both cases we extract the LAST timestamp. Returns None if the file
    is missing or unparseable, meaning scout has never run on this install.
    """
    last = _read_scout_last_line()
    if last is None:
        path = _workspace_dir() / "scout.ts"
        if path.exists():
            try:
                return max(0.0, (time.time() - path.stat().st_mtime) / 60.0)
            except Exception:
                return None
        return None
    try:
        if last.startswith("{"):
            import json as _json
            ts_ms = int(_json.loads(last).get("ts", 0))
        else:
            ts_ms = int(last.strip())
        age_sec = max(0.0, time.time() - ts_ms / 1000.0)
        return age_sec / 60.0
    except Exception:
        try:
            return max(0.0, (time.time() - (_workspace_dir() / "scout.ts").stat().st_mtime) / 60.0)
        except Exception:
            return None


def get_recent_scout_cycles(n: int = 3) -> list[dict]:
    """Return the last `n` scout cycle entries as dicts with keys
    `ts`, `enqueued`, `raw`. Only reads JSON-line rows; legacy int-only
    rows are skipped (they pre-date per-cycle enqueue tracking).

    Used by the PTY nudge to detect "scout ran N cycles with zero enqueues"
    and escalate differently from "scout ran 2 min ago and is healthy."
    """
    path = _workspace_dir() / "scout.ts"
    if not path.exists():
        return []
    try:
        import json as _json
        lines = [ln for ln in path.read_text().splitlines() if ln.strip().startswith("{")]
        out: list[dict] = []
        for ln in lines[-n:]:
            try:
                out.append(_json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []


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
