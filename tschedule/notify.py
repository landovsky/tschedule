"""Telegram notifications for job results, via the devops-telegram /notify service.

We do NOT talk to the Telegram Bot API directly. Instead we shell out to the
canonical `notify-tomas-telegram` wrapper (in ~/.dotfiles/bin), which owns the
/notify endpoint, X-Notify-Token auth, MarkdownV2 escaping, and bot routing.
That keeps one integration point shared with the self-send job scripts and the
audit skills — no second copy of the protocol to drift out of sync.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

DEFAULT_NOTIFIER = "notify-tomas-telegram"
# Fallback for contexts where ~/.dotfiles/bin isn't on PATH (e.g. a bare systemd env).
_FALLBACK_NOTIFIER = Path("~/.dotfiles/bin/notify-tomas-telegram").expanduser()


def resolve_notifier(notifier: str = DEFAULT_NOTIFIER) -> Optional[str]:
    """Resolve the wrapper to a runnable path, or None if it can't be found."""
    found = shutil.which(notifier)
    if found:
        return found
    p = Path(notifier).expanduser()
    if p.is_absolute() and p.exists():
        return str(p)
    if notifier == DEFAULT_NOTIFIER and _FALLBACK_NOTIFIER.exists():
        return str(_FALLBACK_NOTIFIER)
    return None


def channel_to_bot(channel: str) -> str:
    """Map a tschedule channel to a wrapper bot identity.

    The wrapper takes a required <bot>: `devops` (sends no /notify channel param,
    so the service routes to its default bot / broadcast) or `assistant`
    (channel=assistant — a direct DM to Tomáš). Anything that isn't explicitly
    the assistant routes to devops, so an empty/"default"/unknown channel keeps
    today's broadcast behaviour.
    """
    return "assistant" if channel.strip().lower() == "assistant" else "devops"


def send_notification(
    message: str,
    channel: str = "",
    notifier: str = DEFAULT_NOTIFIER,
) -> None:
    """Send `message` via the notify wrapper. Raises on missing wrapper or failure."""
    bin_path = resolve_notifier(notifier)
    if bin_path is None:
        raise FileNotFoundError(f"notifier not found: {notifier}")
    bot = channel_to_bot(channel)
    # Pass plain text; the wrapper escapes MarkdownV2 reserved chars for us.
    subprocess.run(
        [bin_path, bot, message],
        check=True, capture_output=True, text=True, timeout=15,
    )


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
    """Format a notification as plain text.

    No Markdown: the /notify endpoint renders MarkdownV2 and the wrapper escapes
    every reserved char (backticks included), so any markup we added would show
    up literally — `code` would render as a backtick-wrapped word, not code.
    """
    icon = "✅" if exit_code == 0 else "❌"
    status = "ok" if exit_code == 0 else f"failed (exit {exit_code})"
    msg = f"{icon} {project}/{job_name} {status} in {elapsed:.1f}s"
    # Include stdout when present (e.g. audit reports)
    if stdout_text.strip():
        excerpt = stdout_text.strip()[:3000]
        msg += f"\n\n{excerpt}"
    # Append stderr on failure
    if exit_code != 0 and stderr_text.strip():
        excerpt = stderr_text.strip()[:500]
        msg += f"\n\n{excerpt}"
    return msg
