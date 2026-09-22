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

        self.assertGreaterEqual(Version(importlib.metadata.version("openevent-sdk")), Version("0.8.0"))
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
            token = admin.add_token(target_principal=principal).binding.token
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
            payloads = [b'{"kind":"small"}', b"BEGIN|" + b"x" * 32768 + b"|END"]
            published = []
            for payload in payloads:
                uuid = client.get_uuid()
                seq = client.publish_auto_seq(
                    principal, token, channel.channel_id, payload, uuid
                ).seq
                published.append((seq, uuid))

            complete = post("/v1/messages")
            expected_seqs = [str(item[0]) for item in reversed(published)] + ["0"]
            self.assertEqual([item["seq"] for item in complete["messages"]], expected_seqs)
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

            cursor = None
            pages = []
            for _ in range(len(expected_seqs) + 1):
                page = post("/v1/messages", cursor=cursor, limit=1)
                pages.extend(item["seq"] for item in page["messages"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            self.assertIsNone(cursor, "pagination must terminate after seq=0")
            self.assertEqual(pages, expected_seqs)
            self.assertEqual(post("/v1/messages", cursor={"before_seq": "0"})["messages"], [])


if __name__ == "__main__":
    unittest.main()
