import io
import json
import socket
import struct
import threading
import types
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

import grpc

from openevent.view.config import parse_config
from openevent.view.history import HistoryService, QueryTimeout
from openevent.view.server import _grpc_to_http, create_server


def message(seq, payload=b'{"n":1}'):
    return types.SimpleNamespace(
        seq=seq,
        uuid=1000 + seq,
        ts_ms=1700000000000 + seq,
        channel_id=7,
        principal=100,
        recipients=[100],
        payload=payload,
        object_keys=[types.SimpleNamespace(object_id=900 + seq, object_token="secret")],
    )


class FakeClient:
    def __init__(self):
        system = message(0, payload=b'{"kind":"system.initialization"}')
        system.uuid = system.principal = system.channel_id = 0
        system.recipients = system.object_keys = []
        self.messages = [system, message(1)]

    def get_status(self, principal, token, *, timeout):
        return types.SimpleNamespace(min_seq=0, max_seq=1)

    def get_channel(self, principal, token, channel_id, *, timeout):
        return types.SimpleNamespace(
            channel=types.SimpleNamespace(name="events", protocol="chat.v1")
        )

    def fetch(
        self,
        principal,
        token,
        from_seq,
        limit,
        only_my_recipient=False,
        channels=(),
        *,
        timeout,
    ):
        messages = [
            item
            for item in self.messages
            if item.seq >= from_seq and (not channels or item.channel_id in channels)
        ][:limit]
        return types.SimpleNamespace(
            messages=messages,
            next_seq=messages[-1].seq + 1 if messages else 2,
            last_seq=1,
        )


class FakeRpcError(grpc.RpcError):
    def __init__(self, status_code):
        self._status_code = status_code

    def code(self):
        return self._status_code


class ServerTests(unittest.TestCase):
    def setUp(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        config = parse_config({"server": {"port": port}})
        self.client = FakeClient()
        self.history = HistoryService(self.client, config.history)
        self.server = create_server(config, self.history)
        self.server.server_activate()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.history.close()
        self.thread.join()

    def request(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_address[1])
        payload = None if body is None else json.dumps(body)
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        conn.request(method, path, payload, headers)
        response = conn.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        conn.close()
        return result

    def request_json(self, method, path, body=None):
        status, headers, data = self.request(method, path, body)
        return status, headers, json.loads(data) if data else None

    def test_only_documented_routes(self):
        status, _, _ = self.request("GET", "/v1/messages")
        self.assertEqual(status, 404)
        status, _, _ = self.request("GET", "/healthz")
        self.assertEqual(status, 404)

    def test_messages_response_is_no_store_and_hides_object_tokens(self):
        status, headers, body = self.request_json(
            "POST", "/v1/messages", {"principal": "100", "token": "t"}
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(body["messages"][0]["seq"], "1")
        self.assertEqual(body["messages"][0]["object_ids"], ["901"])
        self.assertNotIn("secret", json.dumps(body))

    def test_payload_response_is_no_store_and_returns_complete_content(self):
        status, headers, body = self.request_json(
            "POST", "/v1/messages/1/payload", {"principal": "100", "token": "t"}
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertFalse(body["message"]["payload"]["truncated"])
        self.assertEqual(body["message"]["payload"]["text"], '{"n":1}')

    def test_list_and_detail_return_original_json_text_without_parsing_it(self):
        payloads = [
            b"[" * 300 + b"0" + b"]" * 300,
            b'{"n":9007199254740993,"n":123456789012345678901234567890}',
            b'  {\n  "value" : "\\u4e2d", "items": [ 1, 2 ]\n}\n',
        ]
        self.assertEqual(len(payloads[0]), 601)
        for payload in payloads:
            self.client.messages[1].payload = payload
            for path in ("/v1/messages", "/v1/messages/1/payload"):
                with self.subTest(payload=payload, path=path):
                    status, _, body = self.request_json(
                        "POST", path, {"principal": "100", "token": "t"}
                    )
                    self.assertEqual(status, 200)
                    item = body["messages"][0] if path == "/v1/messages" else body["message"]
                    self.assertEqual(item["payload"]["text"], payload.decode("utf-8"))
                    self.assertEqual(item["payload"]["encoding"], "utf-8")
                    self.assertEqual(item["payload"]["size_bytes"], len(payload))
                    self.assertFalse(item["payload"]["truncated"])
                    self.assertNotIn("json", item["payload"])

    def test_post_requires_json_body(self):
        status, _, body = self.request_json("POST", "/v1/messages")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "INVALID_ARGUMENT")

    def test_payload_and_page_routes_accept_system_sequence(self):
        status, _, body = self.request_json(
            "POST", "/v1/messages/0/payload", {"principal": "1", "token": "t"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["message"]["seq"], "0")
        self.assertEqual(body["message"]["payload"]["text"], '{"kind":"system.initialization"}')
        status, _, _ = self.request("GET", "/message?seq=0")
        self.assertEqual(status, 200)

    def test_total_query_timeout_maps_to_gateway_timeout(self):
        def timed_out(query):
            raise QueryTimeout("history query timed out")

        self.history.query = timed_out
        with patch("openevent.view.server.LOGGER.exception") as log_exception:
            status, _, body = self.request_json(
                "POST", "/v1/messages", {"principal": "100", "token": "t"}
            )
        log_exception.assert_not_called()
        self.assertEqual(status, 504)
        self.assertEqual(body["error"]["code"], "QUERY_TIMEOUT")

    def test_client_reset_after_query_starts_finishes_without_another_response(self):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def query(_query):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test did not release the query")
            return {"messages": [], "next_cursor": None}

        process_request = self.server.process_request_thread

        def track_request(*args):
            try:
                process_request(*args)
            finally:
                finished.set()

        handler_class = self.server.RequestHandlerClass
        send_response = handler_class.send_response
        with (
            patch.object(self.history, "query", side_effect=query),
            patch.object(self.server, "process_request_thread", side_effect=track_request),
            patch.object(self.server, "handle_error") as handle_error,
            patch("openevent.view.server.LOGGER.exception") as log_exception,
            patch.object(handler_class, "send_response", autospec=True, side_effect=send_response) as responses,
        ):
            client = socket.create_connection(self.server.server_address, timeout=2)
            try:
                body = b'{"principal":"100","token":"t"}'
                client.sendall(
                    b"POST /v1/messages HTTP/1.1\r\nHost: localhost\r\n"
                    b"Content-Type: application/json\r\nContent-Length: "
                    + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
                )
                self.assertTrue(entered.wait(5), "request never entered the query")
                client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                client.close()
            finally:
                client.close()
                release.set()
            self.assertTrue(finished.wait(5), "request thread did not finish after disconnect")
            log_exception.assert_not_called()
            handle_error.assert_not_called()
            statuses = [call.args[1] for call in responses.call_args_list]
            self.assertLessEqual(len(statuses), 1)
            self.assertNotIn(500, statuses)

    def test_response_write_failures_close_connection_without_second_response(self):
        class FailingWriter:
            def __init__(self, fail_at, error):
                self.fail_at = fail_at
                self.error = error
                self.attempts = 0
                self.written = []

            def write(self, data):
                self.attempts += 1
                if self.attempts == self.fail_at:
                    raise self.error("client cannot receive the response")
                self.written.append(data)
                return len(data)

            def flush(self):
                pass

        for method, path, expected_status in (
            ("GET", "/static/app.js", 200),
            ("POST", "/v1/messages", 400),
        ):
            for fail_at in (1, 2):
                for error in (BrokenPipeError, ConnectionResetError, socket.timeout):
                    with self.subTest(method=method, fail_at=fail_at, error=error.__name__):
                        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
                        handler.server = self.server
                        handler.protocol_version = "HTTP/1.1"
                        handler.rfile = io.BytesIO(
                            f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode("ascii")
                        )
                        handler.close_connection = False
                        writer = FailingWriter(fail_at, error)
                        handler.wfile = writer
                        with (
                            patch.object(handler, "send_response", wraps=handler.send_response) as responses,
                            patch("openevent.view.server.LOGGER.exception") as log_exception,
                        ):
                            handler.handle_one_request()
                        self.assertEqual([call.args[0] for call in responses.call_args_list], [expected_status])
                        self.assertEqual(writer.attempts, fail_at)
                        self.assertTrue(handler.close_connection)
                        log_exception.assert_not_called()
                        if fail_at == 2:
                            self.assertEqual(b"".join(writer.written).count(b"HTTP/1.1 "), 1)

    def test_request_body_timeout_still_returns_request_timeout(self):
        get_request = self.server.get_request

        def short_read_timeout():
            request, address = get_request()
            request.settimeout(0.05)
            return request, address

        with (
            patch.object(self.server, "get_request", side_effect=short_read_timeout),
            patch("openevent.view.server.LOGGER.exception") as log_exception,
        ):
            connection = HTTPConnection(*self.server.server_address, timeout=2)
            try:
                connection.request(
                    "POST", "/v1/messages", body=b"{",
                    headers={"Content-Type": "application/json", "Content-Length": "100"},
                )
                response = connection.getresponse()
                body = json.loads(response.read())
            finally:
                connection.close()
            self.assertEqual(response.status, 408)
            self.assertEqual(body["error"]["code"], "REQUEST_TIMEOUT")
            log_exception.assert_not_called()

    def test_internal_query_failure_still_returns_500_and_logs_error(self):
        with (
            patch.object(self.history, "query", side_effect=RuntimeError("query failed")),
            self.assertLogs("openevent.view.server", level="ERROR") as logs,
        ):
            status, _, body = self.request_json(
                "POST", "/v1/messages", {"principal": "100", "token": "t"}
            )
        self.assertEqual(status, 500)
        self.assertEqual(body["error"]["code"], "INTERNAL")
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].getMessage(), "request failed")
        self.assertIs(logs.records[0].exc_info[0], RuntimeError)

    def test_non_advancing_open_event_cursor_maps_to_bad_gateway(self):
        class BadFetchClient(FakeClient):
            def fetch(self, *args, **kwargs):
                return types.SimpleNamespace(messages=[], next_seq=kwargs["from_seq"], last_seq=1)

        self.history.close()
        self.history = HistoryService(BadFetchClient(), self.server.config.history)
        self.server.history_service = self.history
        status, _, body = self.request_json(
            "POST", "/v1/messages", {"principal": "100", "token": "t"}
        )

        self.assertEqual(status, 502)
        self.assertEqual(body["error"]["code"], "BAD_GATEWAY")

    def test_unlisted_upstream_grpc_errors_map_to_bad_gateway(self):
        for code in (grpc.StatusCode.INVALID_ARGUMENT, grpc.StatusCode.RESOURCE_EXHAUSTED):
            with self.subTest(code=code):
                self.assertEqual(
                    _grpc_to_http(FakeRpcError(code)),
                    (502, code.name),
                )

    def test_rejects_oversized_request_body(self):
        conn = HTTPConnection("127.0.0.1", self.server.server_address[1])
        conn.request(
            "POST",
            "/v1/messages",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(
                    self.server.config.server.max_request_body_bytes + 1
                ),
            },
        )
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()

        self.assertEqual(response.status, 413)
        self.assertEqual(body["error"]["code"], "REQUEST_TOO_LARGE")

    def test_frontend_includes_non_destructive_error_and_filter_context(self):
        status, _, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'id="errorBanner"', page)

        status, _, script = self.request("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"only messages addressed to this principal", script)
        self.assertIn(b'["objects", (message.object_ids || []).join', script)
        self.assertNotIn(b"list.replaceChildren(node)", script)


if __name__ == "__main__":
    unittest.main()
