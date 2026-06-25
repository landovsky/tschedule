from unittest.mock import patch

import pytest

from tschedule.notify import (
    should_notify,
    format_message,
    send_notification,
    channel_to_bot,
)


# --- should_notify ---

def test_always_notifies_on_success():
    assert should_notify("always", 0, None) is True

def test_always_notifies_on_failure():
    assert should_notify("always", 1, None) is True

def test_never_suppresses_on_failure():
    assert should_notify("never", 1, None) is False

def test_on_error_notifies_on_failure():
    assert should_notify("on_error", 1, None) is True

def test_on_error_silent_on_success():
    assert should_notify("on_error", 0, None) is False

def test_on_repeated_error_first_failure_silent():
    assert should_notify("on_repeated_error", 1, None) is False

def test_on_repeated_error_after_success_silent():
    assert should_notify("on_repeated_error", 1, 0) is False

def test_on_repeated_error_after_failure_notifies():
    assert should_notify("on_repeated_error", 1, 1) is True

def test_on_repeated_error_success_silent():
    assert should_notify("on_repeated_error", 0, 1) is False

def test_unknown_policy_silent():
    assert should_notify("bogus", 1, None) is False


# --- format_message ---

def test_format_success():
    msg = format_message("proj", "job", 0, 12.345, "", "")
    assert "proj/job" in msg
    assert "ok" in msg
    assert "12.3s" in msg

def test_format_success_with_stdout():
    msg = format_message("proj", "job", 0, 5.0, "Audit report here", "")
    assert "Audit report here" in msg

def test_format_failure_with_stderr():
    msg = format_message("proj", "job", 1, 5.0, "", "something broke")
    assert "failed (exit 1)" in msg
    assert "something broke" in msg

def test_format_failure_truncates_long_stderr():
    long_err = "x" * 1000
    msg = format_message("proj", "job", 1, 1.0, "", long_err)
    # stderr excerpt truncated to 500 chars
    assert "x" * 500 in msg
    assert "x" * 501 not in msg

def test_format_truncates_long_stdout():
    long_out = "y" * 5000
    msg = format_message("proj", "job", 0, 1.0, long_out, "")
    assert "y" * 3000 in msg
    assert "y" * 3001 not in msg


# --- format_message uses plain text, not Markdown ---

def test_format_message_has_no_markdown_markup():
    # The /notify endpoint renders MarkdownV2 and the wrapper escapes every
    # reserved char (backticks included), so any markup we emitted would surface
    # literally. Keep the message plain so it reads cleanly after escaping.
    msg = format_message("proj", "job", 1, 1.0, "report body", "boom")
    assert "`" not in msg
    assert "```" not in msg


# --- channel_to_bot: only "assistant" routes off the default bot ---

def test_assistant_channel_maps_to_assistant_bot():
    # Per-job channel: assistant -> a direct DM to Tomáš via the assistant bot.
    assert channel_to_bot("assistant") == "assistant"

def test_assistant_channel_is_case_and_space_insensitive():
    # A stray "Assistant" / " assistant " in YAML must still route personally,
    # not silently fall back to broadcasting to every DevOps subscriber.
    assert channel_to_bot("  Assistant  ") == "assistant"

@pytest.mark.parametrize("channel", ["", "default", "devops", "unknown"])
def test_non_assistant_channels_keep_default_broadcast(channel):
    # Empty/default/unknown all map to devops, which sends no /notify channel
    # param — preserving today's default-bot broadcast behaviour.
    assert channel_to_bot(channel) == "devops"


# --- send_notification shells out to the wrapper ---

@patch("tschedule.notify.subprocess.run")
@patch("tschedule.notify.resolve_notifier", return_value="/bin/notify-tomas-telegram")
def test_send_notification_invokes_wrapper_with_bot_and_message(mock_resolve, mock_run):
    send_notification("hello", channel="assistant")

    mock_run.assert_called_once()
    argv = mock_run.call_args[0][0]
    assert argv == ["/bin/notify-tomas-telegram", "assistant", "hello"]
    # We rely on the wrapper to fail loudly so a broken delivery isn't swallowed.
    assert mock_run.call_args.kwargs["check"] is True

@patch("tschedule.notify.subprocess.run")
@patch("tschedule.notify.resolve_notifier", return_value=None)
def test_send_notification_raises_when_wrapper_missing(mock_resolve, mock_run):
    # No wrapper on the box -> raise rather than silently no-op, so the caller
    # (executor) can log it. The executor pre-checks resolve_notifier to stay
    # quiet on dev/CI boxes where the wrapper legitimately isn't installed.
    with pytest.raises(FileNotFoundError):
        send_notification("hello")
    mock_run.assert_not_called()
