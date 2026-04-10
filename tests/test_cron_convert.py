import pytest

from tschedule.cron_convert import cron_to_systemd, _field, _dow


@pytest.mark.parametrize("cron, expected", [
    ("0 8 * * *", "*-*-* 08:00:00"),
    ("*/5 * * * *", "*-*-* *:00/5:00"),
    ("0 9 * * 1-5", "Mon..Fri *-*-* 09:00:00"),
    ("30 2 1 * *", "*-*-01 02:30:00"),
    ("0 0 * * 0", "Sun *-*-* 00:00:00"),
    ("0 12 * * mon,wed,fri", "Mon,Wed,Fri *-*-* 12:00:00"),
    ("*/15 */2 * * *", "*-*-* 00/2:00/15:00"),
    ("0 0 1 1 *", "*-01-01 00:00:00"),
    ("5 4 * * 7", "Sun *-*-* 04:05:00"),
])
def test_cron_to_systemd(cron, expected):
    assert cron_to_systemd(cron) == expected


def test_cron_to_systemd_invalid():
    with pytest.raises(ValueError, match="Expected 5-field"):
        cron_to_systemd("* * * * * *")


@pytest.mark.parametrize("value, expected", [
    ("*", "*"),
    ("*/5", "00/5"),
    ("30", "30"),
    ("5", "05"),
    ("1-5", "1-5"),
])
def test_field(value, expected):
    assert _field(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("*", ""),
    ("1-5", "Mon..Fri "),
    ("0", "Sun "),
    ("mon,wed,fri", "Mon,Wed,Fri "),
])
def test_dow(value, expected):
    assert _dow(value) == expected
