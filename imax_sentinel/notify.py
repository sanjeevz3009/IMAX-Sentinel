"""
notify.py — Telegram notification dispatcher

Sends alerts when:
  - A watched film appears for the first time (new listing)
  - A performance status changes to "available" (tickets open)
  - A performance status changes to "soldout" (optional, for awareness)

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as environment variables
or in your secrets store. Never put them in config.toml.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ---------------------------------------------------------------------------
# Low-level send
# ---------------------------------------------------------------------------


def _send(token: str, chat_id: str, text: str) -> bool:
    """
    POST a message to Telegram. Returns True on success.
    Uses MarkdownV2 formatting.
    """
    url = TELEGRAM_API.format(token=token)
    try:
        resp = httpx.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.debug("Telegram message sent OK")
        return True
    except Exception as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        return False


def _escape(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def _get_credentials() -> tuple[str, str] | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — notifications disabled")
        return None
    return token, chat_id


# ---------------------------------------------------------------------------
# Public notification helpers
# ---------------------------------------------------------------------------


def notify_new_listing(
    title: str,
    datetime_str: str,
    status: str,
    booking_url: str,
    source_url: str,
) -> None:
    """Alert: a watched film has appeared on the listings page for the first time."""
    creds = _get_credentials()
    if not creds:
        return
    token, chat_id = creds

    status_label = {
        "available": "🎟 Tickets available",
        "soldout": "❌ Sold out",
        "unavailable": "🕐 Not yet on sale",
    }.get(status, status)

    text = (
        f"🎬 *New listing detected\\!*\n\n"
        f"*{_escape(title)}*\n"
        f"📅 {_escape(datetime_str)}\n"
        f"🏛 BFI IMAX\n"
        f"Status: {_escape(status_label)}\n\n"
        f"[Book now]({_escape(booking_url)})"
    )

    logger.info("Sending new-listing alert: %s @ %s", title, datetime_str)
    _send(token, chat_id, text)


def notify_status_change(
    title: str,
    datetime_str: str,
    old_status: str,
    new_status: str,
    booking_url: str,
) -> None:
    """Alert: a tracked performance has changed status."""
    creds = _get_credentials()
    if not creds:
        return
    token, chat_id = creds

    # Only notify on transitions we actually care about
    interesting = {
        ("unavailable", "available"),
        ("soldout", "available"),  # re-release / returned tickets
        ("unavailable", "soldout"),  # sold out before we could act — still useful to know
    }
    if (old_status, new_status) not in interesting:
        logger.debug(
            "Skipping non-interesting status change %s → %s for %s",
            old_status,
            new_status,
            title,
        )
        return

    emoji = "🎟" if new_status == "available" else "❌"
    label = {
        "available": "Tickets now OPEN",
        "soldout": "Just sold out",
    }.get(new_status, new_status)

    text = (
        f"{emoji} *{_escape(label)}\\!*\n\n"
        f"*{_escape(title)}*\n"
        f"📅 {_escape(datetime_str)}\n"
        f"🏛 BFI IMAX\n"
        f"_{_escape(old_status)} → {_escape(new_status)}_\n\n"
        f"[Book now]({_escape(booking_url)})"
    )

    logger.info(
        "Sending status-change alert: %s  %s → %s @ %s",
        title,
        old_status,
        new_status,
        datetime_str,
    )
    _send(token, chat_id, text)


def notify_health_check(successful: int, challenges: int, failed: int) -> None:
    """Daily heartbeat so you know the bot is still alive."""
    creds = _get_credentials()
    if not creds:
        return
    token, chat_id = creds

    text = (
        f"💚 *IMAX Sentinel heartbeat*\n\n"
        f"✅ Successful fetches: {_escape(str(successful))}\n"
        f"🛡 Challenge pages: {_escape(str(challenges))}\n"
        f"❌ Failed fetches: {_escape(str(failed))}"
    )
    _send(token, chat_id, text)
