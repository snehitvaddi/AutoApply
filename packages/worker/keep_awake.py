"""Cross-platform "stay awake during apply" helper.

Apply runs can take 30+ seconds (form fills, file uploads, captcha waits).
If the user's machine sleeps mid-apply, Chrome dies, the form submit fails,
and the row gets stuck in 'applying' state forever.

Mac/Linux: `jiggler.sh` runs externally as a subprocess and uses macOS
`caffeinate`. This module is a no-op on those platforms so we don't have
two systems fighting over wake state.

Windows: there's no caffeinate equivalent and no jiggler.sh. Use the
Win32 `SetThreadExecutionState` API to tell Windows "don't sleep while
this process is alive." Idempotent — calling start() twice is safe.

Usage:
    from . import keep_awake
    keep_awake.start()   # no-op on Mac/Linux, ES_CONTINUOUS on Windows
    try:
        ...apply logic...
    finally:
        keep_awake.stop()
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

_started = False


def start() -> None:
    """Block sleep while the worker is running. No-op on non-Windows."""
    global _started
    if sys.platform != "win32" or _started:
        return
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        )
        _started = True
        logger.debug("Windows stay-awake enabled (SetThreadExecutionState)")
    except Exception as e:
        logger.debug(f"Windows stay-awake start failed (non-fatal): {e}")


def stop() -> None:
    """Release the wake-lock. Safe to call without start()."""
    global _started
    if sys.platform != "win32" or not _started:
        return
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        _started = False
    except Exception as e:
        logger.debug(f"Windows stay-awake stop failed (non-fatal): {e}")
