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

If you use a virtual environment, activate it first. Use the same shell to set up the SDK,
install View, and start it. This example uses an existing virtual environment at `/opt/openevent-view`.

```bash
source /opt/openevent-view/bin/activate
```

Before running `make install`, install an `openevent-sdk` wheel (version 0.13.0 or newer)
in the Python environment you will use for View, or configure pip to use a package source
that provides a compatible version. To build the wheel, see the
[SDK build instructions](https://github.com/openevent-official/openevent-sdk/blob/2183f679bc9e040db96aaab1eeda044bab91e856/README.md#build-and-test).

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

Run these commands from the View repository root. Use `PYTHON` to select a writable
Python environment with pip installed. The default is `python3`. For example, run
`make install PYTHON=/opt/openevent-view/bin/python`.

| Command | Purpose |
| --- | --- |
| `make build` | Build the wheel under `build/` and move it to `dist/` on success. |
| `make install` | Install the wheel from this build, replacing View even at the same version. pip installs missing or incompatible dependencies and reuses those that meet the requirements. |
| `make clean` | Remove View's temporary build files and release packages. Keep development environments, offline dependencies, and other projects' packages. |

Installation stops before the build if install arguments, environment variables, or pip
configuration specify `--python`, `--target`, `--prefix`, or `--root`.

For an offline install, put the build and runtime dependencies, including their transitive
dependencies, for the target environment in `build/wheelhouse/`, then run:

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
