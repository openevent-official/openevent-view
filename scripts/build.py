"""Build the current View wheel and optionally install that exact file."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from pip._internal.commands import create_command

from install import check_install_environment, install_wheel


def wheel_environment():
    # pip wheel starts another pip install for its isolated build requirements.
    # Both processes need the wheel's package sources, even with a separate
    # [install] configuration for runtime dependencies.
    parser = create_command("wheel").parser
    parser.config.load()
    env = os.environ.copy()
    for name, value in parser._get_ordered_configuration_items():
        env["PIP_" + name.upper().replace("-", "_")] = value
    env["PIP_CONFIG_FILE"] = os.devnull
    for name in ("PIP_PYTHON", "PIP_ROOT", "PIP_TARGET", "PIP_PREFIX", "PIP_USER"):
        env.pop(name, None)
    return env


def main(mode):
    options = check_install_environment() if mode == "install" else None

    temporary = Path("build/tmp")
    temporary.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temporary) as directory:
        output = Path(directory)
        subprocess.run(
            [sys.executable, "-B", "-m", "pip", "wheel", "--no-deps", "--wheel-dir", output, "."],
            env=wheel_environment(), check=True,
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
