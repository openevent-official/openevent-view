"""Build the current View wheel and optionally install that exact file."""

from configparser import RawConfigParser
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from pip._internal.configuration import Configuration

from install import check_install_environment, install_wheel


def wheel_environment(output):
    env = os.environ.copy()
    redirects = {"python", "root", "target"}
    sources = {"index-url", "extra-index-url", "no-index", "find-links"}
    for name in redirects:
        env.pop("PIP_" + name.upper(), None)

    # pip installs build requirements with its own --no-user and --prefix.
    # Keep the install subprocess's transport settings, including trusted-host,
    # while using the wheel command's package sources for this build.
    settings = Configuration(isolated=False)
    settings.load()
    config = RawConfigParser()
    changed = False
    for key, value in settings.items():
        section, name = key.split(".", 1)
        if section == ":env:":
            continue
        if not config.has_section(section):
            config.add_section(section)
        if value and (name in redirects or (section == "install" and name in sources)):
            value = ""
            changed = True
        elif value and section == "wheel" and name in sources:
            variable = "PIP_" + name.upper().replace("-", "_")
            env[variable] = env.get(variable) or value
        config.set(section, name, value)
    if changed:
        path = output / "pip.conf"
        with path.open("w", encoding="utf-8") as stream:
            config.write(stream)
        env["PIP_CONFIG_FILE"] = str(path.resolve())
    return env


def main(mode):
    options = check_install_environment() if mode == "install" else None

    temporary = Path("build/tmp")
    temporary.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temporary) as directory:
        output = Path(directory)
        subprocess.run(
            [sys.executable, "-B", "-m", "pip", "wheel", "--no-deps", "--wheel-dir", output, "."],
            env=wheel_environment(output), check=True,
        )
        wheel, = output.glob("*.whl")
        release = Path("dist") / wheel.name
        release.parent.mkdir(exist_ok=True)
        shutil.move(wheel, release)
    print(f"Built {release}", flush=True)

    if options is not None:
        install_wheel(release, options)


if __name__ == "__main__":
    main(sys.argv[1])
