import asyncio
from asyncio.base_events import Server
from datetime import datetime, timedelta
import logging
import socket
from types import TracebackType
from typing import Awaitable, Callable, Dict, List, Optional, Type, Union

from siobrultech_protocols.gem import api
from siobrultech_protocols.gem.packets import Packet
from siobrultech_protocols.gem.protocol import (
    BidirectionalProtocol,
    ConnectionLostMessage,
    ConnectionMadeMessage,
    PacketProtocolMessage,
    PacketReceivedMessage,
)

from greeneye.api import GemSettings, TemperatureUnit, get_all_settings

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
            elapsed_seconds = packet.delta_seconds(self.seconds)
            self.pulses_per_second = (
                (packet.delta_pulse_count(self.number, self.pulses) / elapsed_seconds)
                if self.pulses is not None
                else 0
            )

        self.seconds = packet.seconds
        self.pulses = new_value

        await _invoke_listeners(self._listeners)


class TemperatureSensor:
    """Represents a single GEM temperature-sensor channel"""

    def __init__(self, monitor: "Monitor", number: int, unit: TemperatureUnit) -> None:
        self._monitor = monitor
        self.number: int = number
        self.temperature: Optional[float] = None
        self.unit: TemperatureUnit = unit
        self._listeners: List[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_settings(self, settings: GemSettings) -> None:
        new_unit = settings.temperature_unit
        if new_unit == self.unit:
            return

        self.unit = new_unit
        await _invoke_listeners(self._listeners)

    async def handle_packet(self, packet: Packet) -> None:
        new_value = packet.temperatures[self.number]
        if new_value == self.temperature:
            return

        self.temperature = new_value
        await _invoke_listeners(self._listeners)


class VoltageSensor:
    """Represents the GEMs voltage sensor"""

    def __init__(self, monitor: "Monitor") -> None:
        self._monitor = monitor
        self.voltage: Optional[float] = None
        self._listeners: List[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_packet(self, packet: Packet) -> None:
        new_value = packet.voltage
        if new_value == self.voltage:
            return

        self.voltage = new_value
        await _invoke_listeners(self._listeners)


class Channel:
    """Represents a single GEM CT channel"""

    def __init__(self, monitor: "Monitor", number: int, net_metering: bool) -> None:
        self._monitor = monitor
        self.number: int = number
        self.net_metering: bool = net_metering
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
    def watt_seconds(self) -> Optional[float]:
        if not self.net_metering:
            return self.absolute_watt_seconds
        else:
            return self.net_watt_seconds

    @property
    def kilowatt_hours(self) -> Optional[float]:
        if not self.net_metering:
            return self.absolute_kilowatt_hours
        else:
            return self.net_kilowatt_hours

    @property
    def net_watt_seconds(self) -> Optional[float]:
        if self.absolute_watt_seconds is None or self.polarized_watt_seconds is None:
            return None

        return self.absolute_watt_seconds - self.polarized_watt_seconds

    @property
    def net_kilowatt_hours(self) -> Optional[float]:
        if self.net_watt_seconds is None:
            return None

        return self.net_watt_seconds / WATTS_PER_KILOWATT / SECONDS_PER_HOUR

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

    async def handle_settings(self, settings: GemSettings) -> None:
        net_metering = settings.channel_net_metering[self.number]
        if net_metering == self.net_metering:
            return

        self.net_metering = net_metering
        await _invoke_listeners(self._listeners)

    async def handle_packet(self, packet: Packet) -> None:
        new_absolute_watt_seconds = packet.absolute_watt_seconds[self.number]
        new_polarized_watt_seconds = (
            packet.polarized_watt_seconds[self.number]
            if packet.polarized_watt_seconds
            else None
        )
        new_amps = packet.currents[self.number] if packet.currents else None

        if (
            self.absolute_watt_seconds == new_absolute_watt_seconds
            and self.polarized_watt_seconds == new_polarized_watt_seconds
            and self.amps == new_amps
            and self.watts == 0
        ):
            # Nothing changed
            return

        if self.seconds is not None:
            elapsed_seconds = packet.delta_seconds(self.seconds)

            # This is the total energy produced or consumed since the last
            # sample.
            delta_total_watt_seconds = (
                packet.delta_absolute_watt_seconds(
                    self.number, self.absolute_watt_seconds
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
                delta_watt_seconds_produced = packet.delta_polarized_watt_seconds(
                    self.number, self.polarized_watt_seconds
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

        await _invoke_listeners(self._listeners)


def _compute_delta(earlier_sample: int, later_sample: int, max_value: int) -> int:
    """Computes the difference between two samples of a value, considering
    that the value may have wrapped around in between"""
    if earlier_sample > later_sample:
        # Wraparound occurred
        return later_sample - (max_value - earlier_sample)

    return later_sample - earlier_sample


NUM_PULSE_COUNTERS: int = 4
NUM_TEMPERATURE_SENSORS: int = 8


class Monitor:
    """Represents a single GreenEye Monitor"""

    @staticmethod
    async def _create(serial_number: int, protocol: BidirectionalProtocol) -> "Monitor":
        monitor = Monitor(serial_number, protocol)
        await monitor._sync_with_settings()
        return monitor

    def __init__(self, serial_number: int, protocol: BidirectionalProtocol) -> None:
        """serial_number is the 8 digit serial number as it appears in the GEM
        UI"""
        self.serial_number = serial_number
        self._protocol = protocol
        self.channels: List[Channel] = []
        self.pulse_counters: List[PulseCounter] = [
            PulseCounter(self, num) for num in range(0, NUM_PULSE_COUNTERS)
        ]
        self.temperature_sensors: List[TemperatureSensor] = []
        self.voltage_sensor: VoltageSensor = VoltageSensor(self)
        self.packet_send_interval: timedelta = timedelta(seconds=0)
        self._packet_interval: int = 0
        self._last_packet_seconds: Optional[int] = None
        self._listeners: List[Listener] = []

    async def _set_protocol(self, protocol: BidirectionalProtocol) -> None:
        if self._protocol is protocol:
            return

        self._protocol = protocol
        await self._sync_with_settings()

    async def _sync_with_settings(self) -> None:
        settings = await get_all_settings(self._protocol, self.serial_number)

        self.packet_send_interval = settings.packet_send_interval

        # Truncate or expand channel listing
        if len(self.channels) < settings.num_channels:
            del self.channels[settings.num_channels :]
        for num in range(len(self.channels), settings.num_channels):
            self.channels.append(Channel(self, num, settings.channel_net_metering[num]))

        # Initialize temperature sensors if needed
        for num in range(len(self.temperature_sensors), NUM_TEMPERATURE_SENSORS):
            self.temperature_sensors.append(
                TemperatureSensor(self, num, settings.temperature_unit)
            )

        # Pulse counters and voltage sensors were created up front

        # Now update settings if needed and trigger listeners
        coroutines = []
        for temperature_sensor in self.temperature_sensors:
            coroutines.append(temperature_sensor.handle_settings(settings))
        for channel in self.channels:
            coroutines.append(channel.handle_settings(settings))
        for listener in self._listeners:
            coroutines.append(asyncio.coroutine(listener)())
        await asyncio.wait(coroutines)

    def set_packet_interval(self, seconds: int) -> None:
        self._packet_interval = seconds

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_packet(self, packet: Packet) -> None:
        if self._last_packet_seconds is not None:
            elapsed_seconds = packet.delta_seconds(self._last_packet_seconds)
            if elapsed_seconds < self._packet_interval:
                return
        self._last_packet_seconds = packet.seconds

        await self.voltage_sensor.handle_packet(packet)
        for channel in self.channels:
            await channel.handle_packet(packet)
        for temperature_sensor in self.temperature_sensors:
            await temperature_sensor.handle_packet(packet)
        for pulse_counter in self.pulse_counters:
            await pulse_counter.handle_packet(packet)
        await _invoke_listeners(self._listeners)


async def _invoke_listeners(listeners: List[Listener]) -> None:
    coroutines = [asyncio.coroutine(listener)() for listener in listeners]
    if len(coroutines) > 0:
        await asyncio.wait(coroutines)  # type: ignore


ServerListener = Callable[[PacketProtocolMessage], Awaitable[None]]


class MonitoringServer:
    """Listens for connections from GEMs and notifies a listener of each
    packet."""

    def __init__(self, port: int, listener: ServerListener) -> None:
        self._consumer_task = None
        self._listener = listener
        self._port = port
        self._queue: asyncio.Queue[PacketProtocolMessage] = asyncio.Queue()
        self._server: Optional[Server] = None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        self._server = await loop.create_server(
            lambda: BidirectionalProtocol(self._queue),
            None,
            self._port,
            family=socket.AF_INET,
        )

        LOG.info("Server started on {}".format(self._server.sockets[0].getsockname()))

        self._consumer_task = asyncio.ensure_future(self._consumer())
        LOG.debug("Packet processor started")

    async def _consumer(self) -> None:
        try:
            while True:
                message = await self._queue.get()
                try:
                    await self._listener(message)
                except Exception as exc:
                    LOG.exception("Exception while calling the listener!", exc)
                self._queue.task_done()
        except asyncio.CancelledError:
            LOG.debug("queue consumer is getting canceled")
            raise

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
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None


MonitorListener = Union[Callable[[Monitor], Awaitable[None]], Callable[[Monitor], None]]


class Monitors:
    """Keeps track of all monitors that have reported data"""

    def __init__(self):
        self.monitors: Dict[int, Monitor] = {}
        self._protocols: Dict[int, BidirectionalProtocol] = {}
        self._listeners: List[MonitorListener] = []
        self._server: Optional[MonitoringServer] = None

    async def __aenter__(self) -> "Monitors":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    def add_listener(self, listener: MonitorListener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: MonitorListener) -> None:
        self._listeners.remove(listener)

    async def start_server(self, port: int) -> None:
        server = MonitoringServer(port, self._handle_message)
        await server.start()
        self._server = server

    async def close(self) -> None:
        if self._server:
            await self._server.close()

        while len(self._protocols) > 0:
            _, protocol = self._protocols.popitem()
            protocol.close()

    async def _handle_message(self, message: PacketProtocolMessage) -> None:
        assert isinstance(message.protocol, BidirectionalProtocol)
        if isinstance(message, PacketReceivedMessage):
            packet = message.packet
            serial_number = packet.device_id * 100000 + packet.serial_number
            new_monitor = False
            if serial_number not in self.monitors:
                LOG.info("Discovered new monitor: %s", serial_number)
                monitor = await Monitor._create(serial_number, message.protocol)
                self.monitors[serial_number] = monitor
                new_monitor = True

            monitor = self.monitors[serial_number]
            await monitor._set_protocol(message.protocol)
            await monitor.handle_packet(packet)

            if new_monitor:
                listeners = [
                    asyncio.coroutine(listener)(monitor) for listener in self._listeners
                ]
                if len(listeners) > 0:
                    await asyncio.wait(listeners)  # type: ignore
        else:
            protocol_id = id(message.protocol)
            if isinstance(message, ConnectionLostMessage):
                del self._protocols[protocol_id]
            elif isinstance(message, ConnectionMadeMessage):
                self._protocols[protocol_id] = message.protocol
