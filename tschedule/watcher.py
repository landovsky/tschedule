"""File watcher daemon — monitors jobs.yaml files and auto-reloads on change.

Run as a systemd user service:  tschedule watch
Install via:                     tschedule install
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _Handler(FileSystemEventHandler):
    _last: float = 0.0

    def on_any_event(self, event):
        if event.is_directory:
            return
        src = getattr(event, 'src_path', '')
        if src.endswith(('jobs.yaml', 'config.yaml')):
            now = time.monotonic()
            if now - self._last > 2.0:
                self._last = now
                print(f"tschedule-watch: change detected in {src}, reloading…",
                      flush=True)
                subprocess.run(['tschedule', 'reload'], check=False)


def watch() -> None:
    from .config import load_global_config, CONFIG_DIR

    cfg = load_global_config()
    handler = _Handler()
    observer = Observer()

    # Watch the tschedule config dir
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    observer.schedule(handler, str(CONFIG_DIR), recursive=True)

    # Also watch each registered project directory
    if cfg.projects_dir.exists():
        watched: set[str] = set()
        for link in cfg.projects_dir.iterdir():
            if link.is_symlink():
                target = Path(os.readlink(link))
                if not target.is_absolute():
                    target = (link.parent / target).resolve()
            else:
                target = link
            parent = str(target.parent)
            if parent not in watched and target.parent.exists():
                observer.schedule(handler, parent, recursive=False)
                watched.add(parent)

    observer.start()
    print("tschedule-watch: watching for changes. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
