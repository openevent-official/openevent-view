#!/usr/bin/env bash
set -euo pipefail

# Run through `make e2e`; its build prerequisite supplies the current wheel.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
E2E_DIR="$ROOT_DIR/build/e2e"
E2E_SITE="$E2E_DIR/site"
SERVER_BIN="${OPENEVENT_SERVER_BIN:-}"

if [ -z "$SERVER_BIN" ] || [ ! -x "$SERVER_BIN" ]; then
  printf 'Set OPENEVENT_SERVER_BIN to the server executable from a successful current build.\n' >&2
  exit 2
fi
if [[ "$SERVER_BIN" != /* ]]; then SERVER_BIN="$PWD/$SERVER_BIN"; fi

shopt -s nullglob
wheels=("$ROOT_DIR"/dist/openevent_view-*.whl)
if [ "${#wheels[@]}" -ne 1 ]; then
  printf 'Expected exactly one current View wheel; run make e2e to build it first.\n' >&2
  exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
export PIP_NO_COMPILE=1
export PIP_NO_CACHE_DIR=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export TMPDIR="$E2E_DIR/tmp"
unset PYTHONPATH

# Preserve a selected virtual environment (and relative interpreter paths) after
# changing directories. Resolving the executable symlink would lose its venv.
PYTHON_BIN="$("$PYTHON_BIN" -B -c 'import sys; print(sys.executable)')"

# Clean this run's outputs, leaving any previously selected test venv intact.
rm -rf "$E2E_SITE" "$E2E_DIR/run" "$E2E_DIR/tmp"
mkdir -p "$E2E_DIR/tmp"

# Check dependencies already installed in the selected environment. Never install
# the SDK, generate its protobuf code, or add its source directory to sys.path.
"$PYTHON_BIN" -B - "${wheels[0]}" <<'PY'
from email.parser import Parser
import importlib.metadata
import sys
from zipfile import ZipFile

try:
    from packaging.requirements import Requirement
except ImportError:
    raise SystemExit("e2e requires installed packaging; install the declared test extras")

with ZipFile(sys.argv[1]) as wheel:
    metadata_files = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
    if len(metadata_files) != 1:
        raise SystemExit("View wheel must contain exactly one package metadata file")
    metadata = Parser().parsestr(wheel.read(metadata_files[0]).decode("utf-8"))

for declaration in metadata.get_all("Requires-Dist", []):
    requirement = Requirement(declaration)
    if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
        continue
    try:
        installed = importlib.metadata.version(requirement.name)
    except importlib.metadata.PackageNotFoundError:
        raise SystemExit(f"e2e requires already installed {requirement}; dependencies are not installed by this test")
    if installed not in requirement.specifier:
        raise SystemExit(f"e2e requires {requirement}; current environment contains {installed}")

from openevent.sdk import AdminClient, OpenEventClient
PY

# Isolate only View. A nested venv would inherit the base interpreter's packages,
# not packages installed in the selected virtual environment.
"$PYTHON_BIN" -B -m pip install --no-deps --force-reinstall --target "$E2E_SITE" "${wheels[0]}" >"$E2E_DIR/install.log" 2>&1
export PYTHONPATH="$E2E_SITE"
export OPENEVENT_SERVER_BIN="$SERVER_BIN"
export OPENEVENT_VIEW_E2E=1
export OPENEVENT_VIEW_E2E_DIR="$E2E_DIR"
export OPENEVENT_VIEW_E2E_SITE="$E2E_SITE"
cd "$E2E_DIR"
"$PYTHON_BIN" -B "$ROOT_DIR/tests/test_e2e.py" -v "$@"
printf 'e2e artifacts: %s\n' "$E2E_DIR"
