import logging

from .packets import *

LOG = logging.getLogger(__name__)


class PacketIterator(object):
    """Iterates over packets from an underlying stream."""

    def __init__(self, stream):
        self._stream = stream
        self._total_packets = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        if self._stream:
            if hasattr(self._stream, 'close'):
                await self._stream.close()
            LOG.info(
                "%s: Closed after %d packets",
                self,
                self._total_packets)
            self._stream = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        self._total_packets += 1
        # When sending these packets over IP, the GEM uses TCP with PSH flags
        # rather than the arguably more appropriate UDP. In practice on an
        # unloaded system this usually results in a single stream read
        # returning a single packet, but if we're unable to read the stream
        # fast enough for some reason it could return more than one. To guard
        # against this, we do some rudimentary packet detection

        packet = bytearray()
        header_bytes = await self._stream.read(3)
        if not header_bytes:
            LOG.info("%s: No more data", self)
            raise StopAsyncIteration
        packet.extend(header_bytes)
        header = hi_to_lo(packet)

        if header == 0xfeff08:
            packet_format = BIN32_ABS
        elif header == 0xfeff07:
            packet_format = BIN32_NET
        elif header == 0xfeff06:
            packet_format = BIN48_ABS
        elif header == 0xfeff05:
            packet_format = BIN48_NET
        else:
            raise MalformedPacketException(
                "Invalid header {0} in packet: {1}".format(
                    hex(header),
                    codecs.encode(packet, 'hex')))

        while len(packet) != packet_format.size:
            packet.extend(
                await self._stream.read(packet_format.size - len(packet)))
            if len(packet) != packet_format.size:
                LOG.debug("Short packet")
        try:
            return packet_format.parse(packet)
        except:
            if packet_format == BIN48_NET:
                LOG.debug('Time packet')
                packet_format = BIN48_NET_TIME
                while len(packet) != packet_format.size:
                    packet.extend(
                        await self._stream.read(
                            packet_format.size - len(packet)))
                    if len(packet) != packet_format.size:
                        LOG.debug("Short time packet")

                return packet_format.parse(packet)
            else:
                raise


class ServerPacketIterator(PacketIterator):
    """Provides a stream of packets from a single connected client."""

    def __init__(self, client_reader, client_writer):
        super().__init__(client_reader)
        self._client_writer = client_writer
        self._peername = self._client_writer.transport.get_extra_info(
            'peername')
        LOG.info("%s: Connected", self)

    def __str__(self):
        result = "{0}:{1}".format(self._peername[0], self._peername[1])
        if not self._client_writer:
            result += " (closed)"

        return result

    async def close(self):
        if self._client_writer:
            # This will close the read connection as well, which should cause
            # the iteration to stop.
            self._client_writer.close()
            self._client_writer = None
            await super().close()
