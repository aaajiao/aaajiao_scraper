"""Run repository tests without network credentials or outbound connections."""

import os
from pathlib import Path
import socket
import sys


def block_connection(*args, **kwargs):
    raise RuntimeError("Network access is disabled for repository tests")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    for name in ("OPENAI_API_KEY", "FIRECRAWL_API_KEY", "AAAJIAO_IMPORTER_SITE_ORDER_FILE"):
        os.environ.pop(name, None)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["GIT_ALLOW_PROTOCOL"] = "file"
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    socket.socket.connect = block_connection
    socket.socket.connect_ex = block_connection
    socket.create_connection = block_connection
    import pytest

    return pytest.main(sys.argv[1:] or ["portfolio_scraper/tests", "tests", "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
