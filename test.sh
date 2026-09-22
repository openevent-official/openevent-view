#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build"
PYTHON_BIN="${PYTHON:-python3}"
TMP_WORK_DIR="$BUILD_DIR/tmp"

mkdir -p "$TMP_WORK_DIR"

export PYTHONDONTWRITEBYTECODE=1
export PIP_NO_COMPILE=1
export PIP_NO_CACHE_DIR=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export TMPDIR="$TMP_WORK_DIR"

cd "$ROOT_DIR"

"$PYTHON_BIN" -B - <<'PY'
import importlib.metadata
import sys

try:
    from packaging.requirements import Requirement
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
except ImportError as error:
    print(f"missing test dependency: {error.name}; install the declared test extras", file=sys.stderr)
    sys.exit(2)

with open("pyproject.toml", "rb") as stream:
    project = tomllib.load(stream)["project"]
failures = []
for declaration in project["dependencies"] + project["optional-dependencies"]["test"]:
    requirement = Requirement(declaration)
    if requirement.marker and not requirement.marker.evaluate():
        continue
    try:
        version = importlib.metadata.version(requirement.name)
    except importlib.metadata.PackageNotFoundError:
        failures.append(f"{requirement} is not installed")
    else:
        if version not in requirement.specifier:
            failures.append(f"{requirement} is required, found {version}")
if failures:
    print("Python dependencies in the current environment do not meet the package declarations:", file=sys.stderr)
    print("\n".join(f"  {failure}" for failure in failures), file=sys.stderr)
    print("Install the declared dependencies before running tests; tests do not install the SDK.", file=sys.stderr)
    sys.exit(2)
PY

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON_BIN" -B -m unittest discover -s tests -v "$@"

printf 'test artifacts: %s\n' "$BUILD_DIR"
