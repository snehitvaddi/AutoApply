"""OpenClaw browser CLI wrappers.

Extracted from `applier/greenhouse.py` so every caller (appliers, scouts,
the Agent-SDK brain) can depend on the browser layer without pulling in
Greenhouse-specific logic. The brain's `browser.*` MCP tools and every
ATS applier import from here.

Each helper shells out to `openclaw browser <verb>` and returns stdout
(string). Timeouts are intentional — a stuck OpenClaw call must not
starve the apply loop. `browser()` swallows its own errors and returns
"" so callers can keep making progress on a partial snapshot.
"""
from __future__ import annotations

import os
import re
import shutil
import time
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class BrowserError(RuntimeError):
    """Raised when an openclaw browser command fails in a way the caller
    must not silently ignore (e.g. resume upload to an unreachable path).

    The wrapper `browser()` keeps its lenient contract — returns "" on
    timeout/error — for callers that only care about output. Strict
    helpers (`upload_file`, anything that mutates remote state) use
    `BrowserError` so the failure is surfaced to the agent instead of
    being papered over."""


# OpenClaw's filesystem sandbox for uploads. Paths outside this dir
# are silently rejected by the CLI (it returns success, never attaches
# the file). We auto-copy resumes into the sandbox before invoking the
# upload verb so the agent doesn't have to think about it.
_OPENCLAW_UPLOAD_SANDBOX = os.environ.get(
    "OPENCLAW_UPLOAD_SANDBOX", "/tmp/openclaw/uploads"
)


def browser(cmd: str, timeout: int = 15) -> str:
    """Run an openclaw browser command, return stdout.

    Lenient: timeout / non-zero / exception all collapse to "". This is
    intentional for read-only callers (snapshot, screenshot regex parse,
    tab listing) where empty output is a recoverable signal. For strict
    callers, use the helpers that raise BrowserError on failure.
    """
    full_cmd = f"openclaw browser {cmd}"
    try:
        r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"TIMEOUT: {cmd}")
        return ""
    except Exception as e:
        logger.error(f"ERROR: {cmd} -> {e}")
        return ""


def _browser_strict(cmd: str, timeout: int = 15) -> str:
    """Run openclaw and raise BrowserError on timeout / non-zero exit.

    Use this for verbs that mutate remote state (upload, click that
    triggers navigation). Distinguishing "empty output" from "command
    failed" is the whole point — the lenient `browser()` collapses both."""
    full_cmd = f"openclaw browser {cmd}"
    try:
        r = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise BrowserError(f"openclaw timed out after {timeout}s: {cmd}") from e
    if r.returncode != 0:
        raise BrowserError(
            f"openclaw {cmd!r} failed (rc={r.returncode}): "
            f"stdout={r.stdout.strip()[:300]!r} stderr={r.stderr.strip()[:300]!r}"
        )
    return r.stdout.strip()


def _ensure_in_upload_sandbox(path: str) -> str:
    """Return a path under the OpenClaw upload sandbox.

    If `path` already lives there, return it unchanged. Otherwise copy
    the file into the sandbox dir and return the copy's path. Raises
    BrowserError if the source is missing or the copy fails.

    Why: OpenClaw enforces a sandbox on the upload verb. A path outside
    the sandbox is silently rejected (the CLI returns ok but never
    attaches the file), which used to burn ~20 minutes of agent time
    per resume that lived under ~/.autoapply/workspace/resumes/.
    """
    if not path:
        raise BrowserError("upload path is empty")
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        raise BrowserError(f"upload source not found: {abs_path}")
    sandbox = os.path.abspath(_OPENCLAW_UPLOAD_SANDBOX)
    try:
        os.makedirs(sandbox, exist_ok=True)
    except OSError as e:
        raise BrowserError(f"could not create upload sandbox {sandbox}: {e}") from e
    if abs_path.startswith(sandbox + os.sep):
        return abs_path
    dest = os.path.join(sandbox, os.path.basename(abs_path))
    try:
        shutil.copyfile(abs_path, dest)
    except OSError as e:
        raise BrowserError(f"could not copy {abs_path} → {dest}: {e}") from e
    return dest


def snapshot() -> str:
    return browser("snapshot --efficient --interactive", timeout=10)


def fill_fields(fields_json: str) -> str:
    escaped = fields_json.replace("'", "'\\''")
    return browser(f"fill --fields '{escaped}'", timeout=10)


def click_ref(ref: str) -> str:
    return browser(f"click {ref}", timeout=8)


def select_option(ref: str, value: str) -> str:
    escaped_value = value.replace('"', '\\"')
    return browser(f'select {ref} "{escaped_value}"', timeout=8)


def upload_file(path: str, ref: str) -> str:
    """Two-step resume upload: arm the file chooser, then click the button.

    Auto-copies the source file into the OpenClaw upload sandbox before
    arming so paths outside `/tmp/openclaw/uploads/` work transparently.
    Raises BrowserError if the source is missing, the sandbox copy fails,
    or openclaw signals a non-zero exit. The MCP tool propagates the
    error back to the agent instead of returning a misleading "ok"."""
    sandbox_path = _ensure_in_upload_sandbox(path)
    _browser_strict(f"upload '{sandbox_path}'", timeout=10)
    time.sleep(0.3)
    return click_ref(ref)


def take_screenshot() -> Optional[str]:
    out = browser("screenshot --full-page --type png", timeout=10)
    m = re.search(r'(\/\S+\.png)', out)
    return m.group(1) if m else None


def wait_load(timeout_ms: int = 5000) -> None:
    browser(f"wait --load networkidle --timeout-ms {timeout_ms}", timeout=timeout_ms // 1000 + 3)


def navigate_url(url: str) -> str:
    return browser(f'navigate "{url}"', timeout=10)


def press_key(key: str) -> str:
    return browser(f"press {key}", timeout=3)


def evaluate_js(js_code: str) -> str:
    escaped = js_code.replace("'", "'\\''")
    return browser(f"evaluate --fn '{escaped}'", timeout=10)


def type_into(ref: str, text: str) -> str:
    escaped = text.replace('"', '\\"')
    return browser(f'type {ref} "{escaped}"', timeout=5)


def list_tabs() -> list[dict]:
    """Return the list of open browser tabs.

    Each tab is a dict with at least `targetId`, `url`, `title`. We ask
    OpenClaw for JSON so the shape is stable. Returns [] on any failure
    — callers use this as a pre-submit sanity check, not a load-bearing
    query, so swallowing errors is safe.
    """
    import json as _json
    # OpenClaw logs a config-version banner to stdout on every call. Ask
    # for JSON and grep out the first `{`...`}` block so the banner is
    # tolerated.
    raw = browser("tabs --json", timeout=5)
    if not raw:
        return []
    start = raw.find("{")
    if start < 0:
        return []
    try:
        data = _json.loads(raw[start:])
    except Exception as e:
        logger.debug(f"tabs --json parse failed: {e}; raw={raw[:200]!r}")
        return []
    tabs = data.get("tabs") or []
    return tabs if isinstance(tabs, list) else []


def close_tab(target_id: str) -> str:
    """Close one tab by OpenClaw targetId (or unique prefix)."""
    return browser(f"close {target_id}", timeout=5)


def focus_tab(target_id: str) -> str:
    """Bring one tab to the foreground by targetId."""
    return browser(f"focus {target_id}", timeout=5)


def dismiss_stray_tabs(keep_url_substring: str | None = None) -> int:
    """Close every tab that is NOT the apply tab.

    The apply flow occasionally triggers privacy-policy / terms-of-use
    links that open a new tab and steal focus. OpenClaw's next snapshot
    then targets the popup, the agent fills the wrong page, and the
    original form stalls. Call this between apply steps to keep the
    session single-tabbed.

    Args:
        keep_url_substring: if given, keep tabs whose URL contains this
            substring (use the apply ATS hostname). If None, keep only
            the first tab in the list.

    Returns:
        Number of tabs closed. 0 means nothing to do.
    """
    tabs = list_tabs()
    if len(tabs) <= 1:
        return 0

    closed = 0
    if keep_url_substring:
        keeper_ids: set[str] = set()
        for t in tabs:
            url = (t.get("url") or "").lower()
            if keep_url_substring.lower() in url and not keeper_ids:
                keeper_ids.add(str(t.get("targetId") or ""))
        # No tab matched the filter? Fall back to keeping the first.
        if not keeper_ids:
            keeper_ids = {str(tabs[0].get("targetId") or "")}
    else:
        keeper_ids = {str(tabs[0].get("targetId") or "")}

    for t in tabs:
        tid = str(t.get("targetId") or "")
        if not tid or tid in keeper_ids:
            continue
        close_tab(tid)
        closed += 1

    # Make sure the keeper is foregrounded — popups often steal focus
    # and OpenClaw's next snapshot targets the focused tab.
    if keeper_ids:
        focus_tab(next(iter(keeper_ids)))

    return closed


def parse_snapshot(raw: str) -> list[dict]:
    """Parse snapshot output into a list of {ref, type, label} dicts."""
    fields: list[dict] = []
    for line in raw.split("\n"):
        line = line.strip()
        m = re.match(
            r'-\s+(textbox|combo|button|link|checkbox|radio|select|generic)\s+"([^"]*)".*\[ref=(\w+)\]',
            line,
        )
        if m:
            fields.append({"type": m.group(1), "label": m.group(2), "ref": m.group(3)})
            continue
        m2 = re.match(
            r'-\s+(textbox|combo|button|link|checkbox|radio|select|generic)\s+\[ref=(\w+)\]',
            line,
        )
        if m2:
            fields.append({"type": m2.group(1), "label": "", "ref": m2.group(2)})
    return fields
