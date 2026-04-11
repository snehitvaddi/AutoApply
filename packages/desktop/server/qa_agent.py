"""
Q&A Agent — fire-and-forget subprocess using `claude --print`.

Replaces the PTY-based message router for chat/Telegram questions so that:
  1. Q&A responses aren't contaminated with apply-loop terminal output
  2. The main Claude Code session keeps applying uninterrupted
  3. Each question is a stateless one-shot subprocess — no PTY, no state drift

Flow:
  question  →  build_context() snapshot of SQLite
            →  claude --print --append-system-prompt <context>  (stdin-fed)
            →  clean stdout → return
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime

from . import local_data

logger = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "/Users/vsneh/.local/bin/claude"
DEFAULT_MODEL = "sonnet"  # fast + smart enough for DB Q&A
DEFAULT_TIMEOUT = 60.0    # seconds

SYSTEM_PROMPT_TEMPLATE = """You are the ApplyLoop Q&A assistant embedded in a desktop job-application bot.

Answer the user's question about their job application pipeline using ONLY the
context JSON below. Keep answers short (1-3 sentences unless a list is asked for),
friendly, and Markdown-formatted. Do NOT make up data. If something is missing
from the context, say "I don't have that info yet" instead of guessing.

If the user asks about "today" or "now", use the timestamps in the context to
compute relative answers. Assume the current time is {now_iso}.

CONTEXT:
```json
{context_json}
```
"""


def _build_context() -> dict:
    """Snapshot everything the Q&A agent might need, from SQLite only."""
    try:
        return {
            "stats": local_data.get_stats(),
            "currently_applying": local_data.get_currently_applying(),
            "stuck_jobs_count": len(local_data.get_stuck_jobs()),
            "recent_activity": local_data.get_recent_activity(limit=15),
            "queue_count": local_data.get_queue_count(),
        }
    except Exception as e:
        logger.warning(f"QA context build failed: {e}")
        return {"error": f"failed to build context: {e}"}


async def answer(question: str, model: str = DEFAULT_MODEL, timeout: float = DEFAULT_TIMEOUT) -> str:
    """
    Answer a user question via a one-shot `claude --print` subprocess.

    Runs the subprocess in a worker thread so the FastAPI event loop doesn't block.
    Returns the cleaned stdout, or an error string if the subprocess fails.
    """
    question = (question or "").strip()
    if not question:
        return "⚠️ Empty question."

    context = _build_context()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        now_iso=datetime.utcnow().isoformat() + "Z",
        context_json=json.dumps(context, indent=2, default=str),
    )

    logger.info(f"QA ask: {question[:100]}")

    def _run() -> str:
        import subprocess
        try:
            proc = subprocess.run(
                [
                    CLAUDE_BIN,
                    "--print",
                    "--model", model,
                    "--allowedTools", "",
                    "--append-system-prompt", system_prompt,
                ],
                input=question,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "⚠️ Q&A timed out after 60s. Try a simpler question."
        except FileNotFoundError:
            return f"⚠️ `claude` CLI not found at {CLAUDE_BIN}."
        except Exception as e:
            return f"⚠️ Q&A error: {e}"

        if proc.returncode != 0:
            err = (proc.stderr or "").strip()[:500]
            return f"⚠️ Q&A failed (exit {proc.returncode}): {err}"

        out = (proc.stdout or "").strip()
        return out or "⚠️ Empty response from Q&A agent."

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        logger.warning(f"QA agent asyncio.to_thread failed: {e}")
        return f"⚠️ Q&A dispatch error: {e}"
