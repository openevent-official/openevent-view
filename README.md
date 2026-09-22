# openevent-view

[中文版](README_cn.md)

`openevent-view` is a web service for OpenEvent history and Channel metadata,
accessed through the installed SDK without direct storage access. It lists newest
messages first, supports Channel and recipient filters, and includes system
messages visible to the caller. Small payloads expand inline; large payloads show
previews and open their complete content in a new tab.

## Documentation

The [reference](docs/REFERENCE.md) is authoritative for configuration, HTTP APIs,
payload representation, and deployment boundaries. This README contains only
installation, quick start, and verification entry points.

## Installation and Startup

Python 3.10 or newer is required. [pyproject.toml](pyproject.toml) declares runtime
dependencies; the SDK minimum is 0.8.0. Actual deployments use the SDK installed
in the Python environment running View. The SDK submodule is a source reference only.

```bash
make install
openevent-view
```

Defaults listen on `127.0.0.1:8080` and connect to OpenEvent at `127.0.0.1:9527`.
Open the View address in a browser and enter OpenEvent credentials to query
history. The service targets trusted internal networks by default; read the
[deployment boundary](docs/REFERENCE.md#1-deployment-boundary) before deployment.

For custom configuration, save the [configuration example](docs/REFERENCE.md#2-configuration)
as a YAML file and run:

```bash
openevent-view --config openevent-view.yaml
```

During development, run this repository's source directly:

```bash
PYTHONPATH=src python3 -B -m openevent.view --config openevent-view.yaml
```

`--host` and `--port` override the listen address. Use `make build` to build only;
release wheels go in `dist/`. Temporary files, caches, and logs stay in `build/`,
not source directories.

`make install` installs only the unique wheel from the current successful build,
replacing installed View even at the same version. Dependencies are resolved from
the package declaration, preserving those already satisfying requirements. Choose
the environment with `PYTHON`, for example
`make install PYTHON=/opt/openevent-view/bin/python`. Using `--target`, `--prefix`,
or `--root` to redirect installation into another environment is not supported.

## Quick Query

Scripts and pages share read-only POST APIs, with credentials in the JSON body:

```http
POST /v1/messages
Content-Type: application/json

{"principal":"10001","token":"tok_xxx","cursor":null}
```

The response contains `messages` and `next_cursor`. Pass a non-null cursor back
unchanged to read older messages. See the [HTTP API](docs/REFERENCE.md#4-http-api)
for complete fields, boundaries, and error rules.

## Verification

Install the declared runtime and `test` optional dependencies in the Python
environment selected by `PYTHON`, which defaults to `python3`. Frontend tests
require Node.js 18 or newer. Tests do not automatically install the SDK or load
code from its submodule.

```bash
make test
make check-docs
```

`make test-python` and `make test-frontend` run the suites separately. End-to-end
verification uses the current successfully built View wheel and an explicitly
selected OpenEvent server executable:

```bash
make e2e OPENEVENT_SERVER_BIN=/path/to/current/build/openevent_server
```

When `PYTHON` selects an existing virtual environment, dependency checks, tests,
and the View process all use that environment's interpreter and installed
dependencies. For example:

```bash
make e2e PYTHON=/opt/openevent-view/bin/python \
  OPENEVENT_SERVER_BIN=/path/to/current/build/openevent_server
```

The test installs only the current View wheel into `build/e2e/site/` and loads it
from there. It does not create a child virtual environment or replace View or
third-party dependencies installed in the selected environment.

Select the server artifact from a successful build of its current version. Test
configuration, data, and logs stay in `build/e2e/`.
