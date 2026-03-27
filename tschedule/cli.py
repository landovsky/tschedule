"""tschedule — YAML-driven systemd user job scheduler."""
from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
def main():
    """YAML-driven systemd user job scheduler."""


# ---------------------------------------------------------------------------
# reload
# ---------------------------------------------------------------------------

@main.command()
def reload():
    """Re-read all jobs.yaml files and sync systemd units."""
    from .config import load_global_config, discover_all_jobs
    from .db import DB
    from .units import sync_units

    cfg = load_global_config()
    jobs = discover_all_jobs(cfg)

    if not jobs:
        click.echo("No jobs found. Register a project first:\n  tschedule register <dir>")
        return

    db = DB(cfg.db_path)
    for job in jobs:
        db.upsert_job(job.project, job.name, job.description, job.tags)

    results = sync_units(jobs)

    for name in results['written']:
        click.echo(f"  ✓ {name}")
    for name in results['removed']:
        click.echo(f"  - removed orphan {name}")
    for err in results['errors']:
        click.echo(f"  ✗ {err}", err=True)

    n = len(results['written'])
    click.echo(f"\nSynced {n} job{'s' if n != 1 else ''}.")


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

@main.command()
@click.argument('directory', type=click.Path(exists=True, file_okay=False))
def register(directory):
    """Register a project directory that contains a jobs.yaml file."""
    from .config import load_global_config

    cfg = load_global_config()
    proj_dir = Path(directory).resolve()
    jobs_file = proj_dir / "jobs.yaml"

    if not jobs_file.exists():
        raise click.ClickException(f"No jobs.yaml found in {proj_dir}")

    cfg.projects_dir.mkdir(parents=True, exist_ok=True)
    link_path = cfg.projects_dir / (proj_dir.name + ".yaml")

    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.symlink_to(jobs_file)
    click.echo(f"Registered: {proj_dir}")
    click.echo(f"  → {link_path} → {jobs_file}")
    click.echo("\nRun `tschedule reload` to apply.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command()
def status():
    """Show all jobs: last run, next run, error counts."""
    from .config import load_global_config, discover_all_jobs
    from .db import DB
    from .units import unit_name, get_next_elapse
    from rich import box
    from rich.console import Console
    from rich.table import Table

    cfg = load_global_config()
    db = DB(cfg.db_path)
    jobs_cfg = discover_all_jobs(cfg)
    db_map = {(r['project'], r['name']): r for r in db.get_all_jobs_with_stats()}

    console = Console()
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Project", style="bold cyan", no_wrap=True)
    table.add_column("Job", no_wrap=True)
    table.add_column("Schedule")
    table.add_column("Last run")
    table.add_column("St", justify="center")
    table.add_column("Next run")
    table.add_column("Err/7d", justify="right")
    table.add_column("Tags", style="dim")

    for job in jobs_cfg:
        stats = db_map.get((job.project, job.name))
        last_run = stats['last_run'] if stats else None
        last_run_str = last_run[:16].replace('T', ' ') if last_run else "never"
        exit_code = stats['last_exit_code'] if stats else None
        status_icon = (
            "[green]✓[/green]" if exit_code == 0
            else "[red]✗[/red]" if exit_code is not None
            else "[dim]—[/dim]"
        )
        errors = str(int(stats['errors_7d'] or 0)) if stats else "0"
        uname = unit_name(job.project, job.name)
        next_run = get_next_elapse(uname) or "—"
        tags = ", ".join(job.tags) if job.tags else ""

        table.add_row(
            job.project, job.name, job.schedule,
            last_run_str, status_icon, next_run,
            errors, tags,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

@main.command()
@click.argument('job_ref')
@click.option('-n', default=5, show_default=True, help='Number of runs to show')
def log(job_ref, n):
    """Show run history for a job (project/job or unambiguous job name)."""
    from .config import load_global_config, discover_all_jobs
    from .db import DB
    from rich.console import Console

    cfg = load_global_config()
    db = DB(cfg.db_path)
    project, job_name = _resolve(job_ref, discover_all_jobs(cfg))
    job_id = db.get_job_id(project, job_name)

    if not job_id:
        raise click.ClickException(f"No history found for {job_ref}. Has it run yet?")

    runs = db.get_run_history(job_id, limit=n)
    console = Console()

    if not runs:
        console.print("[dim]No runs recorded.[/dim]")
        return

    for run in runs:
        icon = "[green]✓[/green]" if run['exit_code'] == 0 else "[red]✗[/red]"
        console.rule(f"{icon} {run['started_at'][:19]} — exit {run['exit_code']}")
        if run['stdout']:
            console.print(run['stdout'].rstrip())
        if run['stderr']:
            console.print(f"[red]{run['stderr'].rstrip()}[/red]")


# ---------------------------------------------------------------------------
# run (manual trigger)
# ---------------------------------------------------------------------------

@main.command('run')
@click.argument('job_ref')
def run_job(job_ref):
    """Trigger a job immediately via systemd."""
    import subprocess
    from .config import load_global_config, discover_all_jobs
    from .units import unit_name

    cfg = load_global_config()
    project, job_name = _resolve(job_ref, discover_all_jobs(cfg))
    uname = unit_name(project, job_name)

    r = subprocess.run(
        ['systemctl', '--user', 'start', f'{uname}.service'],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        click.echo(f"Started {project}/{job_name}")
    else:
        raise click.ClickException(r.stderr.strip() or "systemctl start failed")


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------

@main.command()
def watch():
    """Watch jobs.yaml files for changes and auto-reload (run as a daemon)."""
    from .watcher import watch as _watch
    _watch()


# ---------------------------------------------------------------------------
# install / uninstall
# ---------------------------------------------------------------------------

@main.command()
def install():
    """Install the tschedule watcher as a systemd user service and enable it."""
    import shutil
    import subprocess

    bin_path = shutil.which("tschedule")
    if not bin_path:
        raise click.ClickException(
            "tschedule not found in PATH. Install it first:\n"
            "  pip install -e /path/to/tschedule"
        )

    unit_dir = Path("~/.config/systemd/user").expanduser()
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "tschedule-watcher.service"

    unit_path.write_text("\n".join([
        "[Unit]",
        "Description=tschedule config watcher (auto-reload on jobs.yaml change)",
        "After=default.target",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart={bin_path} watch",
        "Restart=on-failure",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]))

    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'tschedule-watcher.service'],
                   check=True)
    click.echo("tschedule-watcher.service enabled and started.")
    click.echo("\nRun `tschedule reload` to register your first jobs.")


@main.command()
def uninstall():
    """Stop and remove the tschedule watcher service."""
    import subprocess

    subprocess.run(['systemctl', '--user', 'disable', '--now', 'tschedule-watcher.service'],
                   check=False)
    unit_path = Path("~/.config/systemd/user/tschedule-watcher.service").expanduser()
    if unit_path.exists():
        unit_path.unlink()
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=False)
    click.echo("tschedule-watcher.service removed.")


# ---------------------------------------------------------------------------
# dash
# ---------------------------------------------------------------------------

@main.command()
@click.option('--host', default=None, help='Bind address (overrides config)')
@click.option('--port', default=None, type=int, help='Port (overrides config)')
def dash(host, port):
    """Launch the Streamlit dashboard."""
    import subprocess

    from .config import load_global_config
    cfg = load_global_config()
    h = host or cfg.dashboard.host
    p = port or cfg.dashboard.port

    dashboard_app = Path(__file__).parent / "_dashboard_app.py"
    click.echo(f"Starting dashboard on http://{h}:{p}")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(dashboard_app),
        "--server.address", h,
        "--server.port", str(p),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ])


# ---------------------------------------------------------------------------
# _exec (internal, called by systemd)
# ---------------------------------------------------------------------------

@main.command('_exec', hidden=True)
@click.argument('project')
@click.argument('job_name')
def _exec(project, job_name):
    """Internal: execute a job and record results. Called by systemd."""
    from .executor import exec_job
    exec_job(project, job_name)


# ---------------------------------------------------------------------------
# env — manage ~/.config/environment.d/tschedule.conf
# ---------------------------------------------------------------------------

ENV_D_FILE = Path("~/.config/environment.d/tschedule.conf").expanduser()


def _read_env_conf() -> dict[str, str]:
    if not ENV_D_FILE.exists():
        return {}
    result: dict[str, str] = {}
    for line in ENV_D_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, _, v = line.partition('=')
            result[k.strip()] = v.strip()
    return result


def _write_env_conf(env: dict[str, str]) -> None:
    ENV_D_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# tschedule global environment variables", "# Applied to all tschedule job services", ""]
    for k, v in sorted(env.items()):
        lines.append(f"{k}={v}")
    lines.append("")
    ENV_D_FILE.write_text("\n".join(lines))


@main.group()
def env():
    """Manage global environment variables for all job services.

    Variables are stored in ~/.config/environment.d/tschedule.conf
    and applied to every tschedule job run by systemd.

    After changes, run `systemctl --user daemon-reload` or
    `tschedule reload` to re-generate service units.
    """


@env.command('set')
@click.argument('key')
@click.argument('value')
def env_set(key, value):
    """Set an environment variable KEY=VALUE."""
    d = _read_env_conf()
    d[key] = value
    _write_env_conf(d)
    click.echo(f"Set {key}={value} in {ENV_D_FILE}")
    click.echo("Run `systemctl --user import-environment` or log out/in for it to take effect.")


@env.command('unset')
@click.argument('key')
def env_unset(key):
    """Remove an environment variable."""
    d = _read_env_conf()
    if key not in d:
        raise click.ClickException(f"{key} is not set.")
    del d[key]
    _write_env_conf(d)
    click.echo(f"Removed {key} from {ENV_D_FILE}")


@env.command('list')
def env_list():
    """List all global environment variables."""
    d = _read_env_conf()
    if not d:
        click.echo(f"No variables set in {ENV_D_FILE}")
        return
    for k, v in sorted(d.items()):
        click.echo(f"{k}={v}")


@env.command('edit')
def env_edit():
    """Open the env conf file in $EDITOR."""
    ENV_D_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ENV_D_FILE.exists():
        _write_env_conf({})
    click.edit(filename=str(ENV_D_FILE))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _resolve(ref: str, jobs: list) -> tuple[str, str]:
    if '/' in ref:
        project, job_name = ref.split('/', 1)
        return project, job_name
    matches = [j for j in jobs if j.name == ref]
    if len(matches) == 1:
        return matches[0].project, matches[0].name
    if len(matches) > 1:
        opts = ", ".join(f"{j.project}/{j.name}" for j in matches)
        raise click.ClickException(f"Ambiguous job name — specify as project/job: {opts}")
    raise click.ClickException(f"Job not found: {ref}")
