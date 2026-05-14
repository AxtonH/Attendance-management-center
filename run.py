"""Dev launcher: start backend + frontend, open the dashboard.

Usage (from repo root):
    python run.py

Ctrl+C stops both.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
IS_WINDOWS = os.name == "nt"


def backend_python() -> Path:
    return (
        BACKEND_DIR / ".venv" / ("Scripts" if IS_WINDOWS else "bin") /
        ("python.exe" if IS_WINDOWS else "python")
    )


def find_npm() -> str:
    """Locate npm as an absolute path so we don't need shell=True."""
    exe = shutil.which("npm.cmd") if IS_WINDOWS else shutil.which("npm")
    if not exe:
        sys.exit("error: npm not found on PATH.")
    return exe


def kill(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        return
    print(f"[run] stopping {name}…")
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    if not backend_python().exists():
        sys.exit(f"error: backend venv missing at {backend_python()}")
    if not (FRONTEND_DIR / "node_modules").exists():
        sys.exit("error: frontend/node_modules missing. Run `npm install` in frontend/.")
    if not (REPO_ROOT / ".env").exists():
        print("warning: .env missing — backend will fail to reach Supabase.", file=sys.stderr)

    print("[run] starting backend on http://localhost:8000")
    backend = subprocess.Popen(
        [str(backend_python()), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=BACKEND_DIR,
    )

    print("[run] starting frontend on http://localhost:3000")
    frontend = subprocess.Popen(
        [find_npm(), "run", "dev"],
        cwd=FRONTEND_DIR,
    )

    # Give Next.js time to bind the port before opening the browser.
    time.sleep(6)
    print("[run] opening http://localhost:3000")
    webbrowser.open("http://localhost:3000")
    print("[run] running. Ctrl+C to stop.")

    try:
        while True:
            if backend.poll() is not None:
                print("[run] backend exited.")
                break
            if frontend.poll() is not None:
                print("[run] frontend exited.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print()
    finally:
        kill(frontend, "frontend")
        kill(backend, "backend")
    return 0


if __name__ == "__main__":
    sys.exit(main())
