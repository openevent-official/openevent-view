PYTHON ?= python3
NODE ?= node
TEST_ARGS ?=
INSTALL_ARGS ?=
DOC_ROOT ?= .
OPENEVENT_SERVER_BIN ?=

.PHONY: help build install test test-python test-frontend e2e check-docs clean

help:
	@printf 'Usage: make <target>\n\n'
	@printf 'Targets:\n'
	@printf '  build    Build artifacts without installing into the current Python environment\n'
	@printf '  install  Build and install the generated wheel with pip\n'
	@printf '  test     Run Python and frontend tests with installed dependencies\n'
	@printf '  test-python   Run Python tests with installed dependencies\n'
	@printf '  test-frontend Run frontend tests (requires Node.js 18 or newer)\n'
	@printf '  e2e           Build View and test with an explicitly selected OpenEvent server\n'
	@printf '  check-docs    Check documentation links and translation structure\n'
	@printf '  clean    Remove dist artifacts and temporary work files\n\n'
	@printf 'Variables:\n'
	@printf '  PYTHON=%s\n' '$(PYTHON)'
	@printf '  INSTALL_ARGS=%s\n' '$(INSTALL_ARGS)'
	@printf '  OPENEVENT_SERVER_BIN=%s\n' '$(OPENEVENT_SERVER_BIN)'
	@printf '\nExamples:\n'
	@printf '  make install PYTHON=/opt/openevent-view/bin/python\n'
	@printf '  make e2e OPENEVENT_SERVER_BIN=/path/to/current/build/openevent_server\n'

build:
	PYTHON="$(PYTHON)" ./build.sh

install: build
	PYTHONDONTWRITEBYTECODE=1 "$(PYTHON)" scripts/install.py $(INSTALL_ARGS)

test:
	$(MAKE) test-python
	$(MAKE) test-frontend

test-python:
	PYTHON="$(PYTHON)" ./test.sh $(TEST_ARGS)

test-frontend:
	@command -v "$(NODE)" >/dev/null 2>&1 || { printf 'Frontend tests require Node.js 18 or newer; set NODE to its executable.\n' >&2; exit 1; }
	"$(NODE)" --test tests/test_frontend.js

e2e: build
	PYTHON="$(PYTHON)" OPENEVENT_SERVER_BIN="$(OPENEVENT_SERVER_BIN)" ./test-e2e.sh $(TEST_ARGS)

check-docs:
	PYTHONDONTWRITEBYTECODE=1 "$(PYTHON)" tests/check_docs.py "$(DOC_ROOT)"

clean:
	rm -rf build dist
