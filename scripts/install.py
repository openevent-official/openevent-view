"""Install View in the selected Python environment."""

from contextlib import contextmanager, nullcontext
from importlib import metadata
from importlib.util import cache_from_source
from pathlib import Path
import site
import subprocess
import sys
from zipfile import ZipFile

from pip._internal.commands import create_command
from pip._internal.commands.install import decide_user_install
from pip._internal.locations import get_scheme
from pip._internal.utils.wheel import wheel_dist_info_dir


def check_install_environment():
    options, _ = create_command("install").parser.parse_args([])
    for flag, value in (("--python", options.python), ("--root", options.root_path)):
        if value:
            sys.exit(f"Remove pip's {flag} setting to install View in the selected Python environment.")
    return options


@contextmanager
def replace_user_files(wheel):
    # A venv with a visible user site can install there, but pip skips uninstalling
    # packages outside the venv. Use View's two RECORDs to remove its obsolete files.
    scheme = get_scheme("openevent-view", user=True)
    previous = next(metadata.distributions(name="openevent-view", path=[scheme.purelib]), None)
    if previous is None:
        yield
        return
    files = previous.files
    if files is None:
        sys.exit(f"Cannot replace View in {scheme.purelib}: its installed file list is missing")
    old_files = {Path(entry.locate()) for entry in files}
    yield
    with ZipFile(wheel) as archive:
        info = wheel_dist_info_dir(archive, "openevent-view")
    current = metadata.Distribution.at(Path(scheme.purelib) / info)
    obsolete = old_files.difference(Path(entry.locate()) for entry in current.files)
    # Same-size source replacements within a second can match the old bytecode.
    obsolete.update(Path(cache_from_source(str(path))) for path in old_files if path.suffix == ".py")
    user_base = Path(scheme.data).resolve()
    for path in obsolete:
        directory = path.parent.resolve()
        if directory.is_relative_to(user_base):
            (directory / path.name).unlink(missing_ok=True)
            while directory != user_base and directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
                directory = directory.parent


def install_wheel(wheel, options):
    cleanup = nullcontext()
    if (sys.prefix != sys.base_prefix and site.ENABLE_USER_SITE
            and decide_user_install(options.use_user_site)):
        cleanup = replace_user_files(wheel)
    pip = [sys.executable, "-B", "-m", "pip", "install", "--no-compile"]
    with cleanup:
        subprocess.run([*pip, wheel], check=True)
        subprocess.run([*pip, "--force-reinstall", "--no-deps", wheel], check=True)
