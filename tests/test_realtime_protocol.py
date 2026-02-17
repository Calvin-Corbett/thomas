import unittest
from thomas.realtime.protocol import parse_json_message, ProtocolError


class TestProtocol(unittest.TestCase):
    def test_parse_valid(self):
        obj = parse_json_message('{"t":"hello","mode":"fast"}')
        self.assertEqual(obj["t"], "hello")
        self.assertIn("id", obj)
        self.assertIn("ts", obj)

    def test_parse_invalid(self):
        with self.assertRaises(ProtocolError):
            parse_json_message('[]')
