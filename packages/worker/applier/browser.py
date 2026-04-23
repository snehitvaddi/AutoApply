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

import re
import time
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def browser(cmd: str, timeout: int = 15) -> str:
    """Run an openclaw browser command, return stdout."""
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
    """Two-step resume upload: arm the file chooser, then click the button."""
    browser(f"upload '{path}'", timeout=10)
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
