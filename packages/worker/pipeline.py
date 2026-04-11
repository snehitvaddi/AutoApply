#!/usr/bin/env python3
"""
ApplyLoop Pipeline CLI — manages all job status transitions in the local SQLite DB.

The worker and orchestrator call this to manage the pipeline.
The desktop UI reads the same SQLite DB for the Kanban board, stats, and activity feed.

DB path: $APPLYLOOP_DB or ~/.autoapply/workspace/applications.db

Usage:
  pipeline.py scout                     Scout all sources -> queue qualifying jobs
  pipeline.py queue                     Show current queue
  pipeline.py next                      Get next queued job (JSON, for automation)
  pipeline.py start <id>                Mark job as 'applying'
  pipeline.py done <id> [--screenshot path]  Mark as 'submitted'
  pipeline.py fail <id> [reason]        Mark as 'failed'
  pipeline.py skip <id> [reason]        Mark as 'skipped'
  pipeline.py block <id>                Mark as 'blocked'
  pipeline.py status                    Full pipeline summary
  pipeline.py today                     Today's applications
  pipeline.py reset-stuck               Reset 'applying' jobs >10min back to 'queued'
  pipeline.py add <company> <role> <url> <ats> [location]  Manually add a job
"""

import sys
import os
import json
import sqlite3
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Configurable DB path: env var > default > legacy fallback
DB_PATH = Path(os.environ.get(
    "APPLYLOOP_DB",
    Path.home() / ".autoapply" / "workspace" / "applications.db"
))
if not DB_PATH.exists():
    _legacy = Path.home() / ".openclaw" / "agents" / "job-bot" / "workspace" / "applications.db"
    if _legacy.exists():
        DB_PATH = _legacy


# --- DATABASE ---------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    """Open (and auto-create) the local SQLite database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
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
    """)
    return conn


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# --- COMMANDS ---------------------------------------------------------------

def cmd_scout():
    """Run the scanner to fill the queue."""
    import subprocess
    # Try the scanner module (SaaS worker path)
    worker_dir = Path(__file__).resolve().parent
    scanner_run = worker_dir / "scanner" / "run.py"
    if scanner_run.exists():
        subprocess.run([sys.executable, "-m", "scanner.run"], cwd=str(worker_dir), timeout=600)
    else:
        print("Scanner not found. Run from the worker directory.")
        sys.exit(1)
    print()
    cmd_queue()


def cmd_queue():
    """Show current queue."""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, company, role, ats, location, scouted_at
        FROM applications WHERE status = 'queued'
        ORDER BY scouted_at ASC
    """).fetchall()
    conn.close()

    if not rows:
        print("Queue is empty.")
        return

    print(f"Queue: {len(rows)} jobs\n")
    print(f"{'ID':>6s}  {'Company':20s}  {'Role':45s}  {'ATS':12s}  {'Location':20s}")
    print("-" * 110)
    for r in rows:
        print(f"{r['id']:6d}  {(r['company'] or '?'):20s}  {(r['role'] or '?'):45s}  {(r['ats'] or '?'):12s}  {(r['location'] or '?'):20s}")


def cmd_next():
    """Get next queued job as JSON (for automation)."""
    conn = get_db()
    row = conn.execute("""
        SELECT id, company, role, url, ats, location, dedup_token, scouted_at
        FROM applications WHERE status = 'queued'
        ORDER BY scouted_at ASC LIMIT 1
    """).fetchone()
    conn.close()

    if not row:
        print(json.dumps({"empty": True}))
        return

    print(json.dumps(dict(row), indent=2))


def cmd_start(job_id: int):
    """Mark job as 'applying'."""
    conn = get_db()
    result = conn.execute(
        "UPDATE applications SET status = 'applying', updated_at = ? WHERE id = ? AND status IN ('queued', 'scouted')",
        (now_iso(), job_id)
    )
    conn.commit()
    if result.rowcount == 0:
        row = conn.execute("SELECT status FROM applications WHERE id = ?", (job_id,)).fetchone()
        if row:
            print(f"Job {job_id} is already '{row['status']}', not queued.")
        else:
            print(f"Job {job_id} not found.")
        conn.close()
        sys.exit(1)

    row = conn.execute("SELECT company, role FROM applications WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    print(f"Applying: {row['company']} -- {row['role']} (ID: {job_id})")


def cmd_done(job_id: int, screenshot: str = None):
    """Mark job as 'submitted'."""
    conn = get_db()
    now = now_iso()
    sets = "status = 'submitted', applied_at = ?, updated_at = ?"
    params = [now, now]
    if screenshot:
        sets += ", screenshot = ?"
        params.append(screenshot)
    params.append(job_id)
    result = conn.execute(f"UPDATE applications SET {sets} WHERE id = ?", params)
    conn.commit()
    if result.rowcount == 0:
        print(f"Job {job_id} not found.")
        conn.close()
        sys.exit(1)

    row = conn.execute("SELECT company, role FROM applications WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    print(f"Submitted: {row['company']} -- {row['role']} (ID: {job_id})")


def cmd_fail(job_id: int, reason: str = ""):
    """Mark job as 'failed'."""
    conn = get_db()
    conn.execute(
        "UPDATE applications SET status = 'failed', notes = ?, updated_at = ? WHERE id = ?",
        (reason, now_iso(), job_id)
    )
    conn.commit()
    row = conn.execute("SELECT company, role FROM applications WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if row:
        print(f"Failed: {row['company']} -- {row['role']} -- {reason}")
    else:
        print(f"Job {job_id} not found.")


def cmd_skip(job_id: int, reason: str = ""):
    """Mark job as 'skipped'."""
    conn = get_db()
    conn.execute(
        "UPDATE applications SET status = 'skipped', notes = ?, updated_at = ? WHERE id = ?",
        (reason, now_iso(), job_id)
    )
    conn.commit()
    row = conn.execute("SELECT company, role FROM applications WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if row:
        print(f"Skipped: {row['company']} -- {row['role']} -- {reason}")


def cmd_block(job_id: int):
    """Mark job as 'blocked'."""
    conn = get_db()
    conn.execute(
        "UPDATE applications SET status = 'blocked', updated_at = ? WHERE id = ?",
        (now_iso(), job_id)
    )
    conn.commit()
    row = conn.execute("SELECT company, role FROM applications WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if row:
        print(f"Blocked: {row['company']} -- {row['role']}")


def cmd_status():
    """Full pipeline summary."""
    conn = get_db()

    rows = conn.execute("SELECT status, COUNT(*) as cnt FROM applications GROUP BY status ORDER BY cnt DESC").fetchall()
    total = sum(r['cnt'] for r in rows)

    today = datetime.now().strftime('%Y-%m-%d')
    today_submitted = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status='submitted' AND applied_at LIKE ? || '%'",
        (today,)
    ).fetchone()[0]
    today_failed = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status='failed' AND updated_at LIKE ? || '%'",
        (today,)
    ).fetchone()[0]

    queued = conn.execute("SELECT COUNT(*) FROM applications WHERE status='queued'").fetchone()[0]
    applying = conn.execute("SELECT COUNT(*) FROM applications WHERE status='applying'").fetchone()[0]

    current = conn.execute(
        "SELECT id, company, role, url, ats FROM applications WHERE status='applying' ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()

    conn.close()

    print("=== PIPELINE STATUS ===\n")
    print(f"  Queue:     {queued}")
    print(f"  Applying:  {applying}")
    print(f"  Today:     {today_submitted} submitted, {today_failed} failed")
    print(f"  All time:  {total} total")

    if current:
        print(f"\n  Currently applying: {current['company']} -- {current['role']} (ID: {current['id']})")
        print(f"     URL: {current['url']}")

    print(f"\n  By status:")
    for r in rows:
        print(f"    {r['status']:15s}  {r['cnt']}")


def cmd_today():
    """Today's applications."""
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    rows = conn.execute("""
        SELECT id, company, role, ats, status, applied_at, updated_at
        FROM applications
        WHERE (applied_at LIKE ? || '%' OR updated_at LIKE ? || '%')
        AND status IN ('submitted', 'failed', 'blocked', 'skipped')
        ORDER BY COALESCE(applied_at, updated_at) DESC
    """, (today, today)).fetchall()
    conn.close()

    if not rows:
        print("No applications today.")
        return

    submitted = sum(1 for r in rows if r['status'] == 'submitted')
    failed = sum(1 for r in rows if r['status'] == 'failed')

    print(f"Today ({today}): {len(rows)} total -- {submitted} submitted, {failed} failed\n")
    print(f"{'ID':>6s}  {'Company':20s}  {'Role':45s}  {'Status':12s}  {'ATS':12s}  Time")
    print("-" * 115)
    for r in rows:
        ts = (r['applied_at'] or r['updated_at'] or '')
        time_str = ts[11:16] if len(ts) > 16 else ''
        print(f"{r['id']:6d}  {(r['company'] or '?'):20s}  {(r['role'] or '?'):45s}  {r['status']:12s}  {(r['ats'] or '?'):12s}  {time_str}")


def cmd_reset_stuck():
    """Reset jobs stuck in 'applying' for >10 minutes back to 'queued'."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    result = conn.execute(
        "UPDATE applications SET status = 'queued', updated_at = ? WHERE status = 'applying' AND updated_at < ?",
        (now_iso(), cutoff)
    )
    conn.commit()
    count = result.rowcount

    current = conn.execute(
        "SELECT id, company, role FROM applications WHERE status = 'applying'"
    ).fetchall()
    conn.close()

    if count > 0:
        print(f"Reset {count} stuck job(s) back to queue.")
    else:
        print("No stuck jobs found.")

    if current:
        print(f"\nCurrently applying ({len(current)}):")
        for r in current:
            print(f"  ID {r['id']}: {r['company']} -- {r['role']}")


def cmd_add(company: str, role: str, url: str, ats: str, location: str = ""):
    """Manually add a job to the queue."""
    conn = get_db()
    now = now_iso()
    dedup_token = f"{company.lower().replace(' ', '-')}|{url.split('/')[-1] or role.lower().replace(' ', '-')}"
    try:
        conn.execute("""
            INSERT INTO applications (company, role, url, ats, location, scouted_at, updated_at, status, dedup_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)
        """, (company, role, url, ats, location, now, now, dedup_token))
        conn.commit()
        job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        print(f"Queued: {company} -- {role} (ID: {job_id})")
    except sqlite3.IntegrityError:
        conn.close()
        print(f"Already in DB (duplicate): {company} -- {role}")


# --- MAIN -------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "scout":
        cmd_scout()
    elif cmd == "queue":
        cmd_queue()
    elif cmd == "next":
        cmd_next()
    elif cmd == "start":
        if len(sys.argv) < 3:
            print("Usage: pipeline.py start <id>")
            sys.exit(1)
        cmd_start(int(sys.argv[2]))
    elif cmd == "done":
        if len(sys.argv) < 3:
            print("Usage: pipeline.py done <id> [--screenshot path]")
            sys.exit(1)
        screenshot = None
        if "--screenshot" in sys.argv:
            idx = sys.argv.index("--screenshot")
            if idx + 1 < len(sys.argv):
                screenshot = sys.argv[idx + 1]
        cmd_done(int(sys.argv[2]), screenshot)
    elif cmd == "fail":
        if len(sys.argv) < 3:
            print("Usage: pipeline.py fail <id> [reason]")
            sys.exit(1)
        reason = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        cmd_fail(int(sys.argv[2]), reason)
    elif cmd == "skip":
        if len(sys.argv) < 3:
            print("Usage: pipeline.py skip <id> [reason]")
            sys.exit(1)
        reason = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        cmd_skip(int(sys.argv[2]), reason)
    elif cmd == "block":
        if len(sys.argv) < 3:
            print("Usage: pipeline.py block <id>")
            sys.exit(1)
        cmd_block(int(sys.argv[2]))
    elif cmd == "status":
        cmd_status()
    elif cmd == "today":
        cmd_today()
    elif cmd == "reset-stuck":
        cmd_reset_stuck()
    elif cmd == "add":
        if len(sys.argv) < 6:
            print("Usage: pipeline.py add <company> <role> <url> <ats> [location]")
            sys.exit(1)
        location = sys.argv[6] if len(sys.argv) > 6 else ""
        cmd_add(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], location)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
