"""Himalaya CLI wrapper — unified Gmail reader for OTPs and verification links.

Himalaya is a Rust IMAP CLI (https://github.com/pimalaya/himalaya).
It authenticates to Gmail using an app password — no OAuth, no Supabase tokens.

Credentials come from the apply profile (self.profile_email / self.profile_app_password
in applier/base.py), or from GMAIL_EMAIL / GMAIL_APP_PASSWORD env vars for
single-profile installs. ensure_configured() writes the TOML config automatically.

Gmail prerequisites:
  1. IMAP enabled (Gmail Settings → Forwarding and POP/IMAP → Enable IMAP)
  2. 2FA on (myaccount.google.com/security)
  3. App password created (myaccount.google.com/apppasswords) — 16-char code
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import time

logger = logging.getLogger(__name__)


# ── Config path ────────────────────────────────────────────────────────────

def _config_path() -> str:
    """Return OS-appropriate himalaya config directory."""
    if platform.system() == "Darwin":
        return os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", "himalaya"
        )
    return os.path.join(os.path.expanduser("~"), ".config", "himalaya")


_TOML_TEMPLATE = """\
[accounts.gmail]
email = "{email}"
backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.login = "{email}"
backend.auth.type = "password"
backend.auth.raw = "{app_password}"
folder.aliases.inbox = "INBOX"
folder.aliases.sent = "[Gmail]/Sent Mail"
folder.aliases.drafts = "[Gmail]/Drafts"
folder.aliases.trash = "[Gmail]/Trash"
"""

# In-memory cache: last (email, app_password) we wrote config for.
_configured_for: tuple[str, str] = ("", "")


def ensure_configured(email: str, app_password: str) -> bool:
    """Write himalaya config.toml from profile creds.

    Idempotent — only rewrites the file when email/password changed.
    Returns True if the himalaya binary is on PATH and config is in place.
    Returns False (with a logged warning) when himalaya is not installed
    or credentials are missing — callers should skip the email step.
    """
    global _configured_for

    if not email or not app_password:
        logger.warning("himalaya_reader: email or app_password is empty — skipping config write")
        return False

    # Check binary is available.
    try:
        subprocess.run(["himalaya", "--version"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("himalaya binary not found — install via: brew install himalaya")
        return False

    if _configured_for == (email, app_password):
        return True  # already written this session

    cfg_dir = _config_path()
    cfg_file = os.path.join(cfg_dir, "config.toml")
    try:
        os.makedirs(cfg_dir, exist_ok=True)
        content = _TOML_TEMPLATE.format(email=email, app_password=app_password)
        with open(cfg_file, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(cfg_file, 0o600)
        _configured_for = (email, app_password)
        logger.info(f"himalaya config written for {email}")
        return True
    except Exception as e:
        logger.warning(f"himalaya config write failed: {e}")
        return False


# ── CLI wrapper ────────────────────────────────────────────────────────────

def _himalaya(*args: str, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run himalaya with the given args. Raises on timeout; returns result otherwise."""
    return subprocess.run(
        ["himalaya"] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ── Public API ─────────────────────────────────────────────────────────────

def list_envelopes(folder: str = "INBOX", page_size: int = 10) -> list[dict]:
    """Return recent envelopes from the Gmail account.

    Each item: {id, from_addr, subject, date_str}. Returns [] on any error.
    """
    try:
        result = _himalaya(
            "envelope", "list",
            "--account", "gmail",
            "--folder", folder,
            "--page-size", str(page_size),
            "--output", "json",
        )
        if result.returncode != 0:
            logger.debug(f"himalaya envelope list failed: {result.stderr[:200]}")
            return []
        raw = json.loads(result.stdout)
        out = []
        for env in raw:
            from_field = env.get("from") or {}
            addr = from_field.get("addr", "") if isinstance(from_field, dict) else str(from_field)
            out.append({
                "id": str(env.get("id", "")),
                "from_addr": addr.lower(),
                "subject": env.get("subject", ""),
                "date_str": str(env.get("date", "")),
            })
        return out
    except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        logger.debug(f"himalaya list_envelopes error: {e}")
        return []
    except Exception as e:
        logger.warning(f"himalaya list_envelopes unexpected error: {e}")
        return []


def read_message(msg_id: str, folder: str = "INBOX") -> str:
    """Return the plain-text body of an email by ID. Returns '' on error."""
    try:
        result = _himalaya(
            "message", "read",
            "--account", "gmail",
            "--folder", folder,
            str(msg_id),
        )
        return result.stdout or ""
    except subprocess.TimeoutExpired:
        logger.debug(f"himalaya read_message timed out for id={msg_id}")
        return ""
    except Exception as e:
        logger.debug(f"himalaya read_message error id={msg_id}: {e}")
        return ""


def _extract_code(text: str) -> str | None:
    """Extract a 4-8 char alphanumeric OTP code from email body text."""
    patterns = [
        r"(?:code|pin|otp|verification)[:\s]+([A-Za-z0-9]{4,8})\b",
        r"(?:code|pin|otp|verification)[:\s]+(\d{4,8})\b",
        r"\b([A-Z0-9]{8})\b",   # Greenhouse 8-char all-caps
        r"\b(\d{6})\b",          # 6-digit numeric
        r"\b(\d{4,8})\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def find_otp(
    sender_pattern: str,
    subject_pattern: str = "",
    timeout: int = 60,
    poll_interval: int = 5,
) -> str | None:
    """Poll himalaya for an OTP code from a matching sender.

    Finds the most-recent envelope where from_addr contains sender_pattern
    (and optionally subject contains subject_pattern). Reads the body and
    extracts a 4-8 char alphanumeric code. Returns None if not found within timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        envelopes = list_envelopes(page_size=10)
        for env in envelopes:
            if sender_pattern.lower() not in env["from_addr"]:
                continue
            if subject_pattern and subject_pattern.lower() not in env["subject"].lower():
                continue
            body = read_message(env["id"])
            if body:
                code = _extract_code(body)
                if code:
                    logger.info(f"himalaya_reader: found OTP from {env['from_addr']}")
                    return code
        remaining = deadline - time.time()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))
    logger.warning(
        f"himalaya_reader: no OTP from '{sender_pattern}' within {timeout}s"
    )
    return None


def find_link(
    sender_pattern: str,
    link_regex: str,
    timeout: int = 60,
    poll_interval: int = 5,
) -> str | None:
    """Poll himalaya for an email containing a URL matching link_regex.

    Used for password-reset links (Workday, ATS account creation flows).
    Returns the first URL match, or None if not found within timeout.
    """
    compiled = re.compile(link_regex)
    deadline = time.time() + timeout
    while time.time() < deadline:
        envelopes = list_envelopes(page_size=10)
        for env in envelopes:
            if sender_pattern.lower() not in env["from_addr"]:
                continue
            body = read_message(env["id"])
            if body:
                m = compiled.search(body)
                if m:
                    logger.info(
                        f"himalaya_reader: found link from {env['from_addr']}: "
                        f"{m.group(0)[:80]}"
                    )
                    return m.group(0)
        remaining = deadline - time.time()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))
    logger.warning(
        f"himalaya_reader: no link matching '{link_regex}' from '{sender_pattern}' "
        f"within {timeout}s"
    )
    return None
