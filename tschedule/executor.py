"""Internal executor: run a job and record results to SQLite.

Called by systemd via:  tschedule _exec <project> <job>
"""
from __future__ import annotations

import subprocess
import sys

from .config import load_global_config, discover_all_jobs
from .db import DB


def exec_job(project: str, job_name: str) -> None:
    cfg = load_global_config()
    db = DB(cfg.db_path)

    jobs = discover_all_jobs(cfg)
    job = next((j for j in jobs if j.project == project and j.name == job_name), None)
    if job is None:
        print(f"tschedule: job not found: {project}/{job_name}", file=sys.stderr)
        sys.exit(1)

    job_id = db.upsert_job(job.project, job.name, job.description, job.tags)
    run_id = db.start_run(job_id)

    exit_code = 1
    stdout_text = ""
    stderr_text = ""

    for attempt in range(max(1, job.retries + 1)):
        try:
            result = subprocess.run(
                job.command,
                shell=True,
                cwd=job.working_dir or None,
                capture_output=True,
                text=True,
                timeout=job.timeout,
            )
            exit_code = result.returncode
            stdout_text = result.stdout
            stderr_text = result.stderr
            if exit_code == 0:
                break
            if attempt < job.retries:
                print(f"tschedule: attempt {attempt + 1} failed (exit {exit_code}), retrying…",
                      file=sys.stderr)
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stderr_text = f"Timeout after {job.timeout}s"
            stdout_text = (exc.stdout or b"").decode(errors='replace')
            break
        except Exception as exc:
            exit_code = 1
            stderr_text = str(exc)
            break

    db.finish_run(run_id, exit_code, stdout_text, stderr_text)

    if exit_code != 0:
        print(f"tschedule: {project}/{job_name} failed (exit {exit_code})", file=sys.stderr)
        if stderr_text:
            print(stderr_text, file=sys.stderr)

    sys.exit(exit_code)
