from __future__ import annotations

import atexit
import fcntl
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

from streamlit.web import bootstrap


APP_NAME = "Focus"
DEFAULT_PORT = 8765
_lock_handle = None


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def user_data_root() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def show_error(message: str) -> None:
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'display alert "{APP_NAME} could not start" '
        f'message "{safe_message}" as critical'
    )
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/_stcore/health"


def app_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def is_healthy(port: int) -> bool:
    try:
        with urlopen(health_url(port), timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def open_when_ready(port: int) -> None:
    for _ in range(120):
        if is_healthy(port):
            if os.getenv("FOCUS_NO_BROWSER") != "1":
                webbrowser.open(app_url(port), new=1)
            return
        time.sleep(0.5)
    logging.error("The Streamlit health endpoint did not become ready.")


def acquire_app_lock(data_root: Path, port_file: Path) -> bool:
    global _lock_handle
    lock_path = data_root / "app.lock"
    _lock_handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        try:
            running_port = int(port_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            running_port = DEFAULT_PORT
        if os.getenv("FOCUS_NO_BROWSER") != "1":
            webbrowser.open(app_url(running_port), new=1)
        return False


def main() -> None:
    data_root = user_data_root()
    database_dir = data_root / "data"
    logs_dir = data_root / "logs"
    database_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=logs_dir / "launcher.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    port_file = data_root / "active-port.txt"
    if not acquire_app_lock(data_root, port_file):
        return

    port = int(os.getenv("FOCUS_PORT", str(DEFAULT_PORT)))
    if is_healthy(port):
        raise OSError(f"Port {port} is already in use by another application.")

    os.environ["FOCUS_DB_PATH"] = str(database_dir / "focus.db")
    os.environ["FOCUS_DESKTOP"] = "1"
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    port_file.write_text(str(port), encoding="utf-8")

    def clean_port_file() -> None:
        try:
            port_file.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(clean_port_file)
    root = bundle_root()
    app_script = root / "app.py"
    if not app_script.exists():
        raise FileNotFoundError("The packaged application files are incomplete.")

    os.chdir(root)
    threading.Thread(target=open_when_ready, args=(port,), daemon=True).start()
    logging.info("Starting Focus on port %s", port)
    streamlit_options = {
        "global.developmentMode": False,
        "server.address": "127.0.0.1",
        "server.port": port,
        "server.headless": True,
        "server.fileWatcherType": "none",
        "server.runOnSave": False,
        "browser.gatherUsageStats": False,
        "client.toolbarMode": "minimal",
    }
    bootstrap.load_config_options(streamlit_options)
    bootstrap.run(str(app_script), False, [], streamlit_options)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("Focus failed to start")
        show_error(
            f"Focus could not start.\n\n{exc}\n\n"
            f"Details are in {user_data_root() / 'logs' / 'launcher.log'}"
        )
        raise SystemExit(1) from exc
