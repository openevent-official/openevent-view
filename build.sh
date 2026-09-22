#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build"
OUT_DIR="$ROOT_DIR/dist"
PYTHON_BIN="${PYTHON:-python3}"
BUILD_DEPS_DIR="$BUILD_DIR/build-deps"
TMP_WORK_DIR="$BUILD_DIR/tmp"

rm -rf "$BUILD_DEPS_DIR" "$TMP_WORK_DIR"
rm -f "$OUT_DIR"/openevent_view-*.whl "$OUT_DIR"/openevent_view-*.tar.gz
mkdir -p "$BUILD_DEPS_DIR" "$OUT_DIR" "$TMP_WORK_DIR"

export PYTHONDONTWRITEBYTECODE=1
export PIP_NO_COMPILE=1
export PIP_NO_CACHE_DIR=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export TMPDIR="$TMP_WORK_DIR"

"$PYTHON_BIN" -B -m pip install -q --target "$BUILD_DEPS_DIR" build
export PYTHONPATH="$BUILD_DEPS_DIR${PYTHONPATH:+:$PYTHONPATH}"

cd "$ROOT_DIR"

"$PYTHON_BIN" -B -m build --wheel --outdir "$OUT_DIR"

printf 'build artifacts: %s\n' "$OUT_DIR"
