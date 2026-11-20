#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
unset PYTHONPATH PYTHONHOME
export PYTHONDONTWRITEBYTECODE=1
export PIP_NO_COMPILE=1
export PIP_NO_CACHE_DIR=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export TMPDIR="$PWD/build/tmp"

exec "${PYTHON:-python3}" -B scripts/install.py "$@"
