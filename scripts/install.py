"""Build View and install the resulting wheel when requested."""

from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from pip._internal.cli.main_parser import create_main_parser
from pip._internal.commands import create_command


def check_destination(arguments):
    general, _ = create_main_parser().parse_args(["install", *arguments])
    if getattr(general, "python", None):
        sys.exit("pip has --python set; choose the Python environment with PYTHON instead")
    command = create_command("install", isolated="--isolated" in arguments)
    options, _ = command.parser.parse_args(arguments)
    for flag in ("--python", "--target", "--prefix", "--root"):
        option = command.parser.get_option(flag)
        if option and getattr(options, option.dest) is not None:
            sys.exit(f"pip has {flag} set; choose the Python environment with PYTHON instead")


def main(mode="build", *arguments):
    if mode == "install":
        check_destination([])
        if arguments:
            check_destination(list(arguments))

    temporary = Path("build/tmp")
    temporary.mkdir(parents=True, exist_ok=True)
    pip = [sys.executable, "-B", "-m", "pip"]
    with TemporaryDirectory(dir=temporary) as output:
        subprocess.run([*pip, "wheel", "--no-deps", "--wheel-dir", output, "."], check=True)
        wheel, = Path(output).glob("*.whl")
        release = Path("dist") / wheel.name
        release.parent.mkdir(exist_ok=True)
        shutil.move(wheel, release)
    print(f"Built {release}", flush=True)

    if mode == "install":
        install = [*pip, "install", "--no-compile"]
        subprocess.run([*install, *arguments, str(release)], check=True)
        subprocess.run([*install, "--force-reinstall", "--no-deps", *arguments, str(release)],
                       check=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
