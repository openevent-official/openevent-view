PYTHON ?= python3
TEST_ARGS ?=
INSTALL_ARGS ?=

.PHONY: help build install test clean

help:
	@printf 'Usage: make <target>\n\n'
	@printf 'Targets:\n'
	@printf '  build    Build artifacts without installing into the current Python environment\n'
	@printf '  install  Build and install the generated wheel with pip\n'
	@printf '  test     Run unit tests with dependencies from the current Python environment\n'
	@printf '  clean    Remove dist artifacts and temporary work files\n\n'
	@printf 'Variables:\n'
	@printf '  PYTHON=%s\n' '$(PYTHON)'
	@printf '  INSTALL_ARGS=%s\n' '$(INSTALL_ARGS)'
	@printf '\nExamples:\n'
	@printf '  make install INSTALL_ARGS="--target /opt/openevent-view"\n'

build:
	PYTHON="$(PYTHON)" ./build.sh

install: build
	@wheel="$$(find "dist" -maxdepth 1 -type f -name '*.whl' | sort | tail -n 1)"; \
	if [ -z "$$wheel" ]; then \
	  printf 'no wheel found in dist\n'; \
	  exit 1; \
	fi; \
	"$(PYTHON)" -m pip install $(INSTALL_ARGS) "$$wheel"

test:
	PYTHON="$(PYTHON)" ./test.sh $(TEST_ARGS)

clean:
	rm -rf build dist
