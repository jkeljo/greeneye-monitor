import asyncio
from asyncio.base_events import Server
from datetime import datetime
import logging
import socket
from types import TracebackType
from typing import Awaitable, Callable, Dict, List, Optional, Type, Union

from siobrultech_protocols.gem.packets import Packet
from siobrultech_protocols.gem.protocol import PacketProtocol

LOG = logging.getLogger(__name__)
SECONDS_PER_HOUR = 3600
WATTS_PER_KILOWATT = 1000

Listener = Union[Callable[[], Awaitable[None]], Callable[[], None]]


class PulseCounter:
    """Represents a single GEM pulse-counting channel"""

    def __init__(self, monitor: "Monitor", number: int) -> None:
        self._monitor = monitor
        self.number: int = number
        self.pulses: Optional[int] = None
        self.pulses_per_second: Optional[float] = None
        self.seconds: Optional[int] = None
        self._listeners: List[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_packet(self, packet: Packet) -> None:
        new_value = packet.pulse_counts[self.number]
        if new_value == self.pulses and self.pulses_per_second == 0:
            return

        if self.seconds is not None:
            elapsed_seconds = _compute_delta(
                earlier_sample=self.seconds,
                later_sample=packet.seconds,
                max_value=packet.max_seconds,
            )

            self.pulses_per_second = (
                (
                    _compute_delta(
                        earlier_sample=self.pulses,
                        later_sample=new_value,
                        max_value=packet.max_pulse_count,
                    )
                    / elapsed_seconds
                )
                if self.pulses is not None
                else 0
            )

        self.seconds = packet.seconds
        self.pulses = new_value

        for listener in self._listeners:
            await asyncio.coroutine(listener)()  # type: ignore


class TemperatureSensor:
    """Represents a single GEM temperature-sensor channel"""

    def __init__(self, monitor: "Monitor", number: int) -> None:
        self._monitor = monitor
        self.number: int = number
        self.temperature: Optional[float] = None
        self._listeners: List[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_packet(self, packet: Packet) -> None:
        new_value = packet.temperatures[self.number]
        if new_value == self.temperature:
            return

        self.temperature = new_value
        for listener in self._listeners:
            await asyncio.coroutine(listener)()  # type: ignore


class Channel:
    """Represents a single GEM CT channel"""

    def __init__(self, monitor: "Monitor", number: int) -> None:
        self._monitor = monitor
        self.number: int = number
        self.total_absolute_watt_seconds: Optional[int] = None
        self.total_polarized_watt_seconds: Optional[int] = None
        self.absolute_watt_seconds: Optional[int] = None
        self.polarized_watt_seconds: Optional[int] = None
        self.amps: Optional[float] = None
        self.seconds: Optional[int] = None
        self.watts: Optional[float] = None
        self.timestamp: Optional[datetime] = None
        self._listeners: List[Listener] = []

    @property
    def absolute_kilowatt_hours(self) -> Optional[float]:
        if self.absolute_watt_seconds is None:
            return None

        return self.absolute_watt_seconds / WATTS_PER_KILOWATT / SECONDS_PER_HOUR

    @property
    def polarized_kilowatt_hours(self) -> Optional[float]:
        if self.polarized_watt_seconds is None:
            return None

        return self.polarized_watt_seconds / WATTS_PER_KILOWATT / SECONDS_PER_HOUR

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_packet(self, packet: Packet) -> None:
        new_absolute_watt_seconds = packet.absolute_watt_seconds[self.number]
        new_polarized_watt_seconds = (
            packet.polarized_watt_seconds[self.number]
            if hasattr(packet, "polarized_watt_seconds")
            else None
        )
        new_amps = packet.currents[self.number] if hasattr(packet, "currents") else None

        if (
            self.absolute_watt_seconds == new_absolute_watt_seconds
            and self.polarized_watt_seconds == new_polarized_watt_seconds
            and self.amps == new_amps
            and self.watts == 0
        ):
            # Nothing changed
            return

        if self.seconds is not None:
            elapsed_seconds = _compute_delta(
                earlier_sample=self.seconds,
                later_sample=packet.seconds,
                max_value=packet.max_seconds,
            )

            # This is the total energy produced or consumed since the last
            # sample.
            delta_total_watt_seconds = (
                _compute_delta(
                    earlier_sample=self.absolute_watt_seconds,
                    later_sample=new_absolute_watt_seconds,
                    max_value=packet.max_absolute_watt_seconds,
                )
                if self.absolute_watt_seconds is not None
                else 0
            )

            # This is the energy produced since the last sample. This will be 0
            # for all channels except for channels in NET metering mode that
            # are actually producing electricity.
            if (
                self.polarized_watt_seconds is not None
                and new_polarized_watt_seconds is not None
            ):
                delta_watt_seconds_produced = _compute_delta(
                    earlier_sample=self.polarized_watt_seconds,
                    later_sample=new_polarized_watt_seconds,
                    max_value=packet.max_polarized_watt_seconds,
                )
            else:
                delta_watt_seconds_produced = 0

            # This is the energy consumed since the last sample.
            delta_watt_seconds_consumed = (
                delta_total_watt_seconds - delta_watt_seconds_produced
            )

            # Now compute the average power over the time since the last sample
            self.watts = (
                delta_watt_seconds_consumed - delta_watt_seconds_produced
            ) / elapsed_seconds

        self.seconds = packet.seconds
        self.absolute_watt_seconds = new_absolute_watt_seconds
        self.polarized_watt_seconds = new_polarized_watt_seconds
        self.amps = new_amps
        self.timestamp = packet.time_stamp

        for listener in self._listeners:
            await asyncio.coroutine(listener)()  # type: ignore


def _compute_delta(earlier_sample: int, later_sample: int, max_value: int) -> int:
    """Computes the difference between two samples of a value, considering
    that the value may have wrapped around in between"""
    if earlier_sample > later_sample:
        # Wraparound occurred
        return later_sample - (max_value - earlier_sample)

    return later_sample - earlier_sample


class Monitor:
    """Represents a single GreenEye Monitor"""

    def __init__(self, serial_number: int) -> None:
        """serial_number is the 8 digit serial number as it appears in the GEM
        UI"""
        self.serial_number: int = serial_number
        self.channels: List[Channel] = []
        self.pulse_counters: List[PulseCounter] = []
        self.temperature_sensors: List[TemperatureSensor] = []
        self.voltage: Optional[float] = None
        self._packet_interval: int = 0
        self._last_packet_seconds: Optional[int] = None
        self._listeners: List[Listener] = []

    def set_packet_interval(self, seconds: int) -> None:
        self._packet_interval = seconds

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_packet(self, packet: Packet) -> None:
        if self._last_packet_seconds is not None:
            elapsed_seconds = _compute_delta(
                earlier_sample=self._last_packet_seconds,
                later_sample=packet.seconds,
                max_value=packet.max_seconds,
            )

            if elapsed_seconds < self._packet_interval:
                return
        self._last_packet_seconds = packet.seconds

        while len(self.channels) < packet.num_channels:
            self.channels.append(Channel(self, len(self.channels)))
        while len(self.pulse_counters) < len(packet.pulse_counts):
            self.pulse_counters.append(PulseCounter(self, len(self.pulse_counters)))
        while len(self.temperature_sensors) < len(packet.temperatures):
            self.temperature_sensors.append(
                TemperatureSensor(self, len(self.temperature_sensors))
            )

        self.voltage = packet.voltage
        for channel in self.channels:
            await channel.handle_packet(packet)
        for temperature_sensor in self.temperature_sensors:
            await temperature_sensor.handle_packet(packet)
        for pulse_counter in self.pulse_counters:
            await pulse_counter.handle_packet(packet)
        for listener in self._listeners:
            await asyncio.coroutine(listener)()  # type: ignore


PacketListener = Callable[[Packet], Awaitable[None]]


class MonitoringServer:
    """Listens for connections from GEMs and notifies a listener of each
    packet."""

    def __init__(self, port: int, listener: PacketListener) -> None:
        self._consumer_task = None
        self._listener = listener
        self._port = port
        self._queue = asyncio.Queue()
        self._server: Optional[Server] = None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        self._server = await loop.create_server(
            lambda: PacketProtocol(self._queue), None, self._port, family=socket.AF_INET
        )

        LOG.info("Server started on {}".format(self._server.sockets[0].getsockname()))

        self._consumer_task = asyncio.ensure_future(self._consumer())
        LOG.debug("Packet processor started")

    async def _consumer(self) -> None:
        try:
            while True:
                packet = await self._queue.get()
                try:
                    await self._listener(packet)
                except Exception as exc:
                    LOG.exception("Exception while calling the listener!", exc)
                self._queue.task_done()
        except asyncio.CancelledError:
            LOG.debug("queue consumer is getting canceled")
            raise

    async def __aenter__(self) -> "MonitoringServer":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._server is not None:
            LOG.info(
                "Closing server on {}".format(self._server.sockets[0].getsockname())
            )
            # Disallow new connections
            self._server.close()

            # Wait for shutdown
            await self._server.wait_closed()
            self._server = None

            # Wait for packets to be processed
            await self._queue.join()

        if self._consumer_task is not None:
            # Cancel consumer task
            self._consumer_task.cancel()
            self._consumer_task = None


MonitorListener = Union[Callable[[Monitor], Awaitable[None]], Callable[[Monitor], None]]


class Monitors:
    """Keeps track of all monitors that have reported data"""

    def __init__(self):
        self.monitors: Dict[int, Monitor] = {}
        self._listeners: List[MonitorListener] = []

    def add_listener(self, listener: MonitorListener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: MonitorListener) -> None:
        self._listeners.remove(listener)

    async def start_server(self, port: int) -> MonitoringServer:
        result = MonitoringServer(port, self._handle_packet)
        await result.start()
        return result

    async def _handle_packet(self, packet: Packet) -> None:
        serial_number = packet.device_id * 100000 + packet.serial_number
        new_monitor = False
        if serial_number not in self.monitors:
            LOG.info("Discovered new monitor: %s", serial_number)
            self.monitors[serial_number] = Monitor(serial_number)
            new_monitor = True

        monitor = self.monitors[serial_number]
        await monitor.handle_packet(packet)

        if new_monitor:
            listeners = [
                asyncio.coroutine(listener)(monitor) for listener in self._listeners
            ]
            if len(listeners) > 0:
                await asyncio.wait(listeners)  # type: ignore
