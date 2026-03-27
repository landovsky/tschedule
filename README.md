# tschedule

YAML-driven job scheduler for Linux, built on top of `systemd --user` timers.

Define jobs in a `jobs.yaml` committed to your project repo. tschedule generates the systemd units, records every run to SQLite, and gives you a CLI status view and Streamlit dashboard — with no daemon required.

---

## Why

Every existing YAML-friendly scheduler either has no run history ([yacron](https://github.com/gjcarneiro/yacron)), is unmaintained ([jobber](https://github.com/dshearer/jobber)), or stores jobs in a web UI rather than files ([Cronicle](https://github.com/jhuckaby/Cronicle)). tschedule fills the gap:

- Jobs defined in **`jobs.yaml`** alongside your project code — version-controlled, diff-able, portable
- Scheduling delegated to **systemd user timers** — no custom daemon, survives reboots, journald integration
- Full **SQLite run history** — stdout, stderr, exit code, timestamps, tags
- **CLI status** with last run, next run, error counts
- Optional **Streamlit dashboard** across all registered projects

---

## Requirements

- Linux with systemd (user session enabled)
- Python 3.10+
- `systemctl --user` working for your user

---

## Installation

```bash
python3 -m venv ~/.venvs/tschedule
~/.venvs/tschedule/bin/pip install tschedule

# or from source
git clone https://github.com/landovsky/tschedule
python3 -m venv ~/.venvs/tschedule
~/.venvs/tschedule/bin/pip install -e tschedule/

# put the binary on PATH
ln -sf ~/.venvs/tschedule/bin/tschedule ~/.local/bin/tschedule
```

Enable the optional file-watcher service (auto-reloads when `jobs.yaml` changes):

```bash
tschedule install
```

---

## Quick start

**1. Add a `jobs.yaml` to your project:**

```yaml
version: 1
project: my-project

jobs:
  nightly-report:
    description: Generate nightly summary
    schedule: "0 2 * * *"       # 02:00 every night
    command: python scripts/report.py
    working_dir: /home/alice/projects/my-project
    timeout: 120
    retries: 1
    tags: [reports, nightly]
```

**2. Register the project and sync units:**

```bash
tschedule register /home/alice/projects/my-project
tschedule reload
```

**3. Check status:**

```bash
tschedule status
```

```
╭──────────────┬────────────────┬───────────┬──────────────────┬────┬──────────────────┬────────┬──────────╮
│ Project      │ Job            │ Schedule  │ Last run         │ St │ Next run         │ Err/7d │ Tags     │
├──────────────┼────────────────┼───────────┼──────────────────┼────┼──────────────────┼────────┼──────────┤
│ my-project   │ nightly-report │ 0 2 * * * │ never            │ —  │ Sat 2026-03-28   │      0 │ reports, │
╰──────────────┴────────────────┴───────────┴──────────────────┴────┴──────────────────┴────────┴──────────╯
```

---

## Job definition reference

```yaml
version: 1
project: my-project          # Grouping label. Defaults to directory name.

jobs:
  job-name:
    description: Human readable description
    schedule: "0 8 * * *"    # 5-field cron expression (required)
    command: your-command --args
    working_dir: /path/to/dir        # Default: directory containing jobs.yaml
    timeout: 300                     # Seconds before SIGKILL. Default: 300
    on_failure: notify               # notify | ignore  (future: retry handler)
    retries: 1                       # Extra attempts on non-zero exit. Default: 0
    tags: [tag1, tag2]               # Arbitrary tags for filtering
    systemd_calendar: "Mon..Fri *-*-* 08:00:00"  # Override cron conversion
```

### Cron → systemd calendar conversion

Standard 5-field cron is automatically converted to systemd `OnCalendar` format:

| Cron | systemd OnCalendar |
|---|---|
| `0 8 * * *` | `*-*-* 08:00:00` |
| `*/5 * * * *` | `*-*-* *:00/5:00` |
| `0 9 * * 1-5` | `Mon..Fri *-*-* 09:00:00` |
| `30 6 1 * *` | `*-*-01 06:30:00` |

For complex expressions not handled by the converter, use `systemd_calendar:` to pass the value directly.

---

## CLI reference

```
tschedule register <dir>         Register a project directory (must contain jobs.yaml)
tschedule reload                 Sync all jobs.yaml files → systemd units + DB
tschedule status                 Show all jobs: last run, next run, errors/7d
tschedule log <job> [-n N]       Show last N run logs (stdout + stderr)
tschedule run <job>              Trigger a job immediately via systemd
tschedule watch                  Run file-watcher daemon (auto-reload on change)
tschedule install                Install + enable tschedule-watcher.service
tschedule uninstall              Remove tschedule-watcher.service
tschedule dash [--host H] [--port P]  Launch Streamlit dashboard
```

Job references accept `project/job` or just `job` when the name is unambiguous across all projects.

---

## Configuration

**`~/.config/tschedule/config.yaml`** (created automatically with defaults):

```yaml
dashboard:
  host: 127.0.0.1   # set to 0.0.0.0 to expose on LAN
  port: 8501

db:
  path: ~/.local/share/tschedule/history.db

discovery:
  projects_dir: ~/.config/tschedule/projects.d
```

`--host` and `--port` flags on `tschedule dash` override the config values.

---

## Dashboard

```bash
tschedule dash
# or expose on LAN:
tschedule dash --host 0.0.0.0
```

Opens at `http://localhost:8501` (or the configured port).

Features:
- Jobs grouped by project with schedule, tags, last run status
- Recent runs table with project/status filters
- Per-run log viewer (stdout + stderr)

---

## Auto-reload

When the watcher service is installed (`tschedule install`), any change to a registered `jobs.yaml` or to `~/.config/tschedule/config.yaml` automatically triggers `tschedule reload` within ~2 seconds. No manual daemon restart needed.

Check watcher status:

```bash
systemctl --user status tschedule-watcher.service
```

---

## How it works

```
jobs.yaml  ──► tschedule reload ──► ~/.config/systemd/user/
                                     tschedule-<project>-<job>.timer
                                     tschedule-<project>-<job>.service
                                              │
                                     systemd fires timer
                                              │
                               tschedule _exec <project> <job>
                                              │
                               runs command, captures stdout/stderr
                                              │
                         ~/.local/share/tschedule/history.db
```

Each job generates two systemd units. The `.timer` unit fires on the cron schedule. The `.service` unit calls `tschedule _exec`, which records start time, runs the command with retries if configured, and writes exit code + output to SQLite.

`Persistent=true` on the timer means a missed fire (machine was off) runs on next boot.

---

## File layout

```
~/.config/tschedule/
├── config.yaml                          global config
├── jobs.yaml                            optional global (non-project) jobs
└── projects.d/
    └── my-project.yaml  →  /path/to/my-project/jobs.yaml

~/.config/systemd/user/
├── tschedule-watcher.service
├── tschedule-my-project-nightly-report.service
└── tschedule-my-project-nightly-report.timer

~/.local/share/tschedule/
└── history.db

/path/to/my-project/
└── jobs.yaml                            ← committed to git
```

---

## SQLite schema

```sql
CREATE TABLE jobs (
    id          INTEGER PRIMARY KEY,
    project     TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',   -- JSON array; query with json_each()
    UNIQUE(project, name)
);

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

Query examples:

```sql
-- Jobs with a specific tag
SELECT j.project, j.name FROM jobs j, json_each(j.tags) t WHERE t.value = 'nightly';

-- Failed runs in the last 24 hours
SELECT j.project, j.name, r.started_at, r.exit_code
FROM runs r JOIN jobs j ON j.id = r.job_id
WHERE r.exit_code != 0 AND r.started_at > datetime('now', '-1 day');
```

---

## License

MIT
