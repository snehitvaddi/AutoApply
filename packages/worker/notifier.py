from __future__ import annotations
import logging
import httpx

from db import get_user_telegram_chat_id, get_global_knowledge

logger = logging.getLogger(__name__)

_bot_token: str | None = None


def _get_bot_token() -> str:
    global _bot_token
    if _bot_token is None:
        config = get_global_knowledge("telegram_bot_token")
        if not config:
            raise RuntimeError("telegram_bot_token not found in knowledge_base")
        _bot_token = config if isinstance(config, str) else config.get("token", "")
    return _bot_token


def _telegram_api(method: str, **kwargs) -> dict:
    token = _get_bot_token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    resp = httpx.post(url, **kwargs, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_application_result(
    user_id: str,
    job: dict,
    screenshot_path: str | None,
    profile_name: str | None = None,
):
    """Send a photo + caption to the user's Telegram after a successful
    application. `profile_name` is the name of the multi-profile bundle
    this application was submitted under — only rendered when the user
    has >1 bundle, so single-profile users see no change."""
    chat_id = get_user_telegram_chat_id(user_id)
    if not chat_id:
        logger.warning(f"No Telegram chat_id for user {user_id}, skipping notification")
        return

    company = job.get("company", "Unknown")
    role = job.get("title", "Unknown")
    posted = job.get("posted_at", "N/A")
    ats = job.get("ats", "N/A")

    profile_line = f"\n*Profile:* {profile_name}" if profile_name else ""
    caption = (
        f"*Applied*{profile_line}\n"
        f"*Role:* {role}\n"
        f"*Company:* {company}\n"
        f"*ATS:* {ats}\n"
        f"*Posted:* {posted}"
    )

    try:
        if screenshot_path:
            with open(screenshot_path, "rb") as photo:
                _telegram_api(
                    "sendPhoto",
                    data={"chat_id": chat_id, "parse_mode": "Markdown", "caption": caption},
                    files={"photo": ("screenshot.png", photo, "image/png")},
                )
        else:
            _telegram_api(
                "sendMessage",
                data={"chat_id": chat_id, "parse_mode": "Markdown", "text": caption},
            )
    except Exception as e:
        logger.error(f"Failed to send Telegram notification for user {user_id}: {e}")


def send_failure(
    user_id: str,
    company: str,
    role: str,
    error: str | None,
    screenshot_path: str | None = None,
):
    """Send a failure notification to the user's Telegram. If a screenshot
    path is given, attach the image (parity with send_application_result).
    """
    chat_id = get_user_telegram_chat_id(user_id)
    if not chat_id:
        return

    text = (
        f"*Application Failed*\n"
        f"*Role:* {role}\n"
        f"*Company:* {company}\n"
        f"*Error:* {error or 'Unknown error'}"
    )

    try:
        if screenshot_path:
            try:
                with open(screenshot_path, "rb") as photo:
                    _telegram_api(
                        "sendPhoto",
                        data={"chat_id": chat_id, "parse_mode": "Markdown", "caption": text},
                        files={"photo": ("fail.png", photo, "image/png")},
                    )
                    return
            except Exception as e:
                logger.debug(f"Failed to attach screenshot, sending text only: {e}")
        _telegram_api(
            "sendMessage",
            data={"chat_id": chat_id, "parse_mode": "Markdown", "text": text},
        )
    except Exception as e:
        logger.error(f"Failed to send failure notification for user {user_id}: {e}")


def send_scout_summary(user_id: str, raw: int, enqueued: int, per_source: dict):
    """Fire after each scout cycle so the user sees activity even when
    nothing submitted. Short by design — the goal is presence, not detail.
    """
    chat_id = get_user_telegram_chat_id(user_id)
    if not chat_id:
        return
    if raw == 0 and enqueued == 0:
        # Skip empty-cycle spam — nothing interesting to report.
        return
    # Only include non-zero sources so the line stays short on busy cycles.
    src_line = ", ".join(f"{k}: {v}" for k, v in per_source.items() if v) or "—"
    text = (
        f"*Scout*\n"
        f"Discovered *{raw}* jobs, enqueued *{enqueued}*.\n"
        f"_Sources:_ {src_line}"
    )
    try:
        _telegram_api(
            "sendMessage",
            data={"chat_id": chat_id, "parse_mode": "Markdown", "text": text},
        )
    except Exception as e:
        logger.debug(f"scout-summary send failed (non-fatal): {e}")


def send_session_event(user_id: str, event: str, detail: str = ""):
    """Session-lifecycle notifications — worker_started, auth_expired,
    rate_limit, paused, resumed. Plain text, fire-and-forget.
    """
    chat_id = get_user_telegram_chat_id(user_id)
    if not chat_id:
        return
    emoji = {
        "worker_started": "🟢",
        "auth_expired": "🔴",
        "rate_limit": "⚠️",
        "paused": "⏸️",
        "resumed": "▶️",
    }.get(event, "ℹ️")
    text = f"{emoji} *{event.replace('_', ' ').title()}*"
    if detail:
        text += f"\n{detail}"
    try:
        _telegram_api(
            "sendMessage",
            data={"chat_id": chat_id, "parse_mode": "Markdown", "text": text},
        )
    except Exception as e:
        logger.debug(f"session-event send failed (non-fatal): {e}")


def send_daily_summary(user_id: str, stats: dict):
    """Send a daily summary of application stats to the user's Telegram."""
    chat_id = get_user_telegram_chat_id(user_id)
    if not chat_id:
        return

    submitted = stats.get("submitted", 0)
    failed = stats.get("failed", 0)
    skipped = stats.get("skipped", 0)
    total = submitted + failed + skipped

    text = (
        f"*Daily Summary*\n"
        f"*Total:* {total}\n"
        f"*Submitted:* {submitted}\n"
        f"*Failed:* {failed}\n"
        f"*Skipped:* {skipped}"
    )

    try:
        _telegram_api(
            "sendMessage",
            data={"chat_id": chat_id, "parse_mode": "Markdown", "text": text},
        )
    except Exception as e:
        logger.error(f"Failed to send daily summary for user {user_id}: {e}")
