from __future__ import annotations
import os
import time
import base64
import re
import logging
import hashlib

import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from db import get_client

logger = logging.getLogger(__name__)

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
AGENTMAIL_BASE_URL = "https://api.agentmail.to/v0"


def _decrypt_token(encrypted: str) -> str:
    """Decrypt a token encrypted by the web app (AES-256-CBC with scrypt key derivation).

    Format: salt_hex:iv_hex:ciphertext_hex
    """
    import binascii
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend

    parts = encrypted.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid encrypted token format (expected salt:iv:ciphertext)")

    salt = binascii.unhexlify(parts[0])
    iv = binascii.unhexlify(parts[1])
    ciphertext = binascii.unhexlify(parts[2])

    # Match Node.js crypto.scryptSync(key, salt, 32)
    import hashlib
    key = hashlib.scrypt(
        ENCRYPTION_KEY.encode(),
        salt=salt,
        n=16384, r=8, p=1, dklen=32,
    )

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    # Remove PKCS7 padding
    unpadder = padding.PKCS7(128).unpadder()
    data = unpadder.update(padded) + unpadder.finalize()
    return data.decode("utf-8")


def _get_gmail_service(user_id: str):
    """Build a Gmail API service using the user's stored OAuth tokens."""
    client = get_client()
    result = (
        client.table("gmail_tokens")
        .select("access_token_encrypted, refresh_token_encrypted, email")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise ValueError(f"No Gmail token found for user {user_id}")

    access_token = _decrypt_token(result.data["access_token_encrypted"])
    refresh_token = _decrypt_token(result.data["refresh_token_encrypted"]) if result.data["refresh_token_encrypted"] else None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    )
    return build("gmail", "v1", credentials=creds)


def check_for_verification_code(
    user_id: str, sender_pattern: str, timeout: int = 60
) -> str | None:
    """Poll Gmail for an OTP/verification code from a matching sender.

    Args:
        user_id: The user whose Gmail to check.
        sender_pattern: Substring to match in the sender address (e.g. 'greenhouse.io').
        timeout: Max seconds to poll before giving up.

    Returns:
        The extracted verification code string, or None if not found.
    """
    service = _get_gmail_service(user_id)
    start = time.time()
    poll_interval = 5

    while time.time() - start < timeout:
        try:
            results = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=f"from:{sender_pattern} newer_than:2m",
                    maxResults=5,
                )
                .execute()
            )
            messages = results.get("messages", [])

            for msg_meta in messages:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_meta["id"], format="full")
                    .execute()
                )
                body = _extract_body(msg)
                if body:
                    code = _extract_code(body)
                    if code:
                        logger.info(f"Found verification code for user {user_id}")
                        return code
        except Exception as e:
            logger.warning(f"Gmail poll error for user {user_id}: {e}")

        time.sleep(poll_interval)

    logger.warning(f"No verification code found for user {user_id} within {timeout}s")
    return None


def _extract_body(message: dict) -> str:
    """Extract plain text body from a Gmail message."""
    payload = message.get("payload", {})

    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        for subpart in part.get("parts", []):
            if subpart.get("mimeType") == "text/plain" and subpart.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(subpart["body"]["data"]).decode("utf-8", errors="replace")

    return ""


def _extract_code(text: str) -> str | None:
    """Extract a 4-8 digit/character verification code from email text."""
    patterns = [
        r"(?:code|pin|otp|verification)[:\s]*([A-Za-z0-9]{4,8})",
        r"(?:code|pin|otp|verification)[:\s]*(\d{4,8})",
        r"(\d{6})",
        r"(\d{4,8})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def get_latest_verification_code(
    user_id: str,
    sender_filter: str = "greenhouse-mail.io",
    subject_filter: str = "security code",
) -> str | None:
    """Fetch the latest email verification code (used by Greenhouse security code flow).

    Searches for recent emails matching sender and subject filters,
    then extracts the alphanumeric code from the body.
    Greenhouse codes are 8 alphanumeric characters.
    """
    try:
        service = _get_gmail_service(user_id)
    except Exception as e:
        logger.error(f"Cannot access Gmail for user {user_id}: {e}")
        return None

    try:
        query = f"from:{sender_filter} subject:{subject_filter} newer_than:5m"
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=3)
            .execute()
        )
        messages = results.get("messages", [])

        for msg_meta in messages:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_meta["id"], format="full")
                .execute()
            )
            body = _extract_body(msg)
            if body:
                code = _extract_code(body)
                if code:
                    logger.info(f"Found Greenhouse security code for user {user_id}")
                    return code

    except Exception as e:
        logger.error(f"Error reading verification email for user {user_id}: {e}")

    return None


# ─── AgentMail (Disposable Inboxes) ────────────────────────────────────────────


def create_disposable_inbox() -> str | None:
    """Create a disposable AgentMail inbox for receiving verification codes.

    Returns the inbox email address (e.g., 'clumsynews296@agentmail.to'),
    or None if AGENTMAIL_API_KEY is not set or creation fails.
    """
    if not AGENTMAIL_API_KEY:
        logger.warning("AGENTMAIL_API_KEY not set — cannot create disposable inbox")
        return None

    try:
        resp = httpx.post(
            f"{AGENTMAIL_BASE_URL}/inboxes",
            headers={"Authorization": f"Bearer {AGENTMAIL_API_KEY}"},
            json={},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        inbox_id = data.get("inbox_id", "")
        logger.info(f"Created AgentMail inbox: {inbox_id}")
        return inbox_id
    except Exception as e:
        logger.error(f"Failed to create AgentMail inbox: {e}")
        return None


def check_agentmail_inbox(
    inbox_address: str, pattern: str, timeout: int = 60
) -> str | None:
    """Poll AgentMail inbox for emails matching pattern and extract a verification code.

    Args:
        inbox_address: The AgentMail inbox email (e.g., 'user@agentmail.to').
        pattern: Substring to match in subject or sender (e.g., 'greenhouse-mail.io').
        timeout: Max seconds to poll before giving up.

    Returns:
        The extracted verification code string, or None if not found.
    """
    if not AGENTMAIL_API_KEY:
        logger.warning("AGENTMAIL_API_KEY not set — cannot check AgentMail inbox")
        return None

    start = time.time()
    poll_interval = 5

    while time.time() - start < timeout:
        try:
            resp = httpx.get(
                f"{AGENTMAIL_BASE_URL}/inboxes/{inbox_address}/messages",
                headers={"Authorization": f"Bearer {AGENTMAIL_API_KEY}"},
                timeout=15,
            )
            resp.raise_for_status()
            messages = resp.json().get("messages", [])

            for msg in messages:
                sender = msg.get("from", "")
                subject = msg.get("subject", "")
                body = msg.get("text", "") or msg.get("body", "")
                if pattern.lower() in sender.lower() or pattern.lower() in subject.lower():
                    code = _extract_code(body)
                    if code:
                        logger.info(f"Found verification code in AgentMail inbox {inbox_address}")
                        return code
        except Exception as e:
            logger.warning(f"AgentMail poll error for {inbox_address}: {e}")

        time.sleep(poll_interval)

    logger.warning(f"No verification code found in AgentMail inbox {inbox_address} within {timeout}s")
    return None
