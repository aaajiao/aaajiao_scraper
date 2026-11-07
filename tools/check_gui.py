#!/usr/bin/env python3
"""Check the real Streamlit page and launcher without live services or user data.

Run with the project interpreter: ./.venv/bin/python tools/check_gui.py
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "portfolio_scraper" / "app.py"

# This applies the same network boundary to the separately launched server. It
# does not change machine networking or any user's Python installation.
LOOPBACK_GUARD = '''\
import ipaddress
import socket

def allowed(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False

def require_loopback(address):
    if not isinstance(address, tuple) or not allowed(address[0]):
        raise OSError("External network disabled during GUI verification")

original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
original_getaddrinfo = socket.getaddrinfo

def connect(self, address):
    require_loopback(address)
    return original_connect(self, address)

def connect_ex(self, address):
    require_loopback(address)
    return original_connect_ex(self, address)

def getaddrinfo(host, *args, **kwargs):
    if host is not None and not allowed(host):
        raise OSError("External DNS disabled during GUI verification")
    return original_getaddrinfo(host, *args, **kwargs)

socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.getaddrinfo = getaddrinfo
'''


def check_page(root: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "portfolio_scraper"))
    from streamlit.testing.v1 import AppTest

    import scraper.paths as paths

    works = [
        {
            "title": "Fixture Installation", "title_cn": "测试装置",
            "type": "installation", "year": "2026", "size": "10 cm",
            "url": "https://eventstructure.com/fixture-installation", "images": [],
        },
        {
            "title": "Fixture Video", "title_cn": "测试影像",
            "type": "video", "year": "2025", "duration": "2 min",
            "url": "https://eventstructure.com/fixture-video", "images": [],
        },
    ]
    works_path = root / "works.json"
    works_path.write_text(json.dumps(works, ensure_ascii=False), encoding="utf-8")
    markdown_path = root / "portfolio.md"
    markdown_path.write_text("# GUI fixture\n", encoding="utf-8")
    network_attempts = []

    def block_network(*args, **kwargs):
        network_attempts.append(True)
        raise AssertionError("Network access is forbidden in the page check")

    with contextlib.ExitStack() as stack:
        for name, value in {
            "WORKS_JSON_PATH": works_path,
            "PORTFOLIO_MARKDOWN_PATH": markdown_path,
            "OUTPUT_DIR": root / "output",
            "REPORTS_DIR": root / "reports",
        }.items():
            stack.enter_context(patch.object(paths, name, value))
        stack.enter_context(patch.dict(os.environ, {
            "PYTHON_DOTENV_DISABLED": "1", "FIRECRAWL_API_KEY": "", "OPENAI_API_KEY": "",
        }))
        stack.enter_context(patch("scraper.core.load_dotenv", return_value=False))
        stack.enter_context(patch.object(socket.socket, "connect", block_network))
        stack.enter_context(patch.object(socket.socket, "connect_ex", block_network))
        stack.enter_context(patch.object(socket, "getaddrinfo", block_network))

        app = AppTest.from_file(APP_PATH, default_timeout=20).run()
        assert not app.exception, app.exception
        assert not app.error, app.error
        assert app.title[0].value == "🎨 aaajiao 作品集抓取工具"
        assert app.metric[0].value == "2"
        assert len(app.dataframe[0].value) == 2
        assert len(app.get("download_button")) == 2

        app.selectbox[0].select("Video (1)").run()
        assert not app.exception, app.exception
        assert len(app.dataframe[0].value) == 1
        assert app.dataframe[0].value.iloc[0]["标题"] == "Fixture Video"

        app.multiselect[0].set_value(["title", "year"]).run()
        assert not app.exception, app.exception
        assert list(app.dataframe[0].value.columns) == ["标题", "年份"]
        assert not app.error, app.error
        assert not network_attempts, "The page attempted unexpected network access"
    print("GUI page passed: rendering, downloads, filtering and column selection", flush=True)


def stop_server(process: subprocess.Popen) -> None:
    # start_new_session isolates this process group from the invoking terminal.
    # Kill the group even if the launcher exits, so a non-exec launcher cannot
    # leave its server child running after an unsuccessful check.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def check_launcher(root: Path) -> None:
    guard = root / "network-guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(LOOPBACK_GUARD, encoding="utf-8")
    environment = dict(os.environ)
    environment.update({
        "PYTHONPATH": str(guard),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    })
    for key in ("FIRECRAWL_API_KEY", "OPENAI_API_KEY"):
        environment.pop(key, None)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [
        str(REPO_ROOT / "start_gui.command"),
        "--server.address=127.0.0.1", f"--server.port={port}",
        "--server.headless=true", "--browser.gatherUsageStats=false",
    ]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (root / "server.log").open("w+", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=root, env=environment,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"GUI launcher exited with status {process.returncode}")
                try:
                    with opener.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                        healthy = response.status == 200 and response.read().strip() == b"ok"
                    if healthy and process.poll() is None:
                        print("GUI launcher passed: forwarded arguments and health from another directory", flush=True)
                        break
                except (urllib.error.URLError, TimeoutError, OSError):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("GUI launcher did not become healthy within 30 seconds")
        except BaseException:
            log.flush()
            log.seek(0)
            print(log.read()[-6000:], file=sys.stderr)
            raise
        finally:
            stop_server(process)
    print("GUI server stopped", flush=True)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="aaajiao-gui-check-") as temporary:
        root = Path(temporary)
        check_page(root)
        check_launcher(root)


if __name__ == "__main__":
    main()
