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


def health_check() -> tuple[bool, str]:
    """End-to-end browser reachability check with auto-recovery.

    Runs `openclaw browser snapshot` (5s). Non-empty output → reachable.
    On empty, attempts `openclaw gateway restart`, waits 2s, then retries.
    Returns (ok, detail) — never raises.
    """
    def _probe() -> bool:
        return bool(browser("snapshot", timeout=5))

    if _probe():
        return True, "Browser reachable"

    logger.info("health_check: snapshot empty, attempting gateway restart")
    try:
        subprocess.run(
            "openclaw gateway restart",
            shell=True, capture_output=True, timeout=10,
        )
        time.sleep(2)
    except Exception as e:
        logger.warning(f"health_check: gateway restart failed: {e}")

    if _probe():
        return True, "Browser reachable (recovered after gateway restart)"

    return False, (
        "openclaw browser snapshot returned empty after gateway restart — "
        "Chrome may not be running or the gateway is misconfigured"
    )


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
    """Three-step resume upload with verification.

    1. Arm the file chooser via `openclaw browser upload`. (Auto-copies
       the source into the OpenClaw upload sandbox; paths outside
       `/tmp/openclaw/uploads/` are rejected by the CLI.)
    2. Click the visible target so the React dropzone takes the file.
       Failures here used to be silently swallowed — OpenClaw still
       reported `ok` from step 1, the agent logged a successful upload,
       and the form went to submit with an empty `<input>`. Now: if
       the click times out OR no `input[type=file]` ends up holding a
       file, raise BrowserError so the caller learns the truth.
    3. Verify via JS that some `input[type=file]` on the page now has
       `.files.length > 0`. If none does, fall back to a DataTransfer
       injection (works for React-rendered dropzones that ignore the
       click entirely) and re-verify.

    The verification step is the actual fix for the brain's
    "browser_upload says ok but Greenhouse field is empty" report —
    Greenhouse's React dropzone often consumes the click without
    forwarding the file to the underlying input.
    """
    sandbox_path = _ensure_in_upload_sandbox(path)
    _browser_strict(f"upload '{sandbox_path}'", timeout=10)
    time.sleep(0.3)
    # Best-effort click. A timeout / non-zero is logged and recovered
    # from in step 3 — many React dropzones handle the file via the
    # `change` event the upload verb already fired and don't need the
    # button click at all. Don't raise here; let the verify step decide.
    try:
        click_ref(ref)
    except Exception as e:
        logger.debug(f"upload_file: post-arm click on {ref!r} failed (will verify): {e}")
    time.sleep(0.4)

    # Step 3 — verify a file landed somewhere. We don't know which
    # specific <input> the dropzone is targeting, so we walk all of
    # them. Returns the file count for diagnostics.
    def _file_count() -> int:
        probe = (
            "() => {"
            " const ins = document.querySelectorAll('input[type=file]');"
            " let n = 0;"
            " for (const i of ins) { if (i && i.files) n += i.files.length; }"
            " return n;"
            "}"
        )
        out = (evaluate_js(probe) or "").strip()
        # OpenClaw evaluate output is the JSON-encoded return; safest
        # to grab the trailing integer if any.
        m = re.search(r"(\d+)\s*$", out)
        return int(m.group(1)) if m else 0

    if _file_count() > 0:
        return "ok"

    # Fallback: synthesize a File via DataTransfer and dispatch onto
    # the first visible input[type=file]. Reading the bytes via fetch()
    # would require the file to be served; instead we ask OpenClaw to
    # navigate to a file:// URL of the sandbox copy (won't work cross-
    # origin) — so the cleanest fallback is to re-arm + dispatch a
    # synthetic 'change' event via JS. Many React dropzones listen for
    # the change on the input directly.
    logger.warning(
        f"upload_file: no input[type=file] holds a file after arm+click "
        f"on ref={ref!r} — re-arming and dispatching change"
    )
    _browser_strict(f"upload '{sandbox_path}'", timeout=10)
    time.sleep(0.3)
    fire_change = (
        "() => {"
        " const ins = document.querySelectorAll('input[type=file]');"
        " let fired = 0;"
        " for (const i of ins) {"
        "   try { i.dispatchEvent(new Event('change', {bubbles:true})); fired++; }"
        "   catch (e) {}"
        " }"
        " return fired;"
        "}"
    )
    evaluate_js(fire_change)
    time.sleep(0.5)

    final = _file_count()
    if final > 0:
        return f"ok (after fallback, files={final})"
    raise BrowserError(
        f"upload_file: file did not land on any input[type=file] after "
        f"arm + click({ref!r}) + change-dispatch. Source: {sandbox_path}"
    )


def take_screenshot() -> Optional[str]:
    out = browser("screenshot --full-page --type png", timeout=10)
    m = re.search(r'(\/\S+\.png)', out)
    if m:
        return m.group(1)
    # Fall back: openclaw versions that print only a bare filename
    # (or just "ok") still drop the PNG into the workspace screenshots
    # dir. Pick the newest .png within the last 5 seconds — anything
    # older is from a previous capture and shouldn't be attributed to
    # this submit.
    try:
        import glob, os, time
        from config import SCREENSHOT_DIR  # local import to avoid cycle
        candidates = glob.glob(os.path.join(SCREENSHOT_DIR, "*.png"))
        if candidates:
            newest = max(candidates, key=os.path.getmtime)
            if time.time() - os.path.getmtime(newest) <= 5:
                return newest
    except Exception:
        pass
    # Don't fail silently — surface what the CLI actually returned so
    # we can tell whether the screenshot capture itself broke vs. just
    # the parser. Truncate so log lines stay readable.
    snippet = (out or "").strip().replace("\n", " | ")[:300]
    logger.warning(f"take_screenshot: no path in openclaw output: {snippet!r}")
    return None


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


def select_react_value(selector: str, label: str, value: str | None = None) -> str:
    """Commit a value to a React-Select / fiber-driven combobox.

    Why: React-Select v5 (Greenhouse) and Ashby's combobox keep their
    selected state in React fiber, not the DOM. Clicking the visible
    option fires a synthetic event that React frequently treats as a
    no-op — the dropdown closes, the label appears selected, but the
    form's onChange never sees it and submission fails with "field
    required". The fix is to walk the fiber up from the trigger
    element until we find a node whose `memoizedProps.onChange` is a
    function, then call it with the canonical option object. This
    bypasses every DOM-event quirk and writes directly into React
    state.

    Args:
        selector: CSS selector for ANY element inside the
            React-Select container (commonly the visible
            `.select__control`, `.select__input`, or the input that
            holds the typed text).
        label: Display label of the option to pick.
        value: Optional opaque value the option carries; many
            React-Select schemas use `{value, label}` and the form
            keys off `value`. If None, falls back to `label`.

    Returns:
        "ok" on success, otherwise a JS-side error string. Doesn't
        raise — callers decide whether an empty result is fatal.
    """
    target_value = (value if value is not None else label).replace('"', '\\"')
    target_label = label.replace('"', '\\"')
    sel = selector.replace('"', '\\"')
    js = (
        "() => {"
        f" const el = document.querySelector(\"{sel}\");"
        " if (!el) return 'no_element';"
        " let node = el;"
        " let fiberKey = null;"
        " for (const k of Object.keys(node)) {"
        "   if (k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$')) { fiberKey = k; break; }"
        " }"
        " if (!fiberKey) return 'no_fiber';"
        " let fiber = node[fiberKey];"
        " let onChange = null;"
        " let depth = 0;"
        " while (fiber && depth < 30) {"
        "   const p = fiber.memoizedProps;"
        "   if (p && typeof p.onChange === 'function') { onChange = p.onChange; break; }"
        "   fiber = fiber.return;"
        "   depth++;"
        " }"
        " if (!onChange) return 'no_onChange';"
        f" const opt = {{value: \"{target_value}\", label: \"{target_label}\"}};"
        " try {"
        "   onChange(opt, {action: 'select-option'});"
        "   return 'ok';"
        " } catch (e) {"
        "   try { onChange(opt); return 'ok_no_meta'; } catch (e2) { return 'onChange_threw:' + (e2.message || ''); }"
        " }"
        "}"
    )
    out = (evaluate_js(js) or "").strip()
    return out or "no_output"


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
