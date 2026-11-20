PYTHON ?= python3
INSTALL_ARGS ?=
unexport PYTHONPATH PYTHONHOME
export PYTHON

.PHONY: help build install clean

help:
	@printf 'Usage: make <target>\n\n'
	@printf 'Targets:\n'
	@printf '  build    Build artifacts without installing into the current Python environment\n'
	@printf '  install  Build and install the generated wheel with pip\n'
	@printf '  clean    Remove View release packages and temporary files\n\n'
	@printf 'Variables:\n'
	@printf '  PYTHON=%s\n' '$(PYTHON)'
	@printf '  INSTALL_ARGS=%s\n' '$(INSTALL_ARGS)'
	@printf '\nExample:\n'
	@printf '  make install PYTHON=/opt/openevent-view/bin/python\n'

build:
	./build.sh

install:
	./build.sh install $(INSTALL_ARGS)

clean:
	rm -rf build/tmp
	rm -f dist/openevent_view-*.whl dist/openevent_view-*.tar.gz
