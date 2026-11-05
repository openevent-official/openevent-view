"""Installed View CLI against a fresh real server and the already installed SDK."""

from contextlib import ExitStack, contextmanager
from http.client import HTTPConnection
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import unittest


def free_ports(count):
    with ExitStack() as stack:
        sockets = [stack.enter_context(socket.socket()) for _ in range(count)]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]


@contextmanager
def running(command, logfile, cwd):
    with logfile.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, cwd=cwd)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def http(port, path, data=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        if data is None:
            connection.request("GET", path)
        else:
            connection.request(
                "POST", path, json.dumps(data), {"Content-Type": "application/json"}
            )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def wait_for_view(process, port, logfile):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"View exited during startup; see {logfile}")
        try:
            if http(port, "/")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.05)
    raise AssertionError(f"View did not become ready within 10 seconds; see {logfile}")


@unittest.skipUnless(
    os.environ.get("OPENEVENT_VIEW_E2E") == "1",
    "run make e2e with OPENEVENT_SERVER_BIN from a successful current server build",
)
class ViewEndToEndTests(unittest.TestCase):
    def test_installed_cli_history_system_message_pagination_and_payload(self):
        import grpc
        from packaging.version import Version
        from openevent.sdk import AdminClient, OpenEventClient
        from openevent.view import cli

        self.assertGreaterEqual(Version(importlib.metadata.version("openevent-sdk")), Version("0.11.1"))
        # The test runner and CLI must load this run's installed View wheel.
        installed_view = Path(os.environ["OPENEVENT_VIEW_E2E_SITE"]).resolve()
        self.assertTrue(Path(cli.__file__).resolve().is_relative_to(installed_view))
        root = Path(os.environ["OPENEVENT_VIEW_E2E_DIR"]) / "run"
        root.mkdir()
        public_port, admin_port, view_port = free_ports(3)
        public = f"127.0.0.1:{public_port}"
        admin_address = f"127.0.0.1:{admin_port}"
        server_config = root / "server.yaml"
        server_config.write_text(
            f'grpc:\n  listen_addr: "{public}"\n'
            f'admin:\n  listen_addr: "{admin_address}"\n'
            f'storage:\n  path: {json.dumps(str(root / "data"))}\n',
            encoding="utf-8",
        )
        view_config = root / "view.yaml"
        view_config.write_text(
            f'server:\n  host: "127.0.0.1"\n  port: {view_port}\n'
            f'  query_timeout_seconds: 5\nopenevent:\n  target: "{public}"\n'
            "  rpc_timeout_seconds: 2\nhistory:\n  fetch_batch_size: 2\n",
            encoding="utf-8",
        )
        with ExitStack() as stack:
            server = stack.enter_context(running(
                [os.environ["OPENEVENT_SERVER_BIN"], str(server_config)],
                root / "server.log", root,
            ))
            client = stack.enter_context(OpenEventClient(public, timeout_ms=2000))
            admin = stack.enter_context(AdminClient(admin_address, timeout_ms=2000))
            for connection in (client.channel, admin.channel):
                grpc.channel_ready_future(connection).result(timeout=10)
            self.assertIsNone(server.poll())
            principal = 1001
            token = admin.add_token(principal=principal).token
            credentials = {"principal": str(principal), "token": token}
            view = stack.enter_context(running(
                [str(installed_view / "bin/openevent-view"), "--config", str(view_config)],
                root / "view.log", root,
            ))
            wait_for_view(view, view_port, root / "view.log")

            def post(path, **fields):
                status, raw = http(view_port, path, {**credentials, **fields})
                self.assertEqual(status, 200, raw.decode("utf-8"))
                return json.loads(raw)

            # A fresh server has a real seq=0 message, rather than empty history.
            initial = post("/v1/messages")
            self.assertEqual([item["seq"] for item in initial["messages"]], ["0"])
            self.assertIsNone(initial["next_cursor"])
            system = post("/v1/messages/0/payload")["message"]
            self.assertEqual((system["seq"], system["channel_id"]), ("0", "0"))
            self.assertEqual(http(view_port, "/message?seq=0")[0], 200)
            self.assertEqual(http(view_port, "/static/app.js")[0], 200)

            channel = client.create_channel(principal, token, "view-e2e", protocol="test/view").channel
            member = 1002
            client.add_member(principal, token, channel.channel_id, member)
            client.remove_member(principal, token, channel.channel_id, member)

            # Use actual upstream messages as the independent projection baseline;
            # View does not interpret or validate their system payload schema.
            system_messages = []
            from_seq = 0
            while True:
                upstream = client.fetch(principal, token, from_seq=from_seq, limit=1000)
                system_messages.extend(upstream.messages)
                if upstream.next_seq > upstream.last_seq:
                    break
                from_seq = upstream.next_seq
            channels = {
                channel_id: client.get_channel(principal, token, channel_id).channel
                for channel_id in {event.channel_id for event in system_messages}
            }
            expected_system_messages = {}
            for event in system_messages:
                display = channels[event.channel_id]
                expected_system_messages[str(event.seq)] = {
                    "seq": str(event.seq),
                    "uuid": str(event.uuid),
                    "ts_ms": str(event.ts_ms),
                    "channel_id": str(event.channel_id),
                    "channel_name": display.name,
                    "channel_protocol": display.protocol,
                    "principal": str(event.principal),
                    "recipients": [str(recipient) for recipient in event.recipients],
                    "object_ids": [str(key.object_id) for key in event.object_keys],
                    "payload": {
                        "encoding": "utf-8",
                        "text": event.payload.decode("utf-8"),
                        "truncated": False,
                        "size_bytes": len(event.payload),
                    },
                }
            self.assertEqual(system, expected_system_messages["0"])

            payloads = [b'{"kind":"small"}', b"BEGIN|" + b"x" * 32768 + b"|END"]
            published = []
            for payload in payloads:
                uuid = client.get_uuid()
                seq = client.publish_auto_seq(
                    principal, token, channel.channel_id, payload, uuid
                ).seq
                published.append((seq, uuid))

            complete = post("/v1/messages")
            expected_seqs = [str(seq) for seq in sorted(
                [event.seq for event in system_messages] + [seq for seq, _ in published],
                reverse=True,
            )]
            self.assertEqual([item["seq"] for item in complete["messages"]], expected_seqs)
            self.assertIsNone(complete["next_cursor"])
            for item in complete["messages"][2:]:
                with self.subTest(system_seq=item["seq"]):
                    expected = expected_system_messages[item["seq"]]
                    self.assertEqual(item, expected)
                    self.assertEqual(post(f'/v1/messages/{item["seq"]}/payload')["message"], expected)
            large = complete["messages"][0]
            self.assertEqual(large["uuid"], str(published[-1][1]))
            self.assertTrue(large["payload"]["truncated"])
            self.assertGreater(large["payload"]["preview"]["omitted_bytes"], 0)
            self.assertTrue(large["payload"]["preview"]["head"].startswith("BEGIN|"))
            self.assertTrue(large["payload"]["preview"]["tail"].endswith("|END"))
            self.assertEqual(complete["messages"][1]["payload"]["text"], payloads[0].decode("utf-8"))
            detail = post(f'/v1/messages/{large["seq"]}/payload')["message"]
            self.assertFalse(detail["payload"]["truncated"])
            self.assertEqual(detail["payload"]["text"], payloads[-1].decode("utf-8"))
            self.assertEqual(detail["payload"]["size_bytes"], len(payloads[-1]))

            filtered = post("/v1/messages", channel_id="0")
            self.assertEqual([item["seq"] for item in filtered["messages"]], ["0"])
            self.assertEqual(filtered["channel"]["channel_id"], "0")
            filtered = post("/v1/messages", channel_id=str(channel.channel_id))
            channel_seqs = {str(event.seq) for event in system_messages if event.channel_id == channel.channel_id}
            channel_seqs.update(str(seq) for seq, _ in published)
            self.assertEqual([item["seq"] for item in filtered["messages"]],
                             [seq for seq in expected_seqs if seq in channel_seqs])
            self.assertEqual(filtered["channel"]["channel_protocol"], "test/view")

            cursor = None
            pages = []
            for _ in range(len(expected_seqs) + 1):
                page = post("/v1/messages", cursor=cursor, limit=1)
                for item in page["messages"]:
                    if item["seq"] in expected_system_messages:
                        self.assertEqual(item, expected_system_messages[item["seq"]])
                pages.extend(item["seq"] for item in page["messages"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            self.assertIsNone(cursor, "pagination must terminate after seq=0")
            self.assertEqual(pages, expected_seqs)
            self.assertEqual(post("/v1/messages", cursor={"before_seq": "0"})["messages"], [])


if __name__ == "__main__":
    unittest.main()
