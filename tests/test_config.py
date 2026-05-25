import unittest

from openevent.view.config import ConfigError, parse_config


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = parse_config({})
        self.assertEqual(config.server.host, "127.0.0.1")
        self.assertEqual(config.server.port, 8080)
        self.assertEqual(config.openevent.target, "127.0.0.1:9527")
        self.assertEqual(config.history.default_order, "desc")

    def test_rejects_large_max_limit(self):
        with self.assertRaises(ConfigError):
            parse_config({"history": {"max_limit": 1001}})


if __name__ == "__main__":
    unittest.main()
