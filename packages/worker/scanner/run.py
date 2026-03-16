"""Scanner entry point — discovers jobs from public ATS APIs.

Usage:
    python -m scanner.run                    # scan all platforms
    python -m scanner.run --ats greenhouse   # scan specific platform
    python -m scanner.run --dry-run          # scan without upserting to DB

Cron (every 6 hours):
    0 */6 * * * cd /path/to/worker && python -m scanner.run
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from db import get_supabase_client
from scanner.greenhouse import scan_greenhouse_boards
from scanner.ashby import scan_ashby_boards
from scanner.lever import scan_lever_boards

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scanner")

# ── Board lists ──────────────────────────────────────────────────────────────
# These are the public ATS board tokens/slugs we scan.
# Greenhouse: 271+ boards, Ashby: 102+ boards, Lever: ~7 active companies.

GREENHOUSE_BOARDS = [
    "stripe", "airbnb", "coinbase", "anthropic", "openai", "waymo",
    "lyft", "squarespace", "roblox", "veracyte", "axon", "launchdarkly",
    "opendoor", "figma", "notion", "plaid", "databricks", "scale",
    "anyscale", "cohere", "huggingface", "midjourney", "stability",
    "runway", "jasper", "inflection", "adept", "replit", "deepmind",
    "coreweave", "collibra", "tenstorrent", "scopely", "sofi",
    "chainguard", "tecton", "modal", "weaviate", "pinecone", "qdrant",
    "chromadb", "langchain", "llamaindex", "together", "cerebras",
    "sambanova", "groq", "xai", "mistral", "perplexityai",
    # Add more tokens as discovered
]

ASHBY_BOARDS = [
    "notion", "ramp", "characterai", "harvey", "posthoginc",
    "cursor", "vercel", "supabase", "resend", "linear",
    "livekit", "dbt-labs", "materialize", "planetscale",
    "neon", "turso", "upstash", "convex", "inngest",
    "temporal", "prefect", "dagster", "modal", "replicate",
    "weights-and-biases", "arize", "helicone", "braintrust",
    # Add more slugs as discovered
]

LEVER_COMPANIES = [
    "voleon", "nominal", "levelai", "fieldai", "nimblerx", "weride",
]


def upsert_discovered_jobs(jobs: list[dict], dry_run: bool = False) -> int:
    """Upsert normalized jobs into the discovered_jobs table.

    Returns count of new/updated rows.
    """
    if dry_run or not jobs:
        return 0

    client = get_supabase_client()
    upserted = 0

    # Batch upsert in chunks of 100
    for i in range(0, len(jobs), 100):
        batch = jobs[i : i + 100]
        rows = [
            {
                "external_id": j["external_id"],
                "ats": j["ats"],
                "title": j["title"],
                "company": j["company"],
                "location": j["location"],
                "apply_url": j["apply_url"],
                "posted_at": j["posted_at"] or None,
                "metadata": j.get("metadata", {}),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            }
            for j in batch
        ]

        try:
            result = client.table("discovered_jobs").upsert(
                rows,
                on_conflict="external_id,ats",
            ).execute()
            upserted += len(result.data) if result.data else 0
        except Exception as e:
            logger.error(f"Upsert batch failed: {e}")

    return upserted


def run_scan(ats_filter: str | None = None, dry_run: bool = False) -> dict:
    """Run scanner for specified (or all) ATS platforms.

    Returns summary dict with counts per platform.
    """
    summary = {}
    all_jobs = []

    platforms = {
        "greenhouse": (scan_greenhouse_boards, GREENHOUSE_BOARDS),
        "ashby": (scan_ashby_boards, ASHBY_BOARDS),
        "lever": (scan_lever_boards, LEVER_COMPANIES),
    }

    for name, (scan_fn, board_list) in platforms.items():
        if ats_filter and name != ats_filter:
            continue

        logger.info(f"Scanning {name} ({len(board_list)} boards)...")
        start = time.time()

        try:
            jobs = scan_fn(board_list)
            elapsed = time.time() - start
            summary[name] = {"jobs": len(jobs), "boards": len(board_list), "seconds": round(elapsed, 1)}
            all_jobs.extend(jobs)
            logger.info(f"{name}: {len(jobs)} jobs in {elapsed:.1f}s")
        except Exception as e:
            logger.error(f"{name} scan failed: {e}")
            summary[name] = {"jobs": 0, "boards": len(board_list), "error": str(e)}

    # Upsert to database
    if not dry_run:
        upserted = upsert_discovered_jobs(all_jobs)
        logger.info(f"Upserted {upserted} jobs to discovered_jobs")
        summary["_upserted"] = upserted
    else:
        logger.info(f"Dry run — {len(all_jobs)} jobs found, nothing written to DB")
        summary["_dry_run"] = True

    summary["_total_jobs"] = len(all_jobs)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Scan public ATS APIs for jobs")
    parser.add_argument("--ats", choices=["greenhouse", "ashby", "lever"], help="Scan specific platform only")
    parser.add_argument("--dry-run", action="store_true", help="Scan without writing to database")
    args = parser.parse_args()

    logger.info(f"Scanner starting at {datetime.now(timezone.utc).isoformat()}")
    summary = run_scan(ats_filter=args.ats, dry_run=args.dry_run)

    logger.info("=" * 60)
    logger.info("SCAN COMPLETE")
    for k, v in summary.items():
        if not k.startswith("_"):
            logger.info(f"  {k}: {v.get('jobs', 0)} jobs from {v.get('boards', 0)} boards ({v.get('seconds', '?')}s)")
    logger.info(f"  Total: {summary.get('_total_jobs', 0)} jobs")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
