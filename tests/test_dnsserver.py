import os
import socket
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WlanNetwork import dnsserver
from WlanNetwork.dnsserver import CatchAllDnsServer, build_response

_IP = bytes([192, 168, 4, 1])


def _query(name, qtype=1, query_id=0x1234):
    labels = b''.join(bytes([len(part)]) + part.encode('ascii') for part in name.split('.'))
    header = struct.pack('>HHHHHH', query_id, 0x0100, 1, 0, 0, 0)  # recursion desired
    return header + labels + b'\x00' + struct.pack('>HH', qtype, 1)


class BuildResponseTests(unittest.TestCase):
    def test_a_query_is_answered_with_the_device_ip(self):
        query = _query('captain-nemo-setup')

        response = build_response(query, _IP)

        query_id, flags, qdcount, ancount = struct.unpack('>HHHH', response[:8])
        self.assertEqual(query_id, 0x1234)
        self.assertTrue(flags & 0x8000, "must be marked as a response")
        self.assertEqual((qdcount, ancount), (1, 1))
        self.assertEqual(response[-4:], _IP)

    def test_any_other_name_is_answered_too(self):
        """Phones' connectivity checks must resolve as well, otherwise
        they send DNS over mobile data and captain-nemo-setup stops
        resolving (see module docstring)."""
        response = build_response(_query('connectivitycheck.gstatic.com'), _IP)

        self.assertEqual(response[-4:], _IP)

    def test_aaaa_query_gets_an_empty_answer(self):
        response = build_response(_query('captain-nemo-setup', qtype=28), _IP)

        ancount = struct.unpack('>H', response[6:8])[0]
        self.assertEqual(ancount, 0)

    def test_short_packet_is_ignored(self):
        self.assertIsNone(build_response(b'\x00\x01\x02', _IP))

    def test_response_packet_is_not_answered(self):
        query = bytearray(_query('captain-nemo-setup'))
        query[2] |= 0x80

        self.assertIsNone(build_response(bytes(query), _IP))

    def test_truncated_name_is_ignored(self):
        query = _query('captain-nemo-setup')

        self.assertIsNone(build_response(query[:20], _IP))

    def test_question_without_name_terminator_is_ignored(self):
        header = struct.pack('>HHHHHH', 1, 0x0100, 1, 0, 0, 0)

        self.assertIsNone(build_response(header + b'\x05abc', _IP))


class CatchAllDnsServerTests(unittest.TestCase):
    def test_answers_a_real_udp_query(self):
        with patch.object(dnsserver, '_DNS_PORT', 0):  # any free port, 53 needs root
            server = CatchAllDnsServer('192.168.4.1')
            server.start()
        self.addCleanup(server.stop)
        port = server._socket.getsockname()[1]

        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(client.close)
        client.settimeout(2)
        client.sendto(_query('captain-nemo-setup'), ('127.0.0.1', port))
        for _ in range(50):
            server.poll()
            try:
                response, _ = client.recvfrom(512)
                break
            except socket.timeout:
                pass
        self.assertEqual(response[-4:], _IP)

    def test_poll_without_pending_query_returns_immediately(self):
        with patch.object(dnsserver, '_DNS_PORT', 0):
            server = CatchAllDnsServer('192.168.4.1')
            server.start()
        self.addCleanup(server.stop)

        server.poll()  # must not block

    def test_poll_before_start_does_nothing(self):
        CatchAllDnsServer('192.168.4.1').poll()


if __name__ == "__main__":
    unittest.main()
