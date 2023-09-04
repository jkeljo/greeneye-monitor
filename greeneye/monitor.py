import asyncio
import inspect
import logging
import socket
from asyncio.base_events import Server
from datetime import datetime, timedelta
from enum import Enum
from types import TracebackType
from typing import (
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    ParamSpec,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import aiohttp
from siobrultech_protocols.gem import api
from siobrultech_protocols.gem.packets import Packet, PacketFormatType
from siobrultech_protocols.gem.protocol import (
    ApiType,
    ConnectionLostMessage,
    ConnectionMadeMessage,
    PacketProtocolMessage,
    PacketReceivedMessage,
)

from . import api as api_ext
from .api import GemSettings, TemperatureUnit
from .protocol import GemProtocol

LOG = logging.getLogger(__name__)
SECONDS_PER_HOUR = 3600
WATTS_PER_KILOWATT = 1000

Listener = Union[Callable[[], Awaitable[None]], Callable[[], None]]


class PulseCounter:
    """Represents a single GEM pulse-counting channel"""

    def __init__(self, monitor: "Monitor", number: int, is_aux: bool = False) -> None:
        self._monitor = monitor
        self.number: int = number
        self.pulses: Optional[int] = None
        self.pulses_per_second: Optional[float] = None
        self.seconds: Optional[int] = None
        self.is_aux: bool = is_aux
        self._listeners: List[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_packet(self, packet: Packet) -> None:
        if not self.is_aux:
            new_value = packet.pulse_counts[self.number]
        else:
            new_value = packet.aux[self.number]
        if new_value == self.pulses and self.pulses_per_second == 0:
            return

        if self.seconds is not None:
            elapsed_seconds = packet.delta_seconds(self.seconds)
            if not self.is_aux:
                self.pulses_per_second = (
                    (
                        packet.delta_pulse_count(self.number, self.pulses)
                        / elapsed_seconds
                    )
                    if self.pulses is not None and elapsed_seconds > 0
                    else 0
                )
            else:
                self.pulses_per_second = (
                    (packet.delta_aux_count(self.number, self.pulses) / elapsed_seconds)
                    if self.pulses is not None and elapsed_seconds > 0
                    else 0
                )

        self.seconds = packet.seconds
        self.pulses = new_value

        await _invoke_listeners(self._listeners)


class TemperatureSensor:
    """Represents a single GEM temperature-sensor channel"""

    def __init__(
        self, monitor: "Monitor", number: int, unit: Optional[TemperatureUnit] = None
    ) -> None:
        self._monitor = monitor
        self.number: int = number
        self.temperature: Optional[float] = None
        self.unit: Optional[TemperatureUnit] = unit
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

    def __init__(
        self,
        monitor: "Monitor",
        number: int,
        net_metering: Optional[bool] = None,
        is_aux: bool = False,
    ) -> None:
        self._monitor = monitor
        self.number: int = number
        self.net_metering: Optional[bool] = net_metering
        self.absolute_watt_seconds: Optional[int] = None
        self.polarized_watt_seconds: Optional[int] = None
        self.amps: Optional[float] = None
        self.seconds: Optional[int] = None
        self.watts: Optional[float] = None
        self.timestamp: Optional[datetime] = None
        self.ct_type: Optional[int] = None
        self.ct_range: Optional[int] = None
        self.is_aux: bool = is_aux
        self._listeners: List[Listener] = []

    @property
    def watt_seconds(self) -> Optional[float]:
        if self.absolute_watt_seconds is None:
            return None

        # Polarized can be None if net metering is off for a channel
        polarized_watt_seconds = self.polarized_watt_seconds or 0
        consumed = self.absolute_watt_seconds - polarized_watt_seconds
        produced = polarized_watt_seconds

        return consumed - produced

    @property
    def kilowatt_hours(self) -> Optional[float]:
        if self.watt_seconds is None:
            return None

        return self.watt_seconds / WATTS_PER_KILOWATT / SECONDS_PER_HOUR

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

    async def set_ct_type(self, type: int) -> None:
        control = self._monitor.control
        assert control
        assert control.api_type
        assert self.ct_type is not None
        assert self.ct_range is not None
        assert not self.is_aux
        if self.ct_type == type:
            return

        if control.api_type == ApiType.GEM:
            await control.set_ct_type(channel=self.number + 1, type=type)
        elif control.api_type == ApiType.ECM:
            await control.set_ct_type_and_range(
                channel=self.number + 1, type=type, range=self.ct_range
            )
        else:
            assert False

        self.ct_type = type

    async def set_ct_range(self, range: int) -> None:
        control = self._monitor.control
        assert control
        assert control.api_type
        assert self.ct_type is not None
        assert self.ct_range is not None
        assert not self.is_aux
        if self.ct_range == range:
            return

        if control.api_type == ApiType.GEM:
            await control.set_ct_range(channel=self.number + 1, range=range)
        elif control.api_type == ApiType.ECM:
            await control.set_ct_type_and_range(
                channel=self.number + 1, type=self.ct_type, range=range
            )
        else:
            assert False

        self.ct_range = range

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_settings(self, settings: GemSettings) -> None:
        net_metering = settings.channel_net_metering[self.number]
        ct_type = settings.ct_types[self.number]
        ct_range = settings.ct_ranges[self.number]
        if (
            net_metering == self.net_metering
            and ct_type == self.ct_type
            and ct_range == self.ct_range
        ):
            return

        self.net_metering = net_metering
        self.ct_type = ct_type
        self.ct_range = ct_range
        await _invoke_listeners(self._listeners)

    async def handle_packet(self, packet: Packet) -> None:
        if not self.is_aux:
            new_absolute_watt_seconds = packet.absolute_watt_seconds[self.number]
            new_polarized_watt_seconds = (
                packet.polarized_watt_seconds[self.number]
                if packet.polarized_watt_seconds
                else None
            )
            new_amps = packet.currents[self.number] if packet.currents else None
        else:
            new_absolute_watt_seconds = packet.aux[self.number]
            new_polarized_watt_seconds = None
            new_amps = None

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
            if not self.is_aux:
                delta_total_watt_seconds = (
                    packet.delta_absolute_watt_seconds(
                        self.number, self.absolute_watt_seconds
                    )
                    if self.absolute_watt_seconds is not None
                    else 0
                )
            else:
                delta_total_watt_seconds = (
                    packet.delta_aux_count(self.number, self.absolute_watt_seconds)
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
                (delta_watt_seconds_consumed - delta_watt_seconds_produced)
                / elapsed_seconds
                if elapsed_seconds > 0
                else 0
            )

        self.seconds = packet.seconds
        self.absolute_watt_seconds = new_absolute_watt_seconds
        self.polarized_watt_seconds = new_polarized_watt_seconds
        self.amps = new_amps
        self.timestamp = packet.time_stamp

        await _invoke_listeners(self._listeners)


class Aux:
    """Represents a single ECM-1240 Aux channel."""

    def __init__(self, monitor: "Monitor", number: int) -> None:
        self._monitor = monitor
        self.number: int = number
        self.pulse_counter: PulseCounter = PulseCounter(monitor, number, is_aux=True)
        self.channel: Channel = Channel(
            monitor, number, net_metering=False, is_aux=True
        )

    def add_listener(self, listener: Listener) -> None:
        self.pulse_counter.add_listener(listener)
        self.channel.add_listener(listener)

    def remove_listener(self, listener: Listener) -> None:
        self.pulse_counter.remove_listener(listener)
        self.channel.remove_listener(listener)

    async def handle_packet(self, packet: Packet) -> None:
        await asyncio.gather(
            self.pulse_counter.handle_packet(packet),
            self.channel.handle_packet(packet),
        )


NUM_PULSE_COUNTERS: int = 4
NUM_TEMPERATURE_SENSORS: int = 8


class MonitorControl:
    """Provides access to APIs that control a monitor."""

    @staticmethod
    async def try_create(
        protocol: GemProtocol, serial_number: int, api_timeout: timedelta | None
    ) -> Optional[Tuple["MonitorControl", GemSettings]]:
        try:
            settings = await api_ext.get_all_settings(
                protocol, serial_number, api_timeout
            )
            # await api_ext.send_one_packet(protocol, serial_number)
            return (MonitorControl(protocol, serial_number), settings)
        except Exception:
            # The remote either timed out or returned binary data, which probably
            # indicates it's a DashBox
            return None

    def __init__(self, protocol: GemProtocol, serial_number: int) -> None:
        self._protocol = protocol
        self._serial_number = serial_number

    @property
    def api_type(self) -> ApiType:
        return self._protocol.api_type

    def set_protocol(self, protocol: GemProtocol) -> None:
        self._protocol = protocol

    async def get_settings(self) -> GemSettings:
        return await api_ext.get_all_settings(self._protocol, self._serial_number)

    async def set_ct_type(self, channel: int, type: int) -> None:
        await api_ext.set_ct_type(
            self._protocol,
            channel=channel,
            type=type,
            serial_number=self._serial_number,
        )

    async def set_ct_range(self, channel: int, range: int) -> None:
        await api_ext.set_ct_range(
            self._protocol,
            channel=channel,
            range=range,
            serial_number=self._serial_number,
        )

    async def set_ct_type_and_range(self, channel: int, type: int, range: int) -> None:
        await api_ext.set_ct_type_and_range(
            self._protocol,
            channel=channel,
            type=type,
            range=range,
            serial_number=self._serial_number,
        )

    async def set_packet_send_interval(self, seconds: int) -> None:
        assert seconds > 0 and seconds <= 255
        await api.set_packet_send_interval(
            self._protocol,
            send_interval_seconds=seconds,
            serial_number=self._serial_number,
        )

    async def set_packet_destination(
        self, host: str, port: int, session: aiohttp.ClientSession
    ) -> None:
        peername = self._protocol.peername
        if peername:
            (gem_host, _) = peername

            await api_ext.set_packet_destination(gem_host, host, port, session)
            LOG.info(
                "%d: Configured to send packets to %s:%d",
                self._serial_number,
                host,
                port,
            )
            return

    async def set_packet_format(self, format: PacketFormatType) -> None:
        await api.set_packet_format(self._protocol, format, self._serial_number)


class MonitorType(Enum):
    ECM_1220 = 1
    ECM_1240 = 2
    GEM = 3


class Monitor:
    """Represents a single GreenEye Monitor"""

    def __init__(self, serial_number: int) -> None:
        """serial_number is the 8 digit serial number as it appears in the GEM
        UI"""
        self.serial_number: int = serial_number
        self._protocol: Optional[GemProtocol] = None
        self._control: Optional[MonitorControl] = None
        self.channels: List[Channel] = []
        self.pulse_counters: List[PulseCounter] = []
        self.temperature_sensors: List[TemperatureSensor] = []
        self.aux: List[Channel | Aux] = []
        self.voltage_sensor: VoltageSensor = VoltageSensor(self)
        self.packet_send_interval: timedelta = timedelta(seconds=0)
        self.packet_format: Optional[PacketFormatType] = None
        self.settings: Optional[GemSettings] = None
        self._configured: bool = False
        self._packet_interval: int = 0
        self._last_packet_seconds: Optional[int] = None
        self._listeners: List[Listener] = []

    @property
    def control(self) -> Optional[MonitorControl]:
        return self._control

    @property
    def type(self) -> MonitorType:
        if self.packet_format == PacketFormatType.ECM_1220:
            return MonitorType.ECM_1220
        elif self.packet_format == PacketFormatType.ECM_1240:
            return MonitorType.ECM_1240
        else:
            return MonitorType.GEM

    async def _set_protocol(
        self, protocol: Optional[GemProtocol], api_timeout: timedelta | None = None
    ) -> None:
        if self._protocol is protocol:
            return
        if protocol is None:
            self._protocol = None
            self._control = None
            return

        self._protocol = protocol
        result = await MonitorControl.try_create(
            self._protocol, self.serial_number, api_timeout
        )
        if result is not None:
            (self._control, settings) = result
            await self._configure_from_settings(settings, self._control)

    async def _configure_from_settings(
        self, settings: GemSettings, control: MonitorControl
    ) -> None:
        self.settings = settings
        self.packet_send_interval = settings.packet_send_interval
        self.packet_format = settings.packet_format

        # Truncate or expand channel listing
        if len(self.channels) < settings.num_channels:
            del self.channels[settings.num_channels :]
        for num in range(len(self.channels), settings.num_channels):
            self.channels.append(Channel(self, num, settings.channel_net_metering[num]))

        if self.type == MonitorType.GEM:
            # Initialize temperature sensors if needed
            for num in range(len(self.temperature_sensors), NUM_TEMPERATURE_SENSORS):
                self.temperature_sensors.append(
                    TemperatureSensor(self, num, settings.temperature_unit)
                )

            # Initialize pulse counters if needed
            for num in range(len(self.pulse_counters), NUM_PULSE_COUNTERS):
                self.pulse_counters.append(PulseCounter(self, num))

        # Voltage sensor was created up front

        # Now update settings if needed and trigger listeners
        coroutines: list[Awaitable[None]] = []
        for temperature_sensor in self.temperature_sensors:
            coroutines.append(temperature_sensor.handle_settings(settings))
        for channel in self.channels:
            coroutines.append(channel.handle_settings(settings))
        self._configured = True
        LOG.info(f"Configured {self.serial_number} from settings API call.")

        for listener in self._listeners:
            coroutines.append(_ensure_coroutine(listener)())
        await asyncio.gather(*coroutines)

    async def _configure_from_packet(self, packet: Packet) -> None:
        self.packet_format = packet.packet_format.type

        if not self.aux and len(packet.aux) == 5:
            for num in range(0, 4):
                self.aux.append(Channel(self, num, net_metering=False, is_aux=True))
            self.aux.append(Aux(self, 4))

        if not self._configured:
            for num in range(0, packet.num_channels):
                self.channels.append(Channel(self, num))

            for num in range(0, len(packet.temperatures)):
                self.temperature_sensors.append(TemperatureSensor(self, num))

            if self.type == MonitorType.GEM:
                self.pulse_counters = [
                    PulseCounter(self, num) for num in range(0, NUM_PULSE_COUNTERS)
                ]

            # Voltage sensor was created up front

            self._configured = True
            LOG.info(f"Configured {self.serial_number} from first packet.")
        await _invoke_listeners(self._listeners)

    async def set_packet_send_interval(self, seconds: int) -> None:
        assert self._control
        await self._control.set_packet_send_interval(seconds)

    def set_packet_interval(self, seconds: int) -> None:
        self._packet_interval = seconds

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    async def handle_packet(self, packet: Packet) -> None:
        await self._configure_from_packet(packet)

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
        for aux in self.aux:
            await aux.handle_packet(packet)
        await _invoke_listeners(self._listeners)


async def _invoke_listeners(listeners: List[Listener]) -> None:
    coroutines: list[Awaitable[None]] = [
        _ensure_coroutine(listener)() for listener in listeners
    ]
    if len(coroutines) > 0:
        await asyncio.gather(*coroutines)


ServerListener = Callable[[PacketProtocolMessage], Awaitable[None]]
GEM_PORT = 8000


class MonitorProtocolProcessor:
    """Listens for connections from GEMs and notifies a listener of each
    packet."""

    def __init__(self, listener: ServerListener, send_packet_delay: bool) -> None:
        self._consumer_task: asyncio.Task[None] | None = asyncio.ensure_future(
            self._consumer()
        )
        LOG.debug("Packet processor started")
        self._listener = listener
        self._queue: asyncio.Queue[PacketProtocolMessage] = asyncio.Queue()
        self._server: Optional[Server] = None
        self._protocols: Dict[int, GemProtocol] = {}
        self._send_packet_delay = send_packet_delay

    async def connect(
        self, hostname: str
    ) -> Tuple[asyncio.BaseTransport, asyncio.BaseProtocol]:
        loop = asyncio.get_event_loop()
        return await loop.create_connection(
            self._create_protocol,
            host=hostname,
            port=GEM_PORT,
        )

    async def start_server(self, desiredPort: int = 0) -> int:
        loop = asyncio.get_event_loop()
        self._server = await loop.create_server(
            self._create_protocol,
            None,
            desiredPort,
            family=socket.AF_INET,
        )

        host, port = self._server.sockets[0].getsockname()
        LOG.info(f"Server started on {host}:{port}")
        return port

    async def _consumer(self) -> None:
        try:
            while True:
                message = await self._queue.get()
                if isinstance(message, ConnectionLostMessage):
                    del self._protocols[id(message.protocol)]
                try:
                    await self._listener(message)
                except Exception:
                    LOG.exception("Exception while calling the listener!")
                self._queue.task_done()
        except asyncio.CancelledError:
            LOG.debug("queue consumer is getting canceled")
            raise

    def _create_protocol(self) -> GemProtocol:
        # TODO: Set API type to GEM when connecting
        protocol = GemProtocol(self._queue, send_packet_delay=self._send_packet_delay)
        self._protocols[id(protocol)] = protocol
        return protocol

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

        while len(self._protocols) > 0:
            (_, protocol) = self._protocols.popitem()
            protocol.close()


MonitorListener = Union[Callable[[Monitor], Awaitable[None]], Callable[[Monitor], None]]


class Monitors:
    """Keeps track of all monitors that have reported data"""

    def __init__(
        self, send_packet_delay: bool = True, api_timeout: timedelta | None = None
    ) -> None:
        self.monitors: Dict[int, Monitor] = {}
        self._protocol_to_monitors: Dict[int, set[Monitor]] = {}
        self._listeners: List[MonitorListener] = []
        self._processor: MonitorProtocolProcessor = MonitorProtocolProcessor(
            self._handle_message, send_packet_delay=send_packet_delay
        )
        self._api_timeout: timedelta | None = api_timeout

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

    async def start_server(self, port: int = 0) -> int:
        return await self._processor.start_server(port)

    async def connect(self, host: str) -> Monitor:
        (_, protocol) = await self._processor.connect(host)
        assert isinstance(protocol, GemProtocol)
        serial_number = await api.get_serial_number(protocol, timeout=self._api_timeout)
        monitor = await self._add_monitor(serial_number, protocol)
        return monitor

    async def close(self) -> None:
        await self._processor.close()

    async def _handle_message(self, message: PacketProtocolMessage) -> None:
        assert isinstance(message.protocol, GemProtocol)
        protocol_id = id(message.protocol)
        if isinstance(message, PacketReceivedMessage):
            packet = message.packet
            serial_number = packet.device_id * 100000 + packet.serial_number
            if serial_number not in self.monitors:
                await self._add_monitor(serial_number, message.protocol, packet)
            else:
                monitor = self.monitors[serial_number]
                await self._set_monitor_protocol(monitor, message.protocol)
                await monitor.handle_packet(packet)
        else:
            if isinstance(message, ConnectionLostMessage):
                for monitor in self._protocol_to_monitors.pop(protocol_id):
                    await monitor._set_protocol(None)  # type: ignore
            elif isinstance(message, ConnectionMadeMessage):
                self._protocol_to_monitors[protocol_id] = set()

    async def _add_monitor(
        self, serial_number: int, protocol: GemProtocol, packet: Packet | None = None
    ) -> Monitor:
        LOG.info("Discovered new monitor: %d", serial_number)
        monitor = Monitor(serial_number)
        await self._set_monitor_protocol(monitor, protocol)
        if packet:
            await monitor.handle_packet(packet)
        self.monitors[serial_number] = monitor
        await self._notify_new_monitor(monitor)
        return monitor

    async def _set_monitor_protocol(
        self, monitor: Monitor, protocol: GemProtocol
    ) -> None:
        protocol_id = id(protocol)
        self._protocol_to_monitors[protocol_id].add(monitor)
        await monitor._set_protocol(  # type: ignore
            protocol, api_timeout=self._api_timeout
        )

    async def _notify_new_monitor(self, monitor: Monitor) -> None:
        listeners = [
            _ensure_coroutine(listener)(monitor) for listener in self._listeners
        ]
        if len(listeners) > 0:
            await asyncio.gather(*listeners)  # type: ignore


P = ParamSpec("P")
R = TypeVar("R")


def _ensure_coroutine(
    listener: Union[Callable[P, Awaitable[R]], Callable[P, R]]
) -> Callable[P, Awaitable[R]]:
    if inspect.iscoroutinefunction(listener):
        return listener
    else:

        async def async_listener(*args: P.args, **kwargs: P.kwargs) -> R:
            return listener(*args, **kwargs)  # type: ignore

        return async_listener
