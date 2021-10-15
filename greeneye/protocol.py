import asyncio
from siobrultech_protocols.gem.api import ApiCall, GET_SERIAL_NUMBER
from siobrultech_protocols.gem.protocol import BidirectionalProtocol
from typing import Awaitable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class GemProtocol(BidirectionalProtocol):
    """Protocol implementation for bi-directional communication with a GreenEye Monitor."""

    def __init__(self, queue: asyncio.Queue):
        """
        Create a new protocol instance.

        When a new connection is received from a GEM, a `GemApi` instance will be enqueued to
        `queue` that allows commands to be sent to that GEM. Whenever a data packet is received from
        the remote GEM, a `Packet` instance will be enqueued to `queue`.
        """
        super().__init__(queue)

    def connection_made(self, transport: asyncio.BaseTransport):
        super().connection_made(transport)
        self._queue.put_nowait(GemApi(self))


class GemApi:
    def __init__(self, protocol: GemProtocol):
        self._protocol = protocol
        self._api_lock = asyncio.Lock()

    async def get_serial_number(self) -> int:
        return await self._send_api_command(GET_SERIAL_NUMBER, None)

    async def _send_api_command(self, call: ApiCall[T, R], arg: T) -> R:
        async with self._api_lock:  # One API call at a time, please
            delay = self._protocol.begin_api_request()
            try:
                await asyncio.sleep(delay.seconds)

                delay = call.send_request(self._protocol, arg)
                await asyncio.sleep(delay.seconds)

                return call.receive_response(self._protocol)
            finally:
                self._protocol.end_api_request()
