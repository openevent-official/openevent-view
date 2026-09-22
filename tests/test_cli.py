import unittest
from unittest.mock import Mock, patch

from openevent.sdk import OpenEventClient
from openevent.view.cli import main
from openevent.view.upstream import HistoryClient


class CliTests(unittest.TestCase):
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
