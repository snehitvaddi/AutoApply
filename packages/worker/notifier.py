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


def send_application_result(user_id: str, job: dict, screenshot_path: str | None):
    """Send a photo + caption to the user's Telegram after a successful application."""
    chat_id = get_user_telegram_chat_id(user_id)
    if not chat_id:
        logger.warning(f"No Telegram chat_id for user {user_id}, skipping notification")
        return

    company = job.get("company", "Unknown")
    role = job.get("title", "Unknown")
    posted = job.get("posted_at", "N/A")
    ats = job.get("ats", "N/A")

    caption = (
        f"*Applied*\n"
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


def send_failure(user_id: str, company: str, role: str, error: str | None):
    """Send a failure notification to the user's Telegram."""
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
        _telegram_api(
            "sendMessage",
            data={"chat_id": chat_id, "parse_mode": "Markdown", "text": text},
        )
    except Exception as e:
        logger.error(f"Failed to send failure notification for user {user_id}: {e}")


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
