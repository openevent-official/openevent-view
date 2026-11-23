PYTHON ?= python3
unexport PYTHONPATH PYTHONHOME
export PYTHONDONTWRITEBYTECODE = 1
export PIP_NO_COMPILE = 1
export PIP_NO_CACHE_DIR = 1
export PIP_DISABLE_PIP_VERSION_CHECK = 1
export TMPDIR := $(CURDIR)/build/tmp

.PHONY: help build install clean

help:
	@echo 'Usage: make build | install | clean [PYTHON=/path/to/python]'

build install:
	"$(PYTHON)" -B scripts/build.py $@

clean:
	rm -rf build/tmp
	rm -f dist/openevent_view-*.whl dist/openevent_view-*.tar.gz
