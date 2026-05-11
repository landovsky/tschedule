"""Internal executor: run a job and record results to SQLite.

Called by systemd via:  tschedule _exec <project> <job>
"""
from __future__ import annotations

import subprocess
import sys
import time

from .config import JobConfig, load_global_config, discover_all_jobs
from .db import DB


def run_job(job: JobConfig, db: DB) -> tuple[int, str, str]:
    """Execute a job command, record to DB, return (exit_code, stdout, stderr).

    This is the testable core: no sys.exit, no config loading.
    """
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
    return exit_code, stdout_text, stderr_text


def _try_notify(cfg, db: DB, job, exit_code: int, elapsed: float,
                 stdout_text: str, stderr_text: str, run_id: int, job_id: int) -> None:
    """Send Telegram notification if policy requires it. Never raises."""
    from .notify import should_notify, format_message, send_telegram

    if not cfg.telegram.bot_token or not cfg.telegram.chat_id:
        return

    prev_exit_code = db.get_previous_exit_code(job_id, run_id)
    if not should_notify(job.notify, exit_code, prev_exit_code):
        return

    try:
        msg = format_message(job.project, job.name, exit_code, elapsed, stdout_text, stderr_text)
        send_telegram(cfg.telegram.bot_token, cfg.telegram.chat_id, msg)
    except Exception as exc:
        print(f"tschedule: telegram notification failed: {exc}", file=sys.stderr)


def exec_job(project: str, job_name: str) -> None:
    cfg = load_global_config()
    db = DB(cfg.db_path)

    jobs = discover_all_jobs(cfg)
    job = next((j for j in jobs if j.project == project and j.name == job_name), None)
    if job is None:
        print(f"tschedule: job not found: {project}/{job_name}", file=sys.stderr)
        sys.exit(1)

    t0 = time.monotonic()
    print(f"tschedule: starting {project}/{job_name}", file=sys.stderr)

    job_id = db.get_job_id(project, job_name) or db.upsert_job(project, job_name, job.description, job.tags)
    exit_code, stdout_text, stderr_text = run_job(job, db)

    elapsed = time.monotonic() - t0
    status = "ok" if exit_code == 0 else f"failed (exit {exit_code})"
    print(f"tschedule: finished {project}/{job_name} — {status} in {elapsed:.1f}s", file=sys.stderr)

    if exit_code != 0:
        if stderr_text:
            print(stderr_text, file=sys.stderr)

    # Get run_id for notification (the most recent run for this job)
    runs = db.get_run_history(job_id, limit=1)
    run_id = runs[0]['id'] if runs else 0
    _try_notify(cfg, db, job, exit_code, elapsed, stdout_text, stderr_text, run_id, job_id)

    sys.exit(exit_code)
