"""Configuration loading and project discovery."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path("~/.config/tschedule").expanduser()
DATA_DIR = Path("~/.local/share/tschedule").expanduser()
PROJECTS_DIR = CONFIG_DIR / "projects.d"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DEFAULT_DB = DATA_DIR / "history.db"


@dataclass
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 8501


@dataclass
class GlobalConfig:
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    db_path: Path = field(default_factory=lambda: DEFAULT_DB)
    projects_dir: Path = field(default_factory=lambda: PROJECTS_DIR)


def load_global_config() -> GlobalConfig:
    cfg = GlobalConfig()
    if not CONFIG_FILE.exists():
        return cfg
    data = yaml.safe_load(CONFIG_FILE.read_text()) or {}
    if 'dashboard' in data:
        d = data['dashboard']
        cfg.dashboard.host = d.get('host', cfg.dashboard.host)
        cfg.dashboard.port = int(d.get('port', cfg.dashboard.port))
    if 'db' in data and 'path' in data['db']:
        cfg.db_path = Path(data['db']['path']).expanduser()
    if 'discovery' in data and 'projects_dir' in data['discovery']:
        cfg.projects_dir = Path(data['discovery']['projects_dir']).expanduser()
    return cfg


@dataclass
class JobConfig:
    name: str
    project: str
    description: str = ""
    schedule: str = ""
    command: str = ""
    working_dir: str = ""
    timeout: int = 300
    on_failure: str = "notify"
    retries: int = 0
    tags: list = field(default_factory=list)
    systemd_calendar: Optional[str] = None
    jobs_file: str = ""


def load_project_jobs(jobs_file: Path) -> list[JobConfig]:
    data = yaml.safe_load(jobs_file.read_text()) or {}
    project = data.get('project', jobs_file.parent.name)
    jobs = []
    for name, jdata in (data.get('jobs') or {}).items():
        if not isinstance(jdata, dict):
            continue
        jobs.append(JobConfig(
            name=name,
            project=project,
            description=jdata.get('description', ''),
            schedule=jdata.get('schedule', ''),
            command=jdata.get('command', ''),
            working_dir=jdata.get('working_dir', str(jobs_file.parent)),
            timeout=int(jdata.get('timeout', 300)),
            on_failure=jdata.get('on_failure', 'notify'),
            retries=int(jdata.get('retries', 0)),
            tags=list(jdata.get('tags', [])),
            systemd_calendar=jdata.get('systemd_calendar'),
            jobs_file=str(jobs_file),
        ))
    return jobs


def discover_all_jobs(cfg: GlobalConfig) -> list[JobConfig]:
    """Load jobs from the global jobs.yaml and all registered project files."""
    all_jobs: list[JobConfig] = []

    global_jobs = CONFIG_DIR / "jobs.yaml"
    if global_jobs.exists():
        all_jobs.extend(load_project_jobs(global_jobs))

    if cfg.projects_dir.exists():
        for link in sorted(cfg.projects_dir.iterdir()):
            if link.is_symlink():
                target = Path(os.readlink(link))
                if not target.is_absolute():
                    target = (link.parent / target).resolve()
            else:
                target = link
            if target.exists():
                try:
                    all_jobs.extend(load_project_jobs(target))
                except Exception as e:
                    import sys
                    print(f"Warning: could not load {target}: {e}", file=sys.stderr)

    return all_jobs
