"""Thought-stream + tool-call tee for the brain.

The SDK streams `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`
(etc.) events from `client.receive_response()`. We forward the
interesting ones as one-line JSON to `~/.applyloop/brain.log` so the
dashboard / admin can tail what the brain is doing without re-piping
the SDK's structured objects. Keep this file small and dependency-free
— it runs alongside the brain loop and must never raise.
"""
from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Any

LOG_PATH = Path(os.environ.get(
    "APPLYLOOP_BRAIN_LOG",
    os.path.expanduser("~/.applyloop/brain.log"),
))


def _ensure_parent() -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _write(entry: dict[str, Any]) -> None:
    _ensure_parent()
    entry["ts"] = time.time()
    try:
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        # Dashboard logging is non-critical. Swallow everything so the
        # brain loop never dies because the disk is full.
        pass


def log_event(kind: str, **fields: Any) -> None:
    """Append one structured event. `kind` is a short tag like
    'tool_call', 'assistant_text', 'cycle_start', 'error'."""
    entry = {"kind": kind}
    entry.update(fields)
    _write(entry)


def log_tool_call(name: str, args: dict[str, Any]) -> None:
    log_event("tool_call", name=name, args=args)


def log_tool_result(name: str, result: dict[str, Any] | str) -> None:
    log_event("tool_result", name=name, result=result)


def log_assistant_text(text: str) -> None:
    # Truncate so one rambling turn doesn't blow up the log line.
    log_event("assistant_text", text=text[:2000])


def log_error(where: str, err: str) -> None:
    log_event("error", where=where, err=err[:1000])
