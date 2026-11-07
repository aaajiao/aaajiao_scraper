#!/usr/bin/env python3
"""Build and exercise the installed distribution outside the source checkout.

Run with ./.venv/bin/python tools/check_wheel.py. Package installation may use
PyPI; the installed scraper smoke check cannot access network services.
"""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "requirements" / "python315.lock"
UV_PATH = REPO_ROOT / ".venv" / "bin" / "uv"

# Executed by the newly installed interpreter with -I, from a temporary cwd.
# Keep the networking guard ahead of every third-party import, including the
# installed distribution's entry points.
SMOKE_PROGRAM = r'''
import copy
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import sys
import sysconfig

checkout, environment = (Path(value).resolve() for value in sys.argv[1:])
assert sys.flags.isolated == 1, "The wheel check requires isolated Python"
assert Path(sys.prefix).resolve() == environment, "Wrong wheel environment"
assert not Path.cwd().resolve().is_relative_to(checkout), "Smoke cwd must be outside checkout"
for entry in sys.path:
    assert entry and not Path(entry).resolve().is_relative_to(checkout), "Source checkout leaked into sys.path"

attempts = []
def deny_network(*args, **kwargs):
    attempts.append(True)
    raise RuntimeError("Network access is forbidden during installed-wheel verification")

socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network
socket.getaddrinfo = deny_network
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
assert not os.environ.get("FIRECRAWL_API_KEY")
assert not os.environ.get("OPENAI_API_KEY")

from packaging.specifiers import SpecifierSet
import scraper
from scraper import AaajiaoScraper
from scraper.site_order import sort_works_by_website_order

site_packages = Path(sysconfig.get_path("purelib")).resolve()
assert site_packages.is_relative_to(environment), "site-packages is outside the wheel environment"
distribution = importlib.metadata.distribution("aaajiao-scraper")
assert Path(distribution.locate_file("")).resolve() == site_packages
assert SpecifierSet(distribution.metadata["Requires-Python"]) == SpecifierSet(">=3.15")
direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
assert not direct_url.get("dir_info", {}).get("editable"), "An editable install is not a wheel check"
assert "archive_info" in direct_url, "The distribution must be installed from its wheel archive"

entry_points = [entry for entry in distribution.entry_points if entry.group == "console_scripts"]
for entry in entry_points:
    assert callable(entry.load()), f"Console entry point is not loadable: {entry.name}"

works = [
    {
        "title": "Recent Fixture", "title_cn": "近期作品", "year": "2026",
        "type": "video", "duration": "2 min", "materials": "screen",
        "description_en": "A recent bilingual fixture.", "description_cn": "近期测试描述。",
        "url": "https://eventstructure.com/recent-fixture", "images": [],
    },
    {
        "title": "Unlisted Fixture", "title_cn": "未列作品", "year": "1990",
        "type": "installation", "size": "10 cm", "materials": "wood",
        "description_en": "Keep the unlisted work.", "description_cn": "保留未列作品。",
        "url": "https://eventstructure.com/unlisted-fixture", "images": [],
    },
    {
        "title": "Older Fixture", "title_cn": "较早作品", "year": "2001",
        "type": "installation", "size": "20 cm", "materials": "steel",
        "description_en": "Display this older work first.", "description_cn": "较早作品排在前面。",
        "url": "https://eventstructure.com/older-fixture", "images": [],
    },
]
original = copy.deepcopy(works)
ordered = sort_works_by_website_order(works, [works[2]["url"], works[0]["url"]])
expected = [works[2], works[0], works[1]]
assert ordered == expected and works == original

# A local dotenv fixture must not become a credential for the real constructor.
Path(".env").write_text("FIRECRAWL_API_KEY=wheel-check-must-not-load\n", encoding="utf-8")
instance = AaajiaoScraper(use_cache=False)
try:
    assert instance.firecrawl_key is None, "The smoke check loaded dotenv credentials"
    instance.works = ordered
    json_path = Path("exported-works.json").resolve()
    markdown_path = Path("exported-portfolio.md").resolve()
    instance.save_to_json(str(json_path))
    instance.generate_markdown(str(markdown_path), preserve_order=True)
finally:
    instance.session.close()

assert json.loads(json_path.read_text(encoding="utf-8")) == expected
assert "较早作品" in json_path.read_text(encoding="utf-8")
markdown = markdown_path.read_text(encoding="utf-8")
headers = re.findall(r"^### \[([^\]]+)\]\(([^)]+)\)", markdown, re.MULTILINE)
assert headers == [(work["title"], work["url"]) for work in expected], "Markdown order differs from JSON"
for work in expected:
    for field in ("title_cn", "description_en", "description_cn", "materials", "year", "type"):
        assert work[field] in markdown, f"Markdown dropped {field}"
    for field, label in (("size", "Size"), ("duration", "Duration")):
        if field in work:
            assert f"**{label}**: {work[field]}" in markdown
assert works == original, "Export changed the source records"
assert not attempts, "The installed package attempted a network request"
for name, module in tuple(sys.modules.items()):
    if name == "scraper" or name.startswith("scraper."):
        origin = Path(module.__file__).resolve()
        assert origin.is_relative_to(site_packages), f"Imported {name} from outside wheel site-packages: {origin}"
print(f"Installed wheel passed: {scraper.__file__}")
print(f"Requires-Python >=3.15; {len(entry_points)} console entry points loadable; JSON/Markdown contents and order verified")
'''


def clean_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("PYTHON", "PIP_", "UV_", "OPENAI_", "FIRECRAWL_", "AAAJIAO_IMPORTER_"))
        and name != "VIRTUAL_ENV"
    }
    environment.update({
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "UV_PYTHON_DOWNLOADS": "never",
    })
    return environment


def run(command: list[str], *, cwd: Path, environment: dict[str, str], label: str) -> None:
    print(label, flush=True)
    result = subprocess.run(
        command, cwd=cwd, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if result.returncode:
        print(result.stdout[-12000:], file=sys.stderr)
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")
    if label == "Checking the installed wheel outside the checkout...":
        print(result.stdout.strip(), flush=True)


def main() -> None:
    expected_python = (REPO_ROOT / ".python-version").read_text().strip()
    if Path(sys.prefix).resolve() != (REPO_ROOT / ".venv").resolve():
        raise SystemExit("Run this check with ./.venv/bin/python after tools/bootstrap_python.sh.")
    if sys.version.split()[0] != expected_python or sysconfig.get_config_var("Py_GIL_DISABLED"):
        raise SystemExit(f"Expected standard CPython {expected_python}.")
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    if project["build-system"]["requires"] != ["setuptools==84.2.1", "wheel==0.48.0"]:
        raise SystemExit("Review this packaging check when the locked build backend changes.")
    for package, expected in (("setuptools", "84.2.1"), ("wheel", "0.48.0"), ("build", "1.6.1")):
        if importlib.metadata.version(package) != expected:
            raise SystemExit(f"Expected locked build dependency {package}=={expected}.")
    if not UV_PATH.is_file():
        raise SystemExit("Missing project uv; run tools/bootstrap_python.sh first.")

    environment = clean_environment()
    with tempfile.TemporaryDirectory(prefix="aaajiao-wheel-check-") as temporary:
        root = Path(temporary)
        source = root / "source"
        source.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE", "LICENSE.txt", "LICENSE.md", "MANIFEST.in", "setup.cfg", "setup.py"):
            if (REPO_ROOT / name).is_file():
                shutil.copy2(REPO_ROOT / name, source / name)
        shutil.copytree(
            REPO_ROOT / "portfolio_scraper", source / "portfolio_scraper",
            ignore=shutil.ignore_patterns(".env*", ".cache", "__pycache__", "*.pyc", "*.egg-info", "output", "reports"),
        )
        artifacts = root / "artifacts"
        # With neither --wheel nor --sdist, build creates the sdist and then
        # builds the wheel from that sdist, checking its source completeness.
        run(
            [sys.executable, "-I", "-B", "-m", "build", "--no-isolation", "--outdir", str(artifacts), str(source)],
            cwd=root, environment=environment, label="Building sdist and wheel with the locked backend...",
        )
        wheels = list(artifacts.glob("*.whl"))
        sdists = list(artifacts.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError("Expected exactly one built wheel and one sdist.")

        wheel_environment = root / "wheel-env"
        wheel_python = wheel_environment / "bin" / "python"
        run(
            [str(UV_PATH), "--no-config", "venv", "--no-project", "--python", sys.executable, str(wheel_environment)],
            cwd=root, environment=environment, label="Creating an independent wheel environment...",
        )
        run(
            [str(UV_PATH), "--no-config", "pip", "sync", "--python", str(wheel_python),
             "--default-index", "https://pypi.org/simple", "--require-hashes",
             "--build-constraints", str(LOCK_PATH), "--require-build-hashes", str(LOCK_PATH)],
            cwd=root, environment=environment, label="Installing hash-locked wheel dependencies...",
        )
        run(
            [str(UV_PATH), "--no-config", "pip", "install", "--python", str(wheel_python),
             "--no-deps", "--no-index", str(wheels[0])],
            cwd=root, environment=environment, label="Installing the built wheel without editable sources...",
        )
        run(
            [str(wheel_python), "-I", "-m", "pip", "check"],
            cwd=root, environment=environment, label="Checking installed wheel dependencies...",
        )
        smoke_directory = root / "smoke"
        smoke_directory.mkdir()
        run(
            [str(wheel_python), "-I", "-B", "-c", SMOKE_PROGRAM, str(REPO_ROOT), str(wheel_environment)],
            cwd=smoke_directory, environment=environment,
            label="Checking the installed wheel outside the checkout...",
        )
    print("Wheel and sdist check passed; temporary sources, artifacts and environment removed.", flush=True)


if __name__ == "__main__":
    main()
