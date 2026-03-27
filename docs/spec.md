# tschedule — Design Specification

_Written: 2026-03-27_

## Problem

No existing tool satisfies all of:
- YAML job definitions that live in a git repo (per project)
- Runs scheduled jobs as a regular Linux user (no root, no daemon process required)
- Records full run history (stdout, stderr, exit code) to a queryable store
- CLI status view: upcoming jobs, last run, error counts
- Web dashboard for overview across projects
- Auto-reloads config on file change

The closest candidate (**Jobber**) matches architecturally but is explicitly unmaintained (2024). **Yacron** has the best YAML format but has zero persistence. **Cronicle** has the best dashboard but jobs are UI-managed, not file-driven.

## Prior art reviewed

| Tool | YAML | Git-friendly | History | CLI status | Dashboard | Status |
|---|---|---|---|---|---|---|
| Jobber | ✅ | ✅ | flat logs | ✅ | ✗ | **dead** |
| Yacron | ✅ | ✅ | ✗ | REST only | ✗ | slow |
| Supercronic | crontab | partial | ✗ | ✗ | ✗ | active |
| Ofelia | INI | partial | ✗ | ✗ | fork | active |
| Cronicle | UI/JSON | ✗ | ✅ | REST+UI | ✅ | active |
| Dkron | YAML daemon | ✗ | ✅ | REST+UI | ✅ | active |
| Healthchecks | (monitoring) | ✗ | ✅ | ✅ | ✅ | active |

## Architecture

tschedule is a thin Python CLI that:
1. Reads YAML job definition files
2. Generates and manages `systemd --user` timer + service units
3. Wraps job execution to record run history in SQLite
4. Provides a `rich`-based CLI status view
5. Provides a Streamlit dashboard

systemd does the actual scheduling and process management. tschedule is not a long-running daemon (except the optional file watcher).

```
jobs.yaml  ──► tschedule reload ──► ~/.config/systemd/user/tschedule-*.{timer,service}
                                                  │
                                          systemd fires timer
                                                  │
                                    tschedule _exec <project> <job>
                                                  │
                                    runs command, records to SQLite
                                                  │
                              ~/.local/share/tschedule/history.db
```

## Job definition file (`jobs.yaml`)

Committed to the project's git repository.

```yaml
version: 1
project: my-project          # used for grouping; defaults to directory name

jobs:
  job-name:
    description: Human readable description
    schedule: "0 8 * * *"    # standard 5-field cron expression
    command: some-command --with-args
    working_dir: /path/to/project      # defaults to jobs.yaml directory
    timeout: 300                       # seconds; default 300
    on_failure: notify                 # notify | retry | ignore (future)
    retries: 1                         # retry count on failure; default 0
    tags: [tag1, tag2]                 # arbitrary tags for filtering
    systemd_calendar: "Mon..Fri *-*-* 08:00:00"  # override cron conversion
```

### Cron → systemd OnCalendar conversion

Common patterns are auto-converted:

| Cron | systemd OnCalendar |
|---|---|
| `* * * * *` | `*-*-* *:*:00` |
| `0 8 * * *` | `*-*-* 08:00:00` |
| `*/5 * * * *` | `*-*-* *:00/5:00` |
| `0 9 * * 1-5` | `Mon..Fri *-*-* 09:00:00` |

For complex patterns, use the `systemd_calendar` escape hatch.

## Global config (`~/.config/tschedule/config.yaml`)

```yaml
dashboard:
  host: 127.0.0.1   # 0.0.0.0 to expose on LAN
  port: 8501

db:
  path: ~/.local/share/tschedule/history.db

discovery:
  projects_dir: ~/.config/tschedule/projects.d
```

## Project registration

Projects are registered by symlinking their `jobs.yaml` into `~/.config/tschedule/projects.d/`:

```
tschedule register /path/to/project
```

This creates:
```
~/.config/tschedule/projects.d/project-name.yaml -> /path/to/project/jobs.yaml
```

One global `~/.config/tschedule/jobs.yaml` is also supported for user-level jobs not tied to a project.

## SQLite schema

```sql
-- Job registry: updated on every reload
CREATE TABLE jobs (
    id          INTEGER PRIMARY KEY,
    project     TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',   -- JSON array
    UNIQUE(project, name)
);

-- One row per execution
CREATE TABLE runs (
    id          INTEGER PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    started_at  TEXT NOT NULL,       -- ISO8601 UTC
    finished_at TEXT,
    exit_code   INTEGER,
    stdout      TEXT,
    stderr      TEXT
);
```

Tags are stored as a JSON array (no join table). Queryable with SQLite's `json_each()`.

## systemd unit structure

For each job, two units are generated:

**`~/.config/systemd/user/tschedule-{project}-{job}.service`**
```ini
[Unit]
Description=tschedule job: project/job

[Service]
Type=oneshot
ExecStart=/path/to/tschedule _exec project job
WorkingDirectory=/path/to/project
TimeoutStartSec=300
```

**`~/.config/systemd/user/tschedule-{project}-{job}.timer`**
```ini
[Unit]
Description=tschedule timer: project/job

[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`Persistent=true` means a missed run (e.g. machine was off) fires on next boot.

## Auto-reload

The optional watcher daemon (`tschedule watch`) uses `watchdog` (inotify) to monitor all registered `jobs.yaml` files and the global config dir. On change, it calls `tschedule reload` with a 2-second debounce.

Install as a systemd user service:
```
tschedule install
```

This writes and enables `~/.config/systemd/user/tschedule-watcher.service`.

## CLI reference

```
tschedule register <dir>    Register a project directory
tschedule reload            Sync all jobs.yaml → systemd units + DB
tschedule status            Table: all jobs, last run, next run, errors/7d
tschedule log <job> [-n N]  Show last N run logs (stdout + stderr)
tschedule run <job>         Trigger a job immediately via systemd
tschedule watch             Run file watcher daemon (called by systemd service)
tschedule install           Install + enable tschedule-watcher.service
tschedule uninstall         Remove tschedule-watcher.service
tschedule dash [--host H] [--port P]   Launch Streamlit dashboard
```

Job references: `project/job` or just `job` if unambiguous across all projects.

## Streamlit dashboard (`tschedule dash`)

- Jobs grouped by project
- Per-job: schedule, tags, last run time, status (✅/❌), errors in last 7 days, total runs
- Recent runs table with project/job filter and success/failed filter
- Log viewer: expandable stdout + stderr per run
- Bind address from `config.yaml`; `--host 0.0.0.0` to expose on LAN

## File layout

```
~/.config/tschedule/
├── config.yaml                     global config
├── jobs.yaml                       optional global jobs (not project-specific)
└── projects.d/
    └── my-project.yaml  ->  /path/to/my-project/jobs.yaml

~/.config/systemd/user/
├── tschedule-watcher.service
├── tschedule-myproject-myjob.service
└── tschedule-myproject-myjob.timer

~/.local/share/tschedule/
└── history.db

/path/to/project/
└── jobs.yaml                       ← committed to git
```

## Design decisions

**Why systemd user timers (not a scheduler daemon)?**
systemd is always available on modern Linux, handles persistence across reboots (`Persistent=true`), provides process isolation, and logs to journald automatically. No custom daemon needed for scheduling.

**Why SQLite (not journald / flat files)?**
Queryable history, tags filter via `json_each()`, dashboard can read directly without parsing logs. Single file, zero setup.

**Why per-project `jobs.yaml` (not a central registry)?**
Job definitions travel with the project in git. When the project is cloned on a new machine, the jobs are already there — just `tschedule register .` and `tschedule reload`.

**Why Streamlit (not a custom web app)?**
Zero frontend code to maintain. Pure Python. The dashboard is a nice-to-have, not the primary interface.

**Tags stored as JSON array in SQLite (not a join table)**
Single-user tool with small data volumes. `json_each()` is sufficient for filtering. A join table would add schema complexity with no benefit at this scale.
