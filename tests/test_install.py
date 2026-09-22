"""Installation regressions using local wheels without downloading dependencies."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def write_wheel(directory, name, version, files, requires=()):
    metadata = f"{name}-{version}.dist-info"
    contents = dict(files)
    contents[metadata + "/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        + "".join(f"Requires-Dist: {requirement}\n" for requirement in requires)
    )
    contents[metadata + "/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: view-installation-test\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    record = metadata + "/RECORD"
    contents[record] = "".join(f"{path},,\n" for path in [*contents, record])
    with zipfile.ZipFile(directory / f"{name}-{version}-py3-none-any.whl", "w") as archive:
        for member, content in contents.items():
            archive.writestr(member, content)


def process_environment():
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith("PIP_") and name != "PYTHONPATH"}
    environment.update(PYTHONDONTWRITEBYTECODE="1", PIP_NO_COMPILE="1",
                       PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1")
    return environment


class InstallationTests(unittest.TestCase):
    def setUp(self):
        build = ROOT / "build"
        build.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="install-test-", dir=build)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/install.py", self.root / "scripts/install.py")
        self.wheels = self.root / "dist"
        self.wheels.mkdir()

    def install(self, *arguments, python=sys.executable, environment=None):
        return subprocess.run(
            [str(python), "-B", str(self.root / "scripts/install.py"),
             "--no-index", "--find-links", str(self.wheels), *arguments],
            env=environment or process_environment(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

    def test_same_version_replaces_view_and_only_needed_dependencies(self):
        # Reuse pip from the current environment without bootstrapping or downloading.
        builder = venv.EnvBuilder(system_site_packages=True)
        environment_path = self.root / "environment"
        builder.create(environment_path)
        python = builder.ensure_directories(environment_path).env_exe
        site_packages = Path(subprocess.check_output(
            [str(python), "-B", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            env=process_environment(), text=True,
        ).strip())

        def view(value, obsolete=False, requires=("view_install_dependency>=1",)):
            files = {"view_install_project.py": value}
            if obsolete:
                files["view_install_obsolete.py"] = "old"
            write_wheel(self.wheels, "openevent_view", "9.9.0", files, requires)

        def install(*arguments):
            result = self.install(*arguments, python=python)
            self.assertEqual(result.returncode, 0, result.stdout)

        write_wheel(self.wheels, "view_install_dependency", "1.0", {"view_install_dependency.py": "one"})
        view("old", obsolete=True)
        install()
        dependency = site_packages / "view_install_dependency.py"
        project = site_packages / "view_install_project.py"
        self.assertEqual(dependency.read_text(), "one")
        self.assertEqual(project.read_text(), "old")
        dependency_mtime = dependency.stat().st_mtime_ns

        write_wheel(self.wheels, "view_install_dependency", "2.0", {"view_install_dependency.py": "two"})
        view("new")
        install()
        self.assertEqual(project.read_text(), "new")
        self.assertFalse((site_packages / "view_install_obsolete.py").exists())
        self.assertEqual(dependency.read_text(), "one")
        self.assertEqual(dependency.stat().st_mtime_ns, dependency_mtime)

        view("dry run")
        install("--dry-run")
        self.assertEqual(project.read_text(), "new")

        view("new dependency", requires=("view_install_dependency>=2",))
        install()
        self.assertEqual(dependency.read_text(), "two")
        self.assertEqual(project.read_text(), "new dependency")

        view("must not install", requires=("view_install_missing_dependency==1",))
        failed = self.install(python=python)
        self.assertNotEqual(failed.returncode, 0, failed.stdout)
        self.assertEqual(project.read_text(), "new dependency")
        self.assertEqual(list(site_packages.rglob("*.pyc")), [])

    def test_alternate_destinations_are_rejected(self):
        for arguments in (
            ["--target", "/unused"], ["--target=/unused"], ["-t", "/unused"], ["-t/unused"],
            ["--prefix", "/unused"], ["--prefix=/unused"], ["--root", "/unused"], ["--root=/unused"],
        ):
            with self.subTest(arguments=arguments):
                result = self.install(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("choose its interpreter with PYTHON", result.stdout)
        for variable in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT"):
            with self.subTest(variable=variable):
                environment = process_environment()
                environment[variable] = "/unused"
                result = self.install(environment=environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("choose its interpreter with PYTHON", result.stdout)

    def test_install_requires_one_view_wheel(self):
        for versions in ([], ["0.1.0", "0.2.0"]):
            with self.subTest(versions=versions):
                for version in versions:
                    write_wheel(self.wheels, "openevent_view", version, {})
                result = self.install()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Exactly one View wheel", result.stdout)

    def test_failed_build_never_installs_an_old_wheel(self):
        shutil.copyfile(ROOT / "Makefile", self.root / "Makefile")
        write_wheel(self.wheels, "openevent_view", "0.1.0", {})
        build = self.root / "build.sh"
        build.write_text("#!/bin/sh\nexit 1\n")
        build.chmod(0o755)
        marker = self.root / "install-ran"
        (self.root / "scripts/install.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        )
        result = subprocess.run(
            ["make", "install", "PYTHON=" + sys.executable], cwd=self.root,
            env=process_environment(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
