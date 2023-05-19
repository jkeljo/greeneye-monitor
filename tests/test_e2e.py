import asyncio
from datetime import timedelta
import functools
from siobrultech_protocols.gem.packets import PacketFormatType
import socket
from typing import List, cast, Optional
import unittest

from greeneye import Monitors
from greeneye.monitor import Monitor

from .packet_test_data import read_packet


class ApiUnawareClient(asyncio.Protocol):
    def __init__(self, packet: str):
        self._packet: bytes = read_packet(packet)
        self._transport: Optional[asyncio.WriteTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = cast(asyncio.WriteTransport, transport)
        self._try_send_packet()

    def connection_lost(self, exc: Optional[Exception]) -> None:
        pass

    def data_received(self, data: bytes) -> None:
        self._try_send_packet()

    def eof_received(self) -> Optional[bool]:
        pass

    def _try_send_packet(self):
        if self._transport:
            self._transport.write(self._packet)


class ApiAwareClient(asyncio.Protocol):
    def __init__(self):
        self._packet: bytes = read_packet("BIN32-NET.bin")
        self._transport: Optional[asyncio.WriteTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = cast(asyncio.WriteTransport, transport)
        self._transport.write(self._packet)

    def data_received(self, data: bytes) -> None:
        request = data.decode()
        if request.endswith("RQSALL"):
            assert self._transport
            self._transport.write(
                "ALL\r\n00,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,00,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,D3,D3,D3,D2,D3,D3,D4,D3,D3,D3,D3,D3,D3,D3,D3,D2,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D2,D3,D3,D2,90,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,44,44,44,43,44,44,44,44,44,44,44,44,44,44,44,24,44,44,44,44,44,44,44,44,89,03,08,05,00,00,1E,00,87,00,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,18,26,A6,80,C7,18,25,81,87,C6,18,25,A4,40,27,F9,86,81,BF,78,6E,25,87,4E,84,88,4E,85,89,A6,8A,B0,83,C7,04,EB,C7,05,1B,A6,00,B2,82,C7,04,EA,C7,05,1A,55,82,D6,00,DC,B7,86,CD,04,B0,AF,01,8B,89,55,00,00,A6,20,00,02,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,AF,FF,35,84,65,DD,00,00,00,00,00,00,00,0F,00,00,00,00,00,01,01,00,00,01,07,FF,01,50,17,70,20,7F".encode()
            )


class TestGEME2E(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._packet: bytes = read_packet("BIN32-NET.bin")
        self._discovered: asyncio.Condition = asyncio.Condition()
        self._error: Exception | None = None

    async def onNewMonitor(self, monitor: Monitor):
        try:
            assert monitor
            assert len(monitor.channels) == 32
            assert len(monitor.pulse_counters) == 4
            assert len(monitor.temperature_sensors) == 8
            assert monitor.packet_format == PacketFormatType.BIN32_NET
        except AssertionError as e:
            self._error = e

        async with self._discovered:
            self._discovered.notify()

    async def testMonitorConfiguredProperlyWhenClientRespondsToAPI(self):
        await self.assertMonitorConfiguredProperlyWithClient(ApiAwareClient)

    async def testMonitorConfiguredProperlyWhenClientIgnoresAPI(self):
        await self.assertMonitorConfiguredProperlyWithClient(
            functools.partial(ApiUnawareClient, packet="BIN32-NET.bin")
        )

    async def assertMonitorConfiguredProperlyWithClient(self, client):
        loop = asyncio.get_event_loop()
        async with Monitors(
            send_packet_delay=False, api_timeout=timedelta(seconds=0)
        ) as monitors:
            monitors.add_listener(self.onNewMonitor)
            port = await monitors.start_server()
            async with self._discovered:
                (transport, _) = await loop.create_connection(
                    client, "localhost", port, family=socket.AF_INET
                )
                await self._discovered.wait()
                transport.close()

        if self._error:
            raise self._error


class TestECME2E(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._packet: bytes = read_packet("ECM-1240.bin")
        self._discovered: asyncio.Condition = asyncio.Condition()
        self._error: Exception | None = None

    async def onNewMonitor(self, monitor: Monitor):
        try:
            assert monitor
            assert len(monitor.channels) == 2
            assert len(monitor.pulse_counters) == 0
            assert len(monitor.temperature_sensors) == 0
            assert len(monitor.aux) == 5
            assert monitor.packet_format == PacketFormatType.ECM_1240
        except AssertionError as e:
            self._error = e

        async with self._discovered:
            self._discovered.notify()

    async def testMonitorConfiguredProperlyWhenClientIgnoresAPI(self) -> None:
        await self.assertMonitorConfiguredProperlyWithClient(
            functools.partial(ApiUnawareClient, packet="ECM-1240.bin")
        )

    async def assertMonitorConfiguredProperlyWithClient(self, client):
        loop = asyncio.get_event_loop()
        async with Monitors(
            send_packet_delay=False, api_timeout=timedelta(seconds=0)
        ) as monitors:
            monitors.add_listener(self.onNewMonitor)
            port = await monitors.start_server()
            async with self._discovered:
                (transport, _) = await loop.create_connection(
                    client, "localhost", port, family=socket.AF_INET
                )
                await self._discovered.wait()
                transport.close()

        if self._error:
            raise self._error
