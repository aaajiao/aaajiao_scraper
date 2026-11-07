# Python environment and rebuilds

The development interpreter, Streamlit GUI, CI, and newly built macOS helper use
standard, GIL-enabled **CPython 3.15.2**, pinned in `.python-version`. The package
requires Python 3.15 or later. Free-threaded Python is not part of this lock or the
macOS wheelhouse.

## Development environment

Install CPython 3.15.2 and native build prerequisites, then run from a checkout:

```bash
./tools/bootstrap_python.sh
./start_gui.command
```

The bootstrap script always creates or synchronizes this checkout's `.venv`.
It verifies the interpreter before modifying dependencies and refuses an existing
environment with a different Python version. To rebuild, move the old `.venv`
outside the checkout first and run the same command. An alternate interpreter can
be selected with `PYTHON_BIN`, but it must still be CPython 3.15.2.

Some pinned libraries are built from source on Python 3.15. macOS needs Xcode
Command Line Tools and Rust/Cargo; Ubuntu needs a C/C++ compiler, `pkg-config`,
JPEG/zlib headers, and Rust/Cargo. The native dependency builds were verified with
Rust 1.99.1; CI selects that toolchain explicitly. No Homebrew library paths are
embedded in the macOS helper runtime.

The bootstrap first installs the hash-checked installer tools, then uses pinned
uv 0.13.7 to synchronize the full environment with distribution hash checking and
build-dependency hash checking. The editable project is installed without resolving
additional dependencies or creating an unpinned build environment.

## Dependency records

| File | Purpose |
| --- | --- |
| `.python-version` | Exact interpreter patch version |
| `pyproject.toml` | Package metadata, supported Python minimum, dependency declarations, pinned project build backend |
| `requirements/bootstrap.in` / `.lock` | Installer versions and distribution hashes |
| `requirements/python315.in` | Reviewed runtime, test, quality, and native-build version constraints |
| `requirements/python315.lock` | Complete platform-marked dependency resolution with SHA-256 hashes; also used as build constraints |
| `macos/Build/python_runtime_manifest.json` | Independent macOS interpreter archive, target, version, and SHA-256 |
| `macos/Build/wheelhouse_requirements.txt` | Separate minimal helper dependency set for CPython 3.15 |
| `macos/Build/native_wheel_sources.json` | Pinned source inputs for native helper wheels unavailable upstream |

The development lock includes the default package dependencies and `[dev]`, not
the optional `[async]`, `[config]`, or `[docs]` extras. Optional extras need their own
reviewed resolution and verification before being added to the standard environment.
Hashes pin upstream distributions; compiling a source distribution also depends on
the documented OS toolchain, so these records do not promise identical native binary
bytes across operating systems.

To intentionally update dependencies, edit the reviewed inputs and regenerate:

```bash
./tools/lock_python.sh
./tools/bootstrap_python.sh
./.venv/bin/python tools/run_tests.py
./.venv/bin/python tools/check_gui.py
./.venv/bin/python tools/check_wheel.py
```

Review both lock-file changes and test results before committing. Do not substitute
`pip freeze` output containing an editable checkout path. The initial 3.15 migration
retains the verified application-library versions, including NumPy 2.4.3, pandas
2.3.3, and Pillow 12.1.1. PyArrow 26.0.1, rpds-py 2026.9.1, Pydantic 2.13.5, and
pydantic-core 2.46.5 replace versions that blocked the original migration. Ruff,
Black, MyPy, and their required tooling dependencies were updated for Python 3.15.

## Verification

```bash
./.venv/bin/python -m pip check
./.venv/bin/python tools/check_environment.py
./.venv/bin/python tools/run_tests.py
./.venv/bin/python tools/check_gui.py
./.venv/bin/python tools/check_wheel.py
```

`run_tests.py` blocks outbound Python connections, limits Git transport to local
files, and disables credentials and dotenv loading. The full suite includes the
Python scraper and macOS helper tests. Helper tests construct their own temporary
seed from tracked source files; a fresh checkout does not need an existing app,
`macos/Seed`, `macos/Vendor/python_snapshot`, or Xcode to run them. Existing sitemap
XML-as-HTML warnings remain visible.

`check_gui.py` executes the actual Streamlit page with temporary artwork fixtures,
checks filtering and displayed columns, then starts the launcher from outside the
checkout and verifies its loopback health endpoint. It stops its own server on
success and failure and does not scrape or publish anything.

`check_wheel.py` builds with the locked backend, installs the wheel into a separate
environment, and executes the public Python API from outside the source tree.
The former `aaajiao-scraper = scraper.cli:main` declaration pointed to a nonexistent
module and has been removed. The supported interfaces are the Streamlit launcher
from a checkout and the installed `scraper` Python package; no standalone console
command is advertised.

Ruff configuration lives only in `.ruff.toml`; Black and MyPy configuration remain
in `pyproject.toml`. All target Python 3.15. Existing code-style debt is separate
from this migration; CI checks fatal syntax/name errors rather than reformatting
unrelated code.

## macOS helper

The app does not copy the development `.venv` or load the machine's Homebrew/Xcode
Python. Its build downloads a pinned, hash-verified standalone CPython 3.15.2 and
installs the separately pinned CPython 3.15 wheels. Follow
[`macos/README.md`](macos/README.md) and the
[release checklist](macos/Build/RELEASE_CHECKLIST.md) for rebuilding and verifying
the relocated bundle, native dependencies, signature, and publication transactions.

Changing the development lock alone does not update the helper wheelhouse. Changes
to shared runtime dependencies must be reviewed against both records. Building into
`dist/` is a validation step; installing an app or publishing a release is separate.
