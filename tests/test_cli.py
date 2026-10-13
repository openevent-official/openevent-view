from importlib import metadata
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from openevent.sdk import OpenEventClient
from openevent.view.cli import main
from openevent.view import dependencies
from openevent.view.upstream import HistoryClient


class CliTests(unittest.TestCase):
    def test_missing_or_incompatible_sdk_stops_before_creating_client_or_listener(self):
        for installed in (metadata.PackageNotFoundError("openevent-sdk"), "0.0.0"):
            with self.subTest(installed=installed):
                version = (
                    Mock(side_effect=installed) if isinstance(installed, Exception)
                    else Mock(return_value=installed)
                )
                with (
                    patch.object(dependencies.metadata, "version", version),
                    patch("openevent.sdk.OpenEventClient") as client,
                    patch("openevent.view.cli.create_server") as server,
                    self.assertRaisesRegex(SystemExit, "openevent-view requires.*openevent-sdk"),
                ):
                    main([])
                client.assert_not_called()
                server.assert_not_called()

    def test_startup_uses_installed_sdk_and_closes_it(self):
        instances = []

        class ObservedClient(OpenEventClient):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                instances.append(self)

        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with patch("openevent.sdk.OpenEventClient", ObservedClient):
            with patch("openevent.view.cli.create_server", return_value=server):
                self.assertEqual(main([]), 0)
        self.assertEqual(instances[0].timeout_ms, 10000)
        self.assertTrue(instances[0]._closed)
        server.server_close.assert_called_once()

    def test_sdk_is_closed_if_http_listener_cannot_start(self):
        instances = []

        class ObservedClient(OpenEventClient):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                instances.append(self)

        with patch("openevent.sdk.OpenEventClient", ObservedClient):
            with patch("openevent.view.cli.create_server", side_effect=OSError("bind failed")):
                with self.assertRaises(OSError):
                    main([])
        self.assertTrue(instances[0]._closed)

    def test_generated_sdk_requests_keep_filters_and_individual_deadlines(self):
        sdk = Mock()
        client = HistoryClient(sdk)
        client.get_status(1, "t", timeout=0.4)
        request = sdk.event_stub.GetStatus.call_args.args[0]
        self.assertEqual(request.principal, 1)
        self.assertEqual(sdk.event_stub.GetStatus.call_args.kwargs, {"timeout": 0.4})
        client.fetch(1, "t", 0, 100, True, (0,), timeout=0.3)
        request = sdk.event_stub.Fetch.call_args.args[0]
        self.assertEqual(request.from_seq, 0)
        self.assertEqual(list(request.channels), [0])
        self.assertTrue(request.only_my_recipient)
        self.assertEqual(sdk.event_stub.Fetch.call_args.kwargs, {"timeout": 0.3})
        client.get_channel(1, "t", 0, timeout=0.2)
        self.assertEqual(sdk.channel_stub.GetChannel.call_args.args[0].channel_id, 0)
        self.assertEqual(sdk.channel_stub.GetChannel.call_args.kwargs, {"timeout": 0.2})


class DependencyDeclarationTests(unittest.TestCase):
    def setUp(self):
        build = Path(__file__).resolve().parents[1] / "build"
        build.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="sdk-declaration-test-", dir=build)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_source_uses_current_checkout_declaration_instead_of_installed_view(self):
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "openevent-view"\n'
            'dependencies = ["openevent-sdk>=7,<8", "PyYAML"]\n',
            encoding="utf-8",
        )
        source = self.root / "src/openevent/view/dependencies.py"
        with patch.object(dependencies, "__file__", str(source)):
            with patch.object(dependencies.metadata, "requires") as installed_requirements:
                with patch.object(dependencies.metadata, "version", return_value="7.2"):
                    dependencies.require_installed_sdk()
                with patch.object(dependencies.metadata, "version", return_value="8.0"):
                    with self.assertRaisesRegex(SystemExit, "found openevent-sdk 8.0"):
                        dependencies.require_installed_sdk()
                installed_requirements.assert_not_called()

    def test_installed_view_uses_metadata_despite_unrelated_ancestor_pyproject(self):
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "unrelated-project"\n'
            'dependencies = ["openevent-sdk>=8"]\n',
            encoding="utf-8",
        )
        installed = self.root / "site-packages/openevent/view/dependencies.py"
        with (
            patch.object(dependencies, "__file__", str(installed)),
            patch.object(dependencies.metadata, "requires", return_value=["openevent-sdk>=7,<8"]) as requirements,
            patch.object(dependencies.metadata, "version", return_value="7.2"),
        ):
            dependencies.require_installed_sdk()
        requirements.assert_called_once_with("openevent-view")

    def test_missing_installed_view_metadata_does_not_skip_sdk_check(self):
        installed = self.root / "site-packages/openevent/view/dependencies.py"
        with (
            patch.object(dependencies, "__file__", str(installed)),
            patch.object(
                dependencies.metadata, "requires",
                side_effect=metadata.PackageNotFoundError("openevent-view"),
            ),
            self.assertRaisesRegex(SystemExit, "openevent-view package metadata is missing"),
        ):
            dependencies.require_installed_sdk()
