"""ApplyLoop Brain — entry point.

Starts a persistent `ClaudeSDKClient` with the applyloop MCP tool
server + the scout-agent / apply-agent subagents. Drives a loop of
"check pipeline → scout if needed → apply one job → sleep" by
re-prompting the client each tick.

Authentication: the SDK launches the `claude` CLI as a subprocess, so
it reuses whatever login the user already has on their machine
(Claude.ai subscription via `claude login`). No ANTHROPIC_API_KEY is
required as long as the `claude` CLI is installed and signed in.

Flags:
  --dry-run   List the tools that would be registered and exit. No
              network calls, no CLI spawn.
  --once      Run exactly one scout+apply cycle and exit. For smoke
              testing on a seeded queue row.
  (default)   Run forever; sleep between cycles.

Env vars:
  APPLYLOOP_USER_ID         — required. Which tenant's queue we serve.
  APPLYLOOP_BRAIN_DISABLED  — if set, refuse to start (kill switch).
  APPLYLOOP_BRAIN_MODEL     — override the default Sonnet 4.6 model.
  APPLYLOOP_BRAIN_LOG       — override ~/.applyloop/brain.log path.
"""
from __future__ import annotations

import os
import sys
import asyncio
import logging
import argparse
from typing import Any

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

from brain import session_log
from brain.prompts import SYSTEM_PROMPT
from brain.tools import ALL_TOOLS, build_server, allowed_tool_names
from brain.subagents import AGENTS

logging.basicConfig(
    level=os.environ.get("APPLYLOOP_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("brain")


SEED_PROMPT_FULL = """Start your loop.

1. Call notify_heartbeat with last_action="brain_online" and a one-line details string.
2. Call tenant_load so you know whose profile you're working with.
3. Call queue_get_pipeline to see today's state.
4. If pending < 20, delegate to the scout-agent subagent to top up the queue. Then check pipeline again.
5. Delegate to the apply-agent subagent to work exactly ONE job from the pending queue.
6. After the apply-agent returns, call notify_heartbeat with the outcome.
7. Stop and wait for my next prompt. I will say "continue" when I want the next cycle."""

SEED_PROMPT_ONCE = """One cycle, then stop.

1. Call notify_heartbeat last_action="brain_online".
2. Call tenant_load.
3. Call queue_get_pipeline.
4. Delegate to the apply-agent to work ONE job.
5. Report back with the outcome."""


async def _run_brain(once: bool) -> None:
    if os.environ.get("APPLYLOOP_BRAIN_DISABLED"):
        logger.error("APPLYLOOP_BRAIN_DISABLED is set — refusing to start. Use applyloop-worker --mode=legacy instead.")
        sys.exit(2)

    user_id = os.environ.get("APPLYLOOP_USER_ID")
    if not user_id:
        logger.error("APPLYLOOP_USER_ID is required.")
        sys.exit(2)

    model = os.environ.get("APPLYLOOP_BRAIN_MODEL", "sonnet")

    options = ClaudeAgentOptions(
        mcp_servers={"applyloop": build_server()},
        allowed_tools=allowed_tool_names(),
        system_prompt=SYSTEM_PROMPT,
        agents=AGENTS,
        model=model,
        # Conservative budget so a runaway loop can't burn $$ unattended.
        max_budget_usd=float(os.environ.get("APPLYLOOP_BRAIN_MAX_USD", "25")),
    )

    session_log.log_event("cycle_start", once=once, model=model, user_id=user_id)

    async with ClaudeSDKClient(options=options) as client:
        seed = SEED_PROMPT_ONCE if once else SEED_PROMPT_FULL
        await client.query(seed)
        async for msg in client.receive_response():
            # The SDK streams AssistantMessage / ToolUseBlock etc. We
            # just tee everything interesting to the brain.log. The
            # SDK itself handles tool dispatch — this loop is purely
            # observational.
            cls = type(msg).__name__
            try:
                text = getattr(msg, "content", None) or getattr(msg, "text", None) or str(msg)
            except Exception:
                text = cls
            session_log.log_event("sdk_message", cls=cls, text=str(text)[:1500])

        if once:
            session_log.log_event("cycle_end", once=True)
            return

        # Non-once mode: re-prompt forever. Each tick runs one cycle.
        while True:
            await asyncio.sleep(int(os.environ.get("APPLYLOOP_BRAIN_CYCLE_S", "300")))
            await client.query("continue")
            async for msg in client.receive_response():
                cls = type(msg).__name__
                try:
                    text = getattr(msg, "content", None) or getattr(msg, "text", None) or str(msg)
                except Exception:
                    text = cls
                session_log.log_event("sdk_message", cls=cls, text=str(text)[:1500])


def _dry_run() -> None:
    print("ApplyLoop Brain — dry run")
    print(f"  tools registered: {len(ALL_TOOLS)}")
    for t in ALL_TOOLS:
        print(f"    - {t.name}")
    print(f"  subagents: {list(AGENTS.keys())}")
    print(f"  system_prompt length: {len(SYSTEM_PROMPT)} chars")
    print(f"  log path: {session_log.LOG_PATH}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="applyloop-brain")
    ap.add_argument("--dry-run", action="store_true", help="List tools and exit without starting the SDK.")
    ap.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    args = ap.parse_args()

    if args.dry_run:
        _dry_run()
        return

    try:
        asyncio.run(_run_brain(once=args.once))
    except KeyboardInterrupt:
        logger.info("brain shutdown requested")
    except Exception as e:
        session_log.log_error("main", str(e))
        raise


if __name__ == "__main__":
    main()
