import base64
import types
import unittest
import weakref
import threading
from unittest.mock import patch

import grpc

from openevent.view.config import HistoryConfig
from openevent.view.history import (
    HistoryService,
    MessageNotFound,
    PayloadQuery,
    QueryTimeout,
    RequestError,
    UpstreamProtocolError,
    encode_payload,
    parse_history_query,
    parse_payload_query,
    parse_seq,
)


def message(seq, channel=7, payload=b'{"n":1}', principal=100, recipients=(100,)):
    if seq == 0:
        return types.SimpleNamespace(
            seq=0, uuid=0, ts_ms=1700000000000, channel_id=0, principal=0,
            recipients=[], object_keys=[],
            payload=b'{"kind":"system.initialization","data":{"schema_version":1},"timestamps":{"event_ms":1700000000000}}',
        )
    return types.SimpleNamespace(
        seq=seq,
        uuid=seq + 1000,
        ts_ms=1700000000000 + seq,
        channel_id=channel,
        principal=principal,
        recipients=list(recipients),
        payload=payload,
        object_keys=[
            types.SimpleNamespace(object_id=900 + seq, object_token="secret-token")
        ],
    )


class FakeRpcError(grpc.RpcError):
    def __init__(self, status_code):
        self._status_code = status_code

    def code(self):
        return self._status_code


class FakeClient:
    def __init__(self, messages, min_seq=0, max_seq=None):
        self.messages = sorted([message(0)] + list(messages), key=lambda item: item.seq)
        self.min_seq = min_seq
        self.max_seq = max_seq if max_seq is not None else (
            self.messages[-1].seq if self.messages else 0
        )
        self.calls = []
        self.channels = {}
        self.timeouts = []

    def get_status(self, principal, token, *, timeout):
        self.timeouts.append(timeout)
        self.calls.append(("status", principal, token))
        return types.SimpleNamespace(min_seq=self.min_seq, max_seq=self.max_seq)

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
        self.calls.append(("fetch", from_seq, limit, only_my_recipient, channels))
        self.timeouts.append(timeout)
        visible = [
            item
            for item in self.messages
            if item.seq >= from_seq
            and (not channels or item.channel_id in channels)
            and (
                not only_my_recipient
                or principal in {int(recipient) for recipient in item.recipients}
            )
        ][:limit]
        next_seq = visible[-1].seq + 1 if visible else self.max_seq + 1
        return types.SimpleNamespace(
            messages=visible,
            next_seq=next_seq,
            last_seq=self.max_seq,
        )

    def get_channel(self, principal, token, channel_id, *, timeout):
        self.timeouts.append(timeout)
        self.calls.append(("channel", channel_id))
        name, protocol = self.channels.get(
            channel_id, ("system", "system.v1") if channel_id == 0 else (f"channel-{channel_id}", "chat.v1")
        )
        return types.SimpleNamespace(
            channel=types.SimpleNamespace(name=name, protocol=protocol)
        )


class ShortPageClient(FakeClient):
    def fetch(self, *args, **kwargs):
        from_seq = kwargs["from_seq"]
        self.calls.append(
            (
                "fetch",
                from_seq,
                kwargs["limit"],
                kwargs["only_my_recipient"],
                kwargs["channels"],
            )
        )
        scripted = {
            1: ([self.messages[1]], 3),
            3: ([], 4),
            4: ([self.messages[2]], 5),
        }
        messages, next_seq = scripted[from_seq]
        return types.SimpleNamespace(
            messages=messages,
            next_seq=next_seq,
            last_seq=self.max_seq,
        )


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.config = HistoryConfig(default_limit=2, max_limit=10, fetch_batch_size=2)

    def make_service(self, client, config=None):
        service = HistoryService(client, config or self.config)
        self.addCleanup(service.close)
        return service

    def test_query_authenticates_at_the_history_boundary(self):
        client = FakeClient([message(1)], max_seq=1)
        result = self.make_service(client).query(
            parse_history_query(
                {
                    "principal": "100",
                    "token": "t",
                    "cursor": {"before_seq": "0"},
                },
                self.config,
            )
        )
        self.assertEqual(result["messages"], [])
        self.assertEqual(client.calls[0][0], "status")

    def test_descending_cursor_scans_multiple_windows_without_skipping(self):
        config = HistoryConfig(default_limit=3, max_limit=10, fetch_batch_size=2)
        client = FakeClient([message(seq) for seq in range(1, 6)])
        service = self.make_service(client, config)

        first = service.query(parse_history_query({"principal": "100", "token": "t"}, config))
        second = service.query(
            parse_history_query(
                {
                    "principal": "100",
                    "token": "t",
                    "cursor": first["next_cursor"],
                },
                config,
            )
        )

        self.assertEqual([item["seq"] for item in first["messages"]], ["5", "4", "3"])
        self.assertEqual(first["next_cursor"], {"before_seq": "3"})
        self.assertEqual([item["seq"] for item in second["messages"]], ["2", "1", "0"])
        self.assertIsNone(second["next_cursor"])

    def test_short_fetch_pages_are_completed_before_descending_selection(self):
        client = ShortPageClient([message(2), message(4)], max_seq=4)
        result = self.make_service(client).query(
            parse_history_query({"principal": "100", "token": "t"}, self.config)
        )

        self.assertEqual([item["seq"] for item in result["messages"]], ["4", "2"])
        self.assertEqual(
            [call[1] for call in client.calls if call[0] == "fetch"], [3, 4, 1]
        )

    def test_recipient_filter_scans_past_nonmatching_messages(self):
        client = FakeClient(
            [
                message(1, recipients=(100,)),
                message(2, recipients=(100,)),
                message(3, recipients=(200,)),
            ]
        )
        result = self.make_service(client).query(
            parse_history_query(
                {
                    "principal": "100",
                    "token": "t",
                    "only_my_recipient": True,
                },
                self.config,
            )
        )

        self.assertEqual([item["seq"] for item in result["messages"]], ["2", "1"])
        self.assertIsNone(result["next_cursor"])

    def test_channel_filter_at_boundary_still_loads_display_metadata(self):
        client = FakeClient([], max_seq=5)
        result = self.make_service(client).query(
            parse_history_query(
                {
                    "principal": "100",
                    "token": "t",
                    "channel_id": "7",
                    "cursor": {"before_seq": "0"},
                },
                self.config,
            )
        )

        self.assertEqual(result["channel"]["channel_name"], "channel-7")
        self.assertIn(("channel", 7), client.calls)

    def test_message_projection_hides_object_tokens(self):
        client = FakeClient([message(1)])
        result = self.make_service(client).query(
            parse_history_query({"principal": "100", "token": "t"}, self.config)
        )

        serialized = result["messages"][0]
        self.assertEqual(serialized["object_ids"], ["901"])
        self.assertNotIn("object_keys", serialized)
        self.assertNotIn("secret-token", str(serialized))

    def test_payload_lookup_returns_full_payload(self):
        payload = b"x" * 20000
        client = FakeClient([message(2, payload=payload)], max_seq=2)
        result = self.make_service(client).get_payload(
            2, PayloadQuery(principal=100, token="t")
        )

        self.assertEqual(result["message"]["payload"]["text"], "x" * 20000)
        self.assertFalse(result["message"]["payload"]["truncated"])
        self.assertEqual(result["message"]["object_ids"], ["902"])

    def test_payload_lookup_hides_permission_denied_as_not_found(self):
        class DeniedClient(FakeClient):
            def fetch(self, *args, **kwargs):
                raise FakeRpcError(grpc.StatusCode.PERMISSION_DENIED)

        service = self.make_service(DeniedClient([message(2)], max_seq=2))
        with self.assertRaises(MessageNotFound):
            service.get_payload(2, PayloadQuery(principal=100, token="t"))

    def test_large_payload_preview_preserves_byte_boundaries(self):
        text_payload = b"a" * 8191 + "€".encode("utf-8") + b"b" * 9000
        preview = encode_payload(text_payload)
        self.assertEqual(preview["encoding"], "utf-8")
        self.assertEqual(preview["preview"]["head_bytes"], 8191)
        self.assertEqual(preview["preview"]["head"], "a" * 8191)

        binary_preview = encode_payload(b"\xff" * 17000)
        self.assertEqual(binary_preview["encoding"], "base64")
        self.assertEqual(
            len(base64.b64decode(binary_preview["preview"]["head"])), 8192
        )

    def test_complete_payload_preserves_original_text_and_binary(self):
        payloads = [
            b'{"n":9007199254740993,"n":123456789012345678901234567890}',
            b'  {\n  "value" : "\\u4e2d", "items": [ 1, 2 ]\n}\n',
            b"[" * 300 + b"0" + b"]" * 300,
            b"/w==",
            b"\xff",
        ]
        for payload in payloads:
            for full in (False, True):
                with self.subTest(payload=payload, full=full):
                    result = encode_payload(payload, full=full)
                    encoding = "base64" if payload == b"\xff" else "utf-8"
                    expected = (
                        base64.b64encode(payload).decode("ascii")
                        if encoding == "base64" else payload.decode("utf-8")
                    )
                    self.assertEqual(result["encoding"], encoding)
                    self.assertEqual(result["text"], expected)
                    self.assertEqual(result["size_bytes"], len(payload))
                    self.assertFalse(result["truncated"])
                    self.assertNotIn("json", result)

    def test_strict_history_query_parsing(self):
        with self.assertRaises(RequestError):
            parse_history_query({"principal": 100, "token": "t"}, self.config)
        with self.assertRaises(RequestError):
            parse_history_query(
                {
                    "principal": "100",
                    "token": "t",
                    "cursor": {"before_seq": "01"},
                },
                self.config,
            )
        with self.assertRaises(RequestError):
            parse_history_query(
                {"principal": "100", "token": "t", "limit": True}, self.config
            )
        self.assertEqual(
            parse_payload_query({"principal": "100", "token": "t"}).principal, 100
        )
        self.assertEqual(parse_seq("42"), 42)
        self.assertEqual(parse_seq("0"), 0)
        with self.assertRaises(RequestError):
            parse_payload_query({"principal": "0", "token": "t"})

    def test_initialization_is_visible_in_history_channel_filter_and_detail(self):
        service = self.make_service(FakeClient([]))
        query = parse_history_query({"principal": "100", "token": "t", "channel_id": "0"}, self.config)
        result = service.query(query)
        self.assertEqual([row["seq"] for row in result["messages"]], ["0"])
        self.assertEqual(result["channel"]["channel_protocol"], "system.v1")
        self.assertIsNone(result["next_cursor"])
        detail = service.get_payload(0, PayloadQuery(100, "t"))
        self.assertEqual(detail["message"]["payload"]["text"], message(0).payload.decode("utf-8"))

    def test_fixed_windows_do_not_shrink_for_last_matching_message(self):
        config = HistoryConfig(default_limit=2, max_limit=10, fetch_batch_size=100)
        client = FakeClient([
            message(seq, channel=7 if seq in {1, 1001} else 8)
            for seq in range(1, 1002)
        ])
        result = self.make_service(client, config).query(parse_history_query(
            {"principal": "100", "token": "t", "channel_id": "7"}, config,
        ))
        self.assertEqual([row["seq"] for row in result["messages"]], ["1001", "1"])
        fetches = [call for call in client.calls if call[0] == "fetch"]
        self.assertEqual(len(fetches), 11)
        self.assertEqual({call[2] for call in fetches}, {100})
        self.assertIsNone(result["next_cursor"])

    def test_page_cut_inside_a_large_window_keeps_older_matches(self):
        config = HistoryConfig(default_limit=2, max_limit=10, fetch_batch_size=100)
        service = self.make_service(FakeClient([message(seq) for seq in range(1, 5)]), config)
        data = {"principal": "100", "token": "t"}
        pages = []
        while True:
            result = service.query(parse_history_query(data, config))
            pages.extend(row["seq"] for row in result["messages"])
            if result["next_cursor"] is None:
                break
            data["cursor"] = result["next_cursor"]
        self.assertEqual(pages, ["4", "3", "2", "1", "0"])

    def test_dense_window_only_encodes_payloads_needed_for_the_page(self):
        config = HistoryConfig(default_limit=100, max_limit=1000, fetch_batch_size=1000)
        client = FakeClient([message(seq) for seq in range(1, 1001)])
        service = self.make_service(client, config)
        with patch("openevent.view.history.encode_payload", wraps=encode_payload) as encode:
            result = service.query(parse_history_query({"principal": "100", "token": "t"}, config))
        self.assertEqual([row["seq"] for row in result["messages"]], [str(seq) for seq in range(1000, 900, -1)])
        self.assertEqual(result["next_cursor"], {"before_seq": "901"})
        self.assertEqual(encode.call_count, 100)
        self.assertEqual(len([call for call in client.calls if call[0] == "fetch"]), 1)

    def test_short_responses_in_one_window_keep_latest_page_without_losing_older_pages(self):
        class LimitedPageClient(FakeClient):
            def fetch(inner, *args, **kwargs):
                kwargs["limit"] = min(kwargs["limit"], 80)
                return super().fetch(*args, **kwargs)

        config = HistoryConfig(default_limit=100, max_limit=1000, fetch_batch_size=1000)
        client = LimitedPageClient([message(seq) for seq in range(1, 300)])
        service = self.make_service(client, config)
        data = {"principal": "100", "token": "t"}
        for newest, oldest in ((299, 200), (199, 100), (99, 0)):
            result = service.query(parse_history_query(data, config))
            self.assertEqual(
                [row["seq"] for row in result["messages"]],
                [str(seq) for seq in range(newest, oldest - 1, -1)],
            )
            expected_cursor = {"before_seq": str(oldest)} if oldest else None
            self.assertEqual(result["next_cursor"], expected_cursor)
            data["cursor"] = result["next_cursor"]

    def test_previous_rpc_payload_is_released_before_next_fetch(self):
        class EphemeralMessage:
            pass

        class EphemeralClient(FakeClient):
            previous = None

            def fetch(inner, *args, **kwargs):
                if inner.previous is not None:
                    self.assertIsNone(inner.previous(), "raw payload retained across Fetch calls")
                item = EphemeralMessage()
                item.__dict__.update(vars(message(kwargs["from_seq"], payload=b"x" * 20000)))
                inner.previous = weakref.ref(item)
                return types.SimpleNamespace(messages=[item], next_seq=item.seq + 1, last_seq=3)

        config = HistoryConfig(default_limit=3, max_limit=10, fetch_batch_size=1)
        result = self.make_service(EphemeralClient([], max_seq=3), config).query(
            parse_history_query({"principal": "100", "token": "t"}, config)
        )
        self.assertTrue(all(row["payload"]["truncated"] for row in result["messages"]))

    def test_query_budget_stops_scanning_even_when_individual_rpcs_succeed(self):
        now = [0.0]

        class SlowClient(FakeClient):
            def fetch(inner, *args, **kwargs):
                result = super().fetch(*args, **kwargs)
                now[0] += 0.6
                return result

        config = HistoryConfig(default_limit=3, max_limit=10, fetch_batch_size=1)
        client = SlowClient([message(seq) for seq in range(1, 4)])
        service = HistoryService(client, config, query_timeout_seconds=1, rpc_timeout_seconds=10)
        self.addCleanup(service.close)
        with patch("openevent.view.history.time.monotonic", side_effect=lambda: now[0]):
            with self.assertRaises(QueryTimeout):
                service.query(parse_history_query({"principal": "100", "token": "t"}, config))
        self.assertEqual(len([call for call in client.calls if call[0] == "fetch"]), 2)
        self.assertAlmostEqual(client.timeouts[-1], 0.4)

    def test_channel_queue_wait_is_part_of_the_same_query_budget(self):
        client = FakeClient([message(1)])
        service = HistoryService(client, self.config, channel_lookup_workers=1, query_timeout_seconds=0.05)
        release = threading.Event()
        occupied = threading.Event()
        queued = []

        def occupy_worker():
            occupied.set()
            release.wait(5)

        service._channel_executor.submit(occupy_worker)
        self.assertTrue(occupied.wait(1))
        submit = service._channel_executor.submit

        def track_queued(*args, **kwargs):
            future = submit(*args, **kwargs)
            queued.append(future)
            return future

        try:
            with patch.object(service._channel_executor, "submit", side_effect=track_queued):
                with self.assertRaises(QueryTimeout):
                    service.query(parse_history_query({"principal": "100", "token": "t"}, self.config))
            self.assertTrue(queued)
            self.assertTrue(all(future.cancelled() for future in queued))
        finally:
            release.set()
            service.close()
        self.assertFalse(any(call[0] == "channel" for call in client.calls))

    def test_fetch_progress_is_required(self):
        class BadClient(FakeClient):
            def fetch(self, *args, **kwargs):
                return types.SimpleNamespace(
                    messages=[],
                    next_seq=kwargs["from_seq"],
                    last_seq=self.max_seq,
                )

        service = self.make_service(BadClient([message(1), message(2), message(3)]))
        with self.assertRaises(UpstreamProtocolError):
            service.query(
                parse_history_query({"principal": "100", "token": "t"}, self.config)
            )


if __name__ == "__main__":
    unittest.main()
