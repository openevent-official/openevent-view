"""Validate the installed SDK against the dependency declaration for this View."""

from importlib import metadata
from pathlib import Path
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


def _project_requirements() -> list[str]:
    module = Path(__file__).resolve()
    project_root = module.parents[3]
    source_module = project_root / "src" / "openevent" / "view" / "dependencies.py"
    project_file = project_root / "pyproject.toml"
    if module == source_module and project_file.is_file():
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib

        with project_file.open("rb") as stream:
            project = tomllib.load(stream)["project"]
        if project["name"] != "openevent-view":
            raise SystemExit("source checkout does not declare the openevent-view project")
        return project["dependencies"]

    try:
        return metadata.requires("openevent-view") or []
    except metadata.PackageNotFoundError as exc:
        raise SystemExit("openevent-view package metadata is missing; reinstall openevent-view") from exc


def require_installed_sdk() -> Requirement:
    requirements = [Requirement(declaration) for declaration in _project_requirements()]
    sdk_requirements = [
        requirement for requirement in requirements
        if canonicalize_name(requirement.name) == "openevent-sdk"
        and (requirement.marker is None or requirement.marker.evaluate({"extra": ""}))
    ]
    if len(sdk_requirements) != 1:
        raise SystemExit("openevent-view must declare exactly one active openevent-sdk dependency")
    requirement = sdk_requirements[0]
    try:
        installed = metadata.version(requirement.name)
    except metadata.PackageNotFoundError as exc:
        raise SystemExit(
            f"openevent-view requires installed {requirement}; openevent-sdk is not installed"
        ) from exc
    try:
        compatible = Version(installed) in requirement.specifier
    except InvalidVersion:
        compatible = False
    if not compatible:
        raise SystemExit(f"openevent-view requires {requirement}; found openevent-sdk {installed}")
    return requirement
