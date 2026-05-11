import json
from unittest.mock import patch, MagicMock

from tschedule.notify import should_notify, format_message, send_telegram


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


# --- send_telegram ---

@patch("tschedule.notify.urllib.request.urlopen")
def test_send_telegram_posts_correctly(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    send_telegram("TOKEN", "CHAT", "hello")

    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert "TOKEN" in req.full_url
    body = json.loads(req.data)
    assert body["chat_id"] == "CHAT"
    assert body["text"] == "hello"
