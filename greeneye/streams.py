import logging

import asyncio

from .packets import *

LOG = logging.getLogger(__name__)

PACKET_HEADER = bytes.fromhex('feff')


class PacketAccumulator(object):
    """Searches for packets in accumulated data."""

    def __init__(self):
        self._buffer = bytearray()

    def put_bytes(self, chunk: bytes):
        self._buffer.extend(chunk)

    def try_get_packet(self):
        while len(self._buffer) > 0:
            def skip_malformed_packet(msg, *args, **kwargs):
                LOG.debug(
                    'Skipping malformed packet due to ' + msg + '. Buffer contents: %s',
                    *args, self._buffer)
                del self._buffer[0:len(PACKET_HEADER)]

            header_index = self._buffer.find(PACKET_HEADER)
            if header_index == -1:
                LOG.debug(
                    'No header found. Discarding junk data: %s', self._buffer)
                self._buffer.clear()
                continue
            del self._buffer[0:header_index]

            if len(self._buffer) < len(PACKET_HEADER) + 1:
                # Not enough length yet
                LOG.debug(
                    'Not enough data in buffer yet ({} bytes): {}'.format(
                        len(self._buffer), self._buffer))
                return None

            format_code = self._buffer[len(PACKET_HEADER)]
            if format_code == 8:
                packet_format = BIN32_ABS
            elif format_code == 7:
                packet_format = BIN32_NET
            elif format_code == 6:
                packet_format = BIN48_ABS
            elif format_code == 5:
                packet_format = BIN48_NET
            else:
                skip_malformed_packet('unknown format code 0x%x', format_code)
                continue

            if len(self._buffer) < packet_format.size:
                # Not enough length yet
                LOG.debug('Not enough data in buffer yet ({} bytes)'.format(
                    len(self._buffer)))
                return None

            try:
                result = None
                try:
                    result = packet_format.parse(self._buffer)
                except MalformedPacketException:
                    if packet_format != BIN48_NET:
                        raise

                if result is None:
                    if len(self._buffer) < BIN48_NET_TIME.size:
                        # Not enough length yet
                        LOG.debug(
                            'Not enough data in buffer yet ({} bytes)'.format(
                                len(self._buffer)))
                        return None

                    result = BIN48_NET_TIME.parse(self._buffer)

                LOG.debug(
                    'Parsed one {} packet.'.format(result.packet_format.name))
                del self._buffer[0:result.packet_format.size]
                return result
            except MalformedPacketException as e:
                skip_malformed_packet(e.args[0])


class PacketProtocol(asyncio.Protocol):
    def __init__(self, listener):
        self._listener = listener
        self._peername = None
        self._accumulator = None

    def connection_made(self, transport):
        self._peername = transport.get_extra_info("peername")
        LOG.info("Connection from {}".format(self._peername))
        self._accumulator = PacketAccumulator()

    def connection_lost(self, exc):
        if exc is not None:
            LOG.warning(
                "Connection lost from {}: {}".format(self._peername, exc))
        else:
            LOG.info("Connection closed from {}".format(self._peername))
        self._accumulator = None

    def data_received(self, data):
        LOG.debug(
            'Received {} bytes from {}'.format(len(data), self._peername))
        self._accumulator.put_bytes(data)

        packet = self._accumulator.try_get_packet()
        while packet is not None:
            LOG.debug('Parsed 1 packet from {}'.format(self._peername))
            asyncio.ensure_future(asyncio.coroutine(self._listener)(packet))
            packet = self._accumulator.try_get_packet()
