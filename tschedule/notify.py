"""Telegram notifications for job results."""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from typing import Optional


def send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    """Send a message via Telegram Bot API. Raises on failure."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def should_notify(
    policy: str,
    exit_code: int,
    prev_exit_code: Optional[int],
) -> bool:
    """Decide whether to send a notification based on policy and results."""
    if policy == "always":
        return True
    if policy == "never":
        return False
    if policy == "on_error":
        return exit_code != 0
    if policy == "on_repeated_error":
        return exit_code != 0 and prev_exit_code is not None and prev_exit_code != 0
    return False


def format_message(
    project: str,
    job_name: str,
    exit_code: int,
    elapsed: float,
    stdout_text: str,
    stderr_text: str,
) -> str:
    """Format a notification message."""
    icon = "\u2705" if exit_code == 0 else "\u274c"
    status = "ok" if exit_code == 0 else f"failed (exit {exit_code})"
    msg = f"{icon} `{project}/{job_name}` {status} in {elapsed:.1f}s"
    # Include stdout when present (e.g. audit reports)
    if stdout_text.strip():
        excerpt = stdout_text.strip()[:3000]
        msg += f"\n\n{excerpt}"
    # Append stderr on failure
    if exit_code != 0 and stderr_text.strip():
        excerpt = stderr_text.strip()[:500]
        msg += f"\n```\n{excerpt}\n```"
    return msg
