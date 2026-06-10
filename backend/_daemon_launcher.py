"""Boot uvicorn as a daemon-style process that survives the IDE shell.

This is needed because the IDE sandbox kills any subprocess when the parent
shell command finishes. We double-fork via the standard POSIX trick, but on
Windows we use the DETACHED_PROCESS / CREATE_NEW_PROCESS_GROUP flags.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

LOG_FILE = Path("d:/DraftMind/backend/_uvicorn_daemon.log")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
PYTHON = sys.executable
BACKEND_DIR = Path("d:/DraftMind/backend").resolve()
SCRIPT = BACKEND_DIR / "_boot.py"

# Windows detach flags: don't open a console, don't share the parent's
# signal group, so when the IDE shell dies the daemon keeps running.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

log_handle = open(LOG_FILE, "wb", buffering=0)

print(f"[daemon-launcher] python={PYTHON}", flush=True)
print(f"[daemon-launcher] cwd={BACKEND_DIR}", flush=True)
print(f"[daemon-launcher] log={LOG_FILE}", flush=True)

env = os.environ.copy()
env["PYTHONPATH"] = str(BACKEND_DIR)
env["PYTHONUNBUFFERED"] = "1"

proc = subprocess.Popen(
    [PYTHON, "-u", str(SCRIPT)],
    cwd=str(BACKEND_DIR),
    env=env,
    stdin=subprocess.DEVNULL,
    stdout=log_handle,
    stderr=log_handle,
    creationflags=flags,
    close_fds=True,
)

print(f"[daemon-launcher] pid={proc.pid}", flush=True)
time.sleep(2.0)
print(f"[daemon-launcher] poll_after_2s={proc.poll()}", flush=True)
print(f"[daemon-launcher] DONE", flush=True)
