"""Convert 5-field cron expressions to systemd OnCalendar format."""

DOW_MAP = {
    '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed',
    '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun',
    'sun': 'Sun', 'mon': 'Mon', 'tue': 'Tue', 'wed': 'Wed',
    'thu': 'Thu', 'fri': 'Fri', 'sat': 'Sat',
}


def _field(value: str, pad: bool = True) -> str:
    """Convert a single numeric cron field to systemd format."""
    if value == '*':
        return '*'
    if value.startswith('*/'):
        step = value[2:]
        return f'00/{step}'
    if '-' in value and '/' not in value:
        # range like 1-5 — pass through for date fields
        return value
    return value.zfill(2) if pad else value


def _dow(value: str) -> str:
    if value == '*':
        return ''
    parts = value.split(',')
    converted = []
    for part in parts:
        if '-' in part:
            start, end = part.split('-', 1)
            s = DOW_MAP.get(start.lower(), start)
            e = DOW_MAP.get(end.lower(), end)
            converted.append(f'{s}..{e}')
        else:
            converted.append(DOW_MAP.get(part.lower(), part))
    return ','.join(converted) + ' '


def cron_to_systemd(cron: str) -> str:
    """Convert a 5-field cron expression to a systemd OnCalendar string.

    Examples:
        "0 8 * * *"    → "*-*-* 08:00:00"
        "*/5 * * * *"  → "*-*-* *:00/5:00"
        "0 9 * * 1-5"  → "Mon..Fri *-*-* 09:00:00"
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron expression, got: {cron!r}")

    minute, hour, dom, month, dow = parts

    m = '*' if month == '*' else month.zfill(2)
    d = '*' if dom == '*' else dom.zfill(2)
    date = f'*-{m}-{d}'

    h = _field(hour)
    mn = _field(minute)
    time_str = f'{h}:{mn}:00'

    dow_prefix = _dow(dow)
    return f'{dow_prefix}{date} {time_str}'
