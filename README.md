# openevent-view

[中文版](README_cn.md)

`openevent-view` is a web service for OpenEvent history and Channel metadata,
accessed through the installed SDK without direct storage access. It lists newest
messages first, supports Channel and recipient filters, and includes system
messages visible to the caller. Small payloads expand inline; large payloads show
previews and open their complete content in a new tab.

## Documentation

The [reference](docs/REFERENCE.md) is authoritative for configuration, HTTP APIs,
payload representation, and deployment boundaries. This README covers building and
installing View and querying message history.

## Installation and Startup

View requires Python 3.10 or newer and uses the SDK installed in its Python environment.
The SDK submodule is a source reference only. See [pyproject.toml](pyproject.toml) for runtime dependencies.

Run these commands from the View repository root. `make install` requires pip 22.3 or newer,
compatible with the Python interpreter you select.
If you use a virtual environment, activate it first. Use the same shell to set up the SDK,
install View, and start it. This example uses an existing virtual environment at `/opt/openevent-view`.

```bash
source /opt/openevent-view/bin/activate
```

Before running `make install`, install an `openevent-sdk` wheel (version 0.13.0 or newer)
in the Python environment you will use for View, or configure pip to use a package source
that provides a compatible version. To build the wheel, see the
[SDK build instructions](https://github.com/openevent-official/openevent-sdk/blob/fd4dd7062786129d3fa72e95e9dcf10163972ad0/README.md#build-and-test).

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

`--host` and `--port` override the listen address.

## Build Commands

Run Make from the View repository root. It defaults to the current shell's `python3`.
You can use a system Python or a virtual environment. To select the interpreter that
will run View, use `make install PYTHON=/opt/openevent-view/bin/python`.

| Command | Purpose |
| --- | --- |
| `make help` | List the available commands. |
| `make build` | Build the wheel in isolation in a temporary directory under `build/`. On success, move it to `dist/` and print its path. |
| `make install` | Install the wheel from this build into the selected Python environment, replacing View even at the same version. pip installs only missing or incompatible runtime dependencies. |
| `make clean` | Remove View's temporary build files and release packages. Keep development environments, offline dependencies, and other projects' packages. |

The install location must be writable. If the selected Python allows user installs
and can import user-site packages, you can run `PIP_USER=1 make install` or set
`user = true` in `pip.conf`. Installations into a distribution-managed system
Python follow pip and distribution restrictions. If pip's environment variables or
configuration specify `--python` or `--root`, `make install` stops before building.

### Installing into a Specific Directory

To install View and its dependencies into an application's release directory, run
`make build` first. Use a Python compatible with the deployment environment to run
one of the following commands. Replace the example wheel path with the one printed
by this build.

- `python3 -B -m pip install --target ./packages dist/openevent_view-0.1.0-py3-none-any.whl` installs packages directly into `./packages/`.
- `python3 -B -m pip install --prefix /opt/myapp dist/openevent_view-0.1.0-py3-none-any.whl` installs libraries and scripts under `/opt/myapp/lib/` and `/opt/myapp/bin/`.

`PIP_TARGET`, `PIP_PREFIX`, and the `target` or `prefix` options in `pip.conf` are
also for direct pip installs. Clear these settings before running `make install`.
For direct installs, pip handles existing files and dependencies according to its own rules.

### Offline Installation

Both the build and install use pip's configured package sources. Use `[global]`
in `pip.conf` for a shared source, or configure `[wheel]` and `[install]` separately.
Put the build and runtime dependencies for the target environment, including their
transitive dependencies, in `build/wheelhouse/`, then run the following command.

```bash
PIP_NO_INDEX=1 PIP_FIND_LINKS=build/wheelhouse make install
```

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
