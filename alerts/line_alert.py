import logging
import os

import requests

logger = logging.getLogger(__name__)

LINE_TOKEN = os.getenv("LINE_TOKEN")

_LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"


def send_line_message(msg: str) -> bool:
    """
    Broadcast a text message via LINE Messaging API.

    Returns True on success, False on failure.
    """

    if not LINE_TOKEN:
        logger.warning("LINE_TOKEN not set — skipping LINE notification")
        return False

    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messages": [{"type": "text", "text": msg[:4500]}]
    }

    try:
        resp = requests.post(_LINE_BROADCAST_URL, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("LINE message sent successfully")
        return True

    except requests.RequestException as exc:
        logger.error(f"LINE send failed: {exc}")
        return False
