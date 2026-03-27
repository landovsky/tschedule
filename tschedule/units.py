"""Generate and sync systemd user timer/service units."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import JobConfig
from .cron_convert import cron_to_systemd

SYSTEMD_USER_DIR = Path("~/.config/systemd/user").expanduser()
PREFIX = "tschedule"


def unit_name(project: str, job: str) -> str:
    safe = lambda s: s.replace('/', '-').replace(' ', '_').replace('\\', '-')
    return f"{PREFIX}-{safe(project)}-{safe(job)}"


def _tschedule_bin() -> str:
    path = shutil.which("tschedule")
    return path or str(Path("~/.local/bin/tschedule").expanduser())


def _user_path() -> str:
    """Build a PATH that includes ~/.local/bin on top of the systemd default."""
    local_bin = str(Path("~/.local/bin").expanduser())
    base = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    return f"{local_bin}:{base}"


def _service(job: JobConfig) -> str:
    bin_path = _tschedule_bin()
    lines = [
        "[Unit]",
        f"Description=tschedule job: {job.project}/{job.name}",
        f"# Source: {job.jobs_file}",
        "",
        "[Service]",
        "Type=oneshot",
        f"Environment=PATH={_user_path()}",
        f"ExecStart={bin_path} _exec {job.project} {job.name}",
        f"TimeoutStartSec={job.timeout}",
    ]
    if job.working_dir:
        lines.append(f"WorkingDirectory={job.working_dir}")
    lines.append("")
    return "\n".join(lines)


def _timer(job: JobConfig) -> str:
    calendar = job.systemd_calendar or cron_to_systemd(job.schedule)
    return "\n".join([
        "[Unit]",
        f"Description=tschedule timer: {job.project}/{job.name}",
        "",
        "[Timer]",
        f"OnCalendar={calendar}",
        "Persistent=true",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ])


def write_units(job: JobConfig) -> str:
    """Write .service and .timer files for a job. Returns the unit base name."""
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    name = unit_name(job.project, job.name)
    (SYSTEMD_USER_DIR / f"{name}.service").write_text(_service(job))
    (SYSTEMD_USER_DIR / f"{name}.timer").write_text(_timer(job))
    return name


def list_managed_units() -> set[str]:
    return {p.stem for p in SYSTEMD_USER_DIR.glob(f"{PREFIX}-*.timer")}


def _ctl(*args):
    subprocess.run(["systemctl", "--user", *args], check=False, capture_output=True)


def sync_units(jobs: list[JobConfig]) -> dict:
    """Write units for all jobs, remove orphans, reload daemon, enable timers."""
    results: dict = {'written': [], 'removed': [], 'errors': []}
    current: set[str] = set()

    for job in jobs:
        try:
            name = write_units(job)
            current.add(name)
            results['written'].append(f"{job.project}/{job.name}")
        except Exception as e:
            results['errors'].append(f"{job.project}/{job.name}: {e}")

    for existing in list_managed_units():
        if existing not in current:
            _ctl('disable', '--now', f'{existing}.timer')
            for suffix in ('.timer', '.service'):
                p = SYSTEMD_USER_DIR / f"{existing}{suffix}"
                if p.exists():
                    p.unlink()
            results['removed'].append(existing)

    _ctl('daemon-reload')

    for name in current:
        _ctl('enable', f'{name}.timer')
        _ctl('start', f'{name}.timer')

    return results


def get_next_elapse(unit: str) -> str | None:
    """Return the human-readable next elapse time for a timer unit."""
    r = subprocess.run(
        ['systemctl', '--user', 'show', f'{unit}.timer',
         '--property=NextElapseUSecRealtime', '--value'],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    val = r.stdout.strip()
    if not val or val == '0':
        return None
    # Convert microseconds epoch to datetime string via systemd-analyze
    r2 = subprocess.run(
        ['systemctl', '--user', 'list-timers', f'{unit}.timer', '--no-pager', '--no-legend'],
        capture_output=True, text=True,
    )
    if r2.returncode == 0 and r2.stdout.strip():
        parts = r2.stdout.strip().split()
        # Output: NEXT LEFT LAST PASSED UNIT ACTIVATES
        # "NEXT" is cols 0–2 (date time zone)
        if len(parts) >= 3:
            return f"{parts[0]} {parts[1]}"
    return val[:16] if len(val) > 16 else val
