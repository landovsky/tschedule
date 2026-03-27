"""Streamlit dashboard — launched by `tschedule dash`.

Do not run directly; use: tschedule dash
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Prague")

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from tschedule.config import load_global_config, discover_all_jobs
from tschedule.db import DB


def _fmt_dt(s: str | None) -> str:
    if not s:
        return "—"
    try:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc).astimezone(TZ)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return s[:16] if s else "—"


def _duration(start: str | None, end: str | None) -> str:
    if not start or not end:
        return "—"
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        secs = (e - s).total_seconds()
        return f"{secs:.0f}s" if secs < 60 else f"{secs / 60:.1f}m"
    except Exception:
        return "—"


def main():
    st.set_page_config(page_title="tschedule", page_icon="⏰", layout="wide")
    st.title("⏰ tschedule")

    cfg = load_global_config()
    db = DB(cfg.db_path)
    jobs_cfg = {(j.project, j.name): j for j in discover_all_jobs(cfg)}
    db_jobs = db.get_all_jobs_with_stats()

    if not db_jobs:
        st.info("No jobs registered yet. Run `tschedule reload` to populate.")
        return

    # Aggregate by project
    projects: dict[str, list] = {}
    for row in db_jobs:
        projects.setdefault(row['project'], []).append(row)

    for project, pjobs in projects.items():
        st.subheader(f"📁 {project}")
        rows = []
        for j in pjobs:
            tags = json.loads(j['tags'] or '[]')
            cfg_job = jobs_cfg.get((j['project'], j['name']))
            schedule = cfg_job.schedule if cfg_job else "—"
            status = (
                "✅ ok" if j['last_exit_code'] == 0
                else "❌ failed" if j['last_exit_code'] is not None
                else "— never run"
            )
            rows.append({
                "Job":         j['name'],
                "Schedule":    schedule,
                "Tags":        ", ".join(tags),
                "Last run":    _fmt_dt(j['last_run']),
                "Status":      status,
                "Errors (7d)": int(j['errors_7d'] or 0),
                "Total runs":  int(j['total_runs'] or 0),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Recent runs")

    col_filter, col_status = st.columns([3, 1])
    with col_filter:
        project_filter = st.selectbox(
            "Project", ["(all)"] + sorted(projects.keys()), index=0
        )
    with col_status:
        status_filter = st.selectbox("Status", ["(all)", "success", "failed"], index=0)

    all_runs = db.get_all_runs(limit=500)
    run_rows = []
    for r in all_runs:
        if project_filter != "(all)" and r['project'] != project_filter:
            continue
        if status_filter == "success" and r['exit_code'] != 0:
            continue
        if status_filter == "failed" and r['exit_code'] == 0:
            continue
        run_rows.append({
            "Project":  r['project'],
            "Job":      r['job_name'],
            "Tags":     r['tags'],
            "Started":  _fmt_dt(r['started_at']),
            "Duration": _duration(r['started_at'], r['finished_at']),
            "Exit":     r['exit_code'],
        })

    if run_rows:
        st.dataframe(run_rows, use_container_width=True, hide_index=True)

        # Expandable log viewer
        st.divider()
        st.subheader("Log viewer")
        run_labels = [
            f"{r['started_at'][:16]}  {r['project']}/{r['job_name']}  (exit {r['exit_code']})"
            for r in all_runs[:100]
        ]
        if run_labels:
            idx = st.selectbox("Select run", range(len(run_labels)),
                               format_func=lambda i: run_labels[i])
            selected = all_runs[idx]
            col_out, col_err = st.columns(2)
            with col_out:
                st.caption("stdout")
                st.code(selected['stdout'] or "(empty)", language="text")
            with col_err:
                st.caption("stderr")
                st.code(selected['stderr'] or "(empty)", language="text")
    else:
        st.info("No runs match the selected filters.")


if __name__ == "__main__":
    main()
