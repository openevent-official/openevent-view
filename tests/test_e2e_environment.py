"""Exercise e2e environment selection with real isolated Python environments."""

import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import venv

import packaging

from test_install import ROOT, process_environment, write_wheel


class EndToEndEnvironmentTests(unittest.TestCase):
    def setUp(self):
        build = ROOT / "build"
        build.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="e2e-environment-test-", dir=build)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "tests").mkdir()
        (self.project / "dist").mkdir()
        shutil.copyfile(ROOT / "test-e2e.sh", self.project / "test-e2e.sh")
        self.wheels = self.root / "wheels"
        self.wheels.mkdir()
        self.environment = process_environment()
        self.environment["PIP_NO_INDEX"] = "1"

        # This SDK test double exists only in the selected environment. Using the
        # base interpreter's site-packages instead would lose this installation.
        environment_path = self.root / "selected-environment"
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(environment_path)
        self.python = Path(builder.ensure_directories(environment_path).env_exe)
        self.site_packages = Path(self.run_python(
            "import sysconfig; print(sysconfig.get_path('purelib'))"
        ).strip())

        # Package the already installed parser locally; this test never downloads.
        packaging_root = Path(packaging.__file__).parent
        write_wheel(
            self.wheels, "packaging", importlib.metadata.version("packaging"),
            {str(path.relative_to(packaging_root.parent)): path.read_bytes()
             for path in packaging_root.rglob("*.py")},
        )
        self.install(next(self.wheels.glob("packaging-*.whl")))

        # The copied script only needs an executable marker; its fake runner below
        # verifies package selection without starting a server or touching the SDK.
        self.server = self.root / "server"
        self.server.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.server.chmod(0o755)
        self.write_view(self.project / "dist", "current build")
        (self.project / "tests/test_e2e.py").write_text(
            """import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from openevent import sdk, view

site = Path(os.environ["OPENEVENT_VIEW_E2E_SITE"]).resolve()
assert Path(sys.executable) == Path(os.environ["EXPECTED_PYTHON"])
assert Path(sdk.__file__).resolve().is_relative_to(Path(os.environ["EXPECTED_PARENT_SITE"]))
assert sdk.ORIGIN == "selected environment"
assert Path(view.__file__).resolve().is_relative_to(site)
assert view.ORIGIN == "current build"
assert importlib.metadata.version("openevent-sdk") == "0.8.1"
assert os.environ["PYTHONPATH"] == str(site)
command = site / "bin/openevent-view"
cli = subprocess.check_output([str(command)], text=True).strip()
assert cli == "current build: selected environment", cli
Path(os.environ["OPENEVENT_VIEW_E2E_DIR"], "runner.json").write_text(json.dumps({
    "python": sys.executable, "sdk": sdk.__file__, "view": view.__file__, "cli": cli,
}), encoding="utf-8")
""",
            encoding="utf-8",
        )

    def run_python(self, code):
        return subprocess.check_output(
            [str(self.python), "-B", "-c", code], env=self.environment, text=True,
        )

    def install(self, wheel):
        result = subprocess.run(
            [str(self.python), "-B", "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
            env=self.environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def install_sdk(self, version):
        write_wheel(self.wheels, "openevent_sdk", version, {
            "openevent/sdk/__init__.py": (
                'ORIGIN = "selected environment"\n'
                "class AdminClient: pass\nclass OpenEventClient: pass\n"
            ),
        })
        self.install(self.wheels / f"openevent_sdk-{version}-py3-none-any.whl")

    def write_view(self, directory, origin):
        write_wheel(directory, "openevent_view", "9.9.0", {
            "openevent/view/__init__.py": (
                f"ORIGIN = {origin!r}\n"
                "def main():\n"
                "    from openevent.sdk import ORIGIN as sdk_origin\n"
                "    print(ORIGIN + ': ' + sdk_origin)\n"
            ),
            "openevent_view-9.9.0.dist-info/entry_points.txt": (
                "[console_scripts]\nopenevent-view = openevent.view:main\n"
            ),
        }, requires=("openevent-sdk>=0.8.0",))

    def run_e2e(self):
        environment = dict(self.environment)
        environment.update(
            PYTHON=str(self.python), OPENEVENT_SERVER_BIN=str(self.server),
            EXPECTED_PYTHON=str(self.python), EXPECTED_PARENT_SITE=str(self.site_packages),
        )
        return subprocess.run(
            ["bash", str(self.project / "test-e2e.sh")], cwd=self.project,
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

    def installed_snapshot(self):
        return {
            str(path.relative_to(self.site_packages)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.site_packages.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }

    def test_parent_environment_dependencies_and_current_view_are_used_without_reinstallation(self):
        self.install_sdk("0.8.1")
        self.write_view(self.wheels, "previous installation")
        self.install(self.wheels / "openevent_view-9.9.0-py3-none-any.whl")
        before = self.installed_snapshot()
        result = self.run_e2e()
        self.assertEqual(result.returncode, 0, result.stdout)
        report = json.loads((self.project / "build/e2e/runner.json").read_text())
        self.assertEqual(report["python"], str(self.python))
        self.assertEqual(report["cli"], "current build: selected environment")
        self.assertEqual(before, self.installed_snapshot())
        self.assertEqual(self.run_python("from openevent.view import ORIGIN; print(ORIGIN)").strip(), "previous installation")
        self.assertFalse((self.project / "build/e2e/venv").exists())

    def test_missing_sdk_fails_before_installing_view_or_running_tests(self):
        before = self.installed_snapshot()
        result = self.run_e2e()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("openevent-sdk", result.stdout)
        self.assertFalse((self.project / "build/e2e/runner.json").exists())
        self.assertFalse((self.project / "build/e2e/site/openevent/view").exists())
        self.assertEqual(before, self.installed_snapshot())

    def test_incompatible_sdk_fails_before_installing_view_or_running_tests(self):
        self.install_sdk("0.7.9")
        before = self.installed_snapshot()
        result = self.run_e2e()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("openevent-sdk", result.stdout)
        self.assertIn("0.7.9", result.stdout)
        self.assertFalse((self.project / "build/e2e/runner.json").exists())
        self.assertFalse((self.project / "build/e2e/site/openevent/view").exists())
        self.assertEqual(before, self.installed_snapshot())


if __name__ == "__main__":
    unittest.main()
