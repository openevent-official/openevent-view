import json
import threading
import unittest
from dataclasses import dataclass
from dataclasses import replace
from http.client import HTTPConnection

from openevent.view.config import ViewConfig, parse_config
from openevent.view.server import create_server


@dataclass
class FakeHistoryService:
    config: ViewConfig

    def query(self, query):
        return {
            "messages": [
                {
                    "seq": 2,
                    "ts_ms": 20,
                    "channel_id": 100,
                    "principal": query.principal,
                    "recipients": [],
                    "payload": {
                        "encoding": "utf-8",
                        "text": "{\"n\":2}",
                        "json": {"n": 2},
                        "truncated": False,
                        "size_bytes": 7,
                    },
                }
            ],
            "next_cursor": "2",
            "has_more": True,
            "order": query.order,
            "scanned": 1,
        }


class ServerTests(unittest.TestCase):
    def setUp(self):
        base_config = parse_config({"server": {"host": "127.0.0.1"}})
        self.config = replace(base_config, server=replace(base_config.server, port=0))
        self.server = create_server(self.config, FakeHistoryService(self.config))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_healthz(self):
        conn = HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(resp.read()), {"ok": True})
        conn.close()

    def test_messages_post(self):
        conn = HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request(
            "POST",
            "/v1/messages",
            body=json.dumps({"principal": 1, "token": "tok"}),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.read())
        self.assertEqual(body["messages"][0]["payload"]["json"], {"n": 2})
        self.assertEqual(body["next_cursor"], "2")
        conn.close()


if __name__ == "__main__":
    unittest.main()
