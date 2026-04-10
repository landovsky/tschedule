import os
from pathlib import Path

from tschedule.config import (
    GlobalConfig,
    load_global_config,
    load_project_jobs,
    discover_all_jobs,
)


def test_load_global_config_defaults(tmp_path):
    cfg = load_global_config(config_file=tmp_path / "nonexistent.yaml")
    assert cfg.dashboard.host == "127.0.0.1"
    assert cfg.dashboard.port == 8501


def test_load_global_config_from_file(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text(
        "dashboard:\n"
        "  host: 0.0.0.0\n"
        "  port: 9000\n"
        "db:\n"
        "  path: /tmp/test.db\n"
    )
    cfg = load_global_config(config_file=conf)
    assert cfg.dashboard.host == "0.0.0.0"
    assert cfg.dashboard.port == 9000
    assert cfg.db_path == Path("/tmp/test.db")


def test_load_project_jobs(tmp_path):
    jobs_file = tmp_path / "jobs.yaml"
    jobs_file.write_text(
        "version: 1\n"
        "project: myproj\n"
        "jobs:\n"
        "  backup:\n"
        "    description: Daily backup\n"
        '    schedule: "0 2 * * *"\n'
        "    command: /usr/bin/backup.sh\n"
        "    timeout: 600\n"
        "    retries: 1\n"
        "    tags: [infra, backup]\n"
        "    env:\n"
        "      FOO: bar\n"
        "  cleanup:\n"
        "    description: Remove old files\n"
        '    schedule: "0 3 * * *"\n'
        "    command: /usr/bin/cleanup.sh\n"
    )
    jobs = load_project_jobs(jobs_file)
    assert len(jobs) == 2

    backup = next(j for j in jobs if j.name == "backup")
    assert backup.project == "myproj"
    assert backup.schedule == "0 2 * * *"
    assert backup.timeout == 600
    assert backup.retries == 1
    assert backup.tags == ["infra", "backup"]
    assert backup.env == {"FOO": "bar"}

    cleanup = next(j for j in jobs if j.name == "cleanup")
    assert cleanup.retries == 0  # default


def test_load_project_jobs_empty(tmp_path):
    jobs_file = tmp_path / "jobs.yaml"
    jobs_file.write_text("")
    assert load_project_jobs(jobs_file) == []


def test_discover_all_jobs(tmp_path):
    # Create a project directory with a jobs.yaml
    proj_dir = tmp_path / "myproject"
    proj_dir.mkdir()
    jobs_file = proj_dir / "jobs.yaml"
    jobs_file.write_text(
        "version: 1\n"
        "project: myproject\n"
        "jobs:\n"
        "  task1:\n"
        '    schedule: "0 8 * * *"\n'
        "    command: echo hello\n"
    )

    # Create projects.d with a symlink
    projects_d = tmp_path / "projects.d"
    projects_d.mkdir()
    os.symlink(str(jobs_file), str(projects_d / "myproject.yaml"))

    cfg = GlobalConfig()
    cfg.projects_dir = projects_d

    jobs = discover_all_jobs(cfg)
    assert len(jobs) == 1
    assert jobs[0].project == "myproject"
    assert jobs[0].name == "task1"
