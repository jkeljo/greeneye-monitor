import datetime
from io import StringIO
import os
import unittest

from .packet_test_data import read_packet, assert_packet
from . import packets


class TestPacketFormats(unittest.TestCase):
    def test_bin32_abs(self):
        test_packet(
            'BIN32-ABS.bin',
            packets.BIN32_ABS)

    def test_bin32_net(self):
        test_packet(
            'BIN32-NET.bin',
            packets.BIN32_NET)

    def test_bin48_abs(self):
        test_packet(
            'BIN48-ABS.bin',
            packets.BIN48_ABS)

    def test_bin48_net(self):
        test_packet(
            'BIN48-NET.bin',
            packets.BIN48_NET)

    def test_bin48_net_time(self):
        test_packet(
            'BIN48-NET-TIME.bin',
            packets.BIN48_NET_TIME)

    def test_bin48_net_time_tricky(self):
        """BIN48_NET and BIN48_NET_TIME packets both have the same packet type
        code, so in order to detect the difference you must try to parse as
        BIN48_NET first, and if that fails try BIN48_NET_TIME. However, if
        the parser just checks the checksum and not the footer, it's possible
        for a BIN48_NET_TIME packet to be mistaken for a BIN48_NET. This is
        one such packet."""
        try:
            parse_packet('BIN48-NET-TIME_tricky.bin', packets.BIN48_NET)
            self.fail('Should have thrown')
        except packets.MalformedPacketException as e:
            pass

        test_packet(
            'BIN48-NET-TIME_tricky.bin',
            packets.BIN48_NET_TIME)

    def test_short_packet(self):
        packet = read_packet('BIN32-NET.bin')
        with self.assertRaisesRegex(packets.MalformedPacketException,
                                    'Packet too short.'):
            packets.BIN32_NET.parse(packet[:-1])

    def test_packet_with_extra_after(self):
        data = bytearray()
        data.extend(read_packet('BIN32-NET.bin'))
        data.extend(read_packet('BIN32-ABS.bin'))

        packet = packets.BIN32_NET.parse(data)
        assert_packet('BIN32-NET.bin', packet)

def test_packet(packet_file_name, packet_format):
    packet = parse_packet(packet_file_name, packet_format)

    assert_packet(packet_file_name, packet)


def parse_packet(packet_file_name, packet_format):
    return packet_format.parse(read_packet(packet_file_name))


if __name__ == '__main__':
    unittest.main(defaultTest=TestPacketFormats)
