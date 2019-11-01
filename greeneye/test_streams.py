import logging
import sys
import unittest

from . import streams
from .packets import *
from .packet_test_data import read_packet, read_packets, assert_packet

logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format='%(asctime)s [%(name)s](%(levelname)s) %(message)s')


class TestPacketAccumulator(unittest.TestCase):
    def test_single_packet(self):
        packet_data = read_packet('BIN32-ABS.bin')
        accumulator = streams.PacketAccumulator()
        accumulator.put_bytes(packet_data)
        packet = accumulator.try_get_packet()
        assert_packet('BIN32-ABS.bin', packet)

    def test_header_only(self):
        packet_data = read_packet('BIN32-ABS.bin')
        accumulator = streams.PacketAccumulator()
        accumulator.put_bytes(packet_data[:2])
        packet = accumulator.try_get_packet()
        self.assertIsNone(packet)
        accumulator.put_bytes(packet_data[2:])
        packet = accumulator.try_get_packet()
        assert_packet('BIN32-ABS.bin', packet)

    def test_partial_packet(self):
        packet_data = read_packet('BIN32-ABS.bin')
        accumulator = streams.PacketAccumulator()
        accumulator.put_bytes(packet_data[:100])
        packet = accumulator.try_get_packet()
        self.assertIsNone(packet)
        accumulator.put_bytes(packet_data[100:])
        packet = accumulator.try_get_packet()
        assert_packet('BIN32-ABS.bin', packet)

    def test_time_packet(self):
        packet_data = read_packet('BIN48-NET-TIME_tricky.bin')
        accumulator = streams.PacketAccumulator()
        accumulator.put_bytes(packet_data)
        packet = accumulator.try_get_packet()
        assert_packet('BIN48-NET-TIME_tricky.bin', packet)

    def test_partial_time_packet(self):
        packet_data = read_packet('BIN48-NET-TIME_tricky.bin')
        accumulator = streams.PacketAccumulator()
        accumulator.put_bytes(packet_data[:BIN48_NET.size])
        packet = accumulator.try_get_packet()
        self.assertIsNone(packet)
        accumulator.put_bytes(packet_data[BIN48_NET.size:])
        packet = accumulator.try_get_packet()
        assert_packet('BIN48-NET-TIME_tricky.bin', packet)

    def test_multiple_packets(self):
        packet_data = read_packets(['BIN32-ABS.bin', 'BIN32-NET.bin', 'BIN48-NET.bin', 'BIN48-NET-TIME.bin'])
        accumulator = streams.PacketAccumulator()
        accumulator.put_bytes(packet_data)
        packet = accumulator.try_get_packet()
        assert_packet('BIN32-ABS.bin', packet)
        packet = accumulator.try_get_packet()
        assert_packet('BIN32-NET.bin', packet)
        packet = accumulator.try_get_packet()
        assert_packet('BIN48-NET.bin', packet)
        packet = accumulator.try_get_packet()
        assert_packet('BIN48-NET-TIME.bin', packet)

    def test_multiple_packets_with_junk(self):
        accumulator = streams.PacketAccumulator()
        accumulator.put_bytes(read_packet('BIN32-ABS.bin'))
        accumulator.put_bytes(bytes.fromhex('feff05'))
        accumulator.put_bytes(read_packet('BIN32-NET.bin'))
        accumulator.put_bytes(bytes.fromhex('feff01'))
        accumulator.put_bytes(read_packet('BIN48-NET.bin'))
        accumulator.put_bytes(bytes.fromhex('23413081afb134870dacea'))
        accumulator.put_bytes(read_packet('BIN48-NET-TIME.bin'))
        packet = accumulator.try_get_packet()
        assert_packet('BIN32-ABS.bin', packet)
        packet = accumulator.try_get_packet()
        assert_packet('BIN32-NET.bin', packet)
        packet = accumulator.try_get_packet()
        assert_packet('BIN48-NET.bin', packet)
        packet = accumulator.try_get_packet()
        assert_packet('BIN48-NET-TIME.bin', packet)
