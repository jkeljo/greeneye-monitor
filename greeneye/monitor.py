import asyncio
import logging
import socket

from .streams import ServerPacketIterator

LOG = logging.getLogger(__name__)
SECONDS_PER_HOUR = 3600
WATTS_PER_KILOWATT = 1000


class PulseCounter:
    """Represents a single GEM pulse-counting channel"""
    def __init__(self, monitor, number):
        self._monitor = monitor
        self.number = number
        self.pulses = None
        self.pulses_per_second = None
        self.seconds = None
        self._listeners = []

    def add_listener(self, listener):
        self._listeners.append(listener)

    def remove_listener(self, listener):
        self._listeners.remove(listener)

    async def handle_packet(self, packet):
        new_value = packet.pulse_counts[self.number]
        if new_value == self.pulses and self.pulses_per_second == 0:
            return

        if self.seconds is not None:
            elapsed_seconds = _compute_delta(
                earlier_sample=self.seconds,
                later_sample=packet.seconds,
                max_value=packet.max_seconds)

            self.pulses_per_second = _compute_delta(
                earlier_sample=self.pulses,
                later_sample=new_value,
                max_value=packet.max_pulse_count) / elapsed_seconds

        self.seconds = packet.seconds
        self.pulses = new_value

        for listener in self._listeners:
            await asyncio.coroutine(listener)()


class TemperatureSensor:
    """Represents a single GEM temperature-sensor channel"""
    def __init__(self, monitor, number):
        self._monitor = monitor
        self.number = number
        self.temperature = None
        self._listeners = []

    def add_listener(self, listener):
        self._listeners.append(listener)

    def remove_listener(self, listener):
        self._listeners.remove(listener)

    async def handle_packet(self, packet):
        new_value = packet.temperatures[self.number]
        if new_value == self.temperature:
            return

        self.temperature = new_value
        for listener in self._listeners:
            await asyncio.coroutine(listener)()


class Channel:
    """Represents a single GEM CT channel"""
    def __init__(self, monitor, number):
        self._monitor = monitor
        self.number = number
        self.total_absolute_watt_seconds = None
        self.total_polarized_watt_seconds = None
        self.absolute_watt_seconds = None
        self.polarized_watt_seconds = None
        self.amps = None
        self.seconds = None
        self.watts = None
        self.timestamp = None
        self._listeners = []

    @property
    def absolute_kilowatt_hours(self):
        if self.absolute_watt_seconds is None:
            return None

        return \
            self.absolute_watt_seconds / WATTS_PER_KILOWATT / SECONDS_PER_HOUR

    @property
    def polarized_kilowatt_hours(self):
        if self.polarized_watt_seconds is None:
            return None

        return \
            self.polarized_watt_seconds / WATTS_PER_KILOWATT / SECONDS_PER_HOUR

    def add_listener(self, listener):
        self._listeners.append(listener)

    def remove_listener(self, listener):
        self._listeners.remove(listener)

    async def handle_packet(self, packet):
        new_absolute_watt_seconds = packet.absolute_watt_seconds[self.number]
        new_polarized_watt_seconds = packet.polarized_watt_seconds[self.number] if hasattr(packet, 'polarized_watt_seconds') else None
        new_amps = packet.currents[self.number] if hasattr(packet, 'currents') else None

        if (self.absolute_watt_seconds == new_absolute_watt_seconds
                and self.polarized_watt_seconds == new_polarized_watt_seconds
                and self.amps == new_amps
                and self.watts == 0):
            # Nothing changed
            return

        if self.seconds is not None:
            elapsed_seconds = _compute_delta(
                earlier_sample=self.seconds,
                later_sample=packet.seconds,
                max_value=packet.max_seconds)

            # This is the total energy produced or consumed since the last
            # sample.
            delta_total_watt_seconds = _compute_delta(
                earlier_sample=self.absolute_watt_seconds,
                later_sample=new_absolute_watt_seconds,
                max_value=packet.max_absolute_watt_seconds)

            # This is the energy produced since the last sample. This will be 0
            # for all channels except for channels in NET metering mode that
            # are actually producing electricity.
            if self.polarized_watt_seconds is not None and new_polarized_watt_seconds is not None:
                delta_watt_seconds_produced = _compute_delta(
                    earlier_sample=self.polarized_watt_seconds,
                    later_sample=new_polarized_watt_seconds,
                    max_value=packet.max_polarized_watt_seconds)
            else:
                delta_watt_seconds_produced = 0

            # This is the energy consumed since the last sample.
            delta_watt_seconds_consumed = \
                delta_total_watt_seconds - delta_watt_seconds_produced

            # Now compute the average power over the time since the last sample
            self.watts = \
                (delta_watt_seconds_consumed - delta_watt_seconds_produced) \
                / elapsed_seconds

        self.seconds = packet.seconds
        self.absolute_watt_seconds = new_absolute_watt_seconds
        self.polarized_watt_seconds = new_polarized_watt_seconds
        self.amps = new_amps
        self.timestamp = packet.time_stamp

        for listener in self._listeners:
            await asyncio.coroutine(listener)()


def _compute_delta(
        earlier_sample,
        later_sample,
        max_value):
    """Computes the difference between two samples of a value, considering
    that the value may have wrapped around in between"""
    if earlier_sample > later_sample:
        # Wraparound occurred
        return later_sample - (max_value - earlier_sample)

    return later_sample - earlier_sample


class Monitor:
    """Represents a single GreenEye Monitor"""
    def __init__(self, serial_number):
        """serial_number is the 8 digit serial number as it appears in the GEM
        UI"""
        self.serial_number = serial_number
        self.channels = []
        self.pulse_counters = []
        self.temperature_sensors = []
        self.voltage = None
        self._packet_interval = 0
        self._last_packet_seconds = None
        self._listeners = []

    def set_packet_interval(self, seconds):
        self._packet_interval = seconds

    def add_listener(self, listener):
        self._listeners.append(listener)

    def remove_listener(self, listener):
        self._listeners.remove(listener)

    async def handle_packet(self, packet):
        if self._last_packet_seconds is not None:
            elapsed_seconds = _compute_delta(
                earlier_sample=self._last_packet_seconds,
                later_sample=packet.seconds,
                max_value=packet.max_seconds)

            if elapsed_seconds < self._packet_interval:
                return
        self._last_packet_seconds = packet.seconds

        while len(self.channels) < packet.num_channels:
            self.channels.append(Channel(self, len(self.channels)))
        while len(self.pulse_counters) < len(packet.pulse_counts):
            self.pulse_counters.append(
                PulseCounter(self, len(self.pulse_counters)))
        while len(self.temperature_sensors) < len(packet.temperatures):
            self.temperature_sensors.append(
                TemperatureSensor(self, len(self.temperature_sensors)))

        self.voltage = packet.voltage
        for channel in self.channels:
            await channel.handle_packet(packet)
        for temperature_sensor in self.temperature_sensors:
            await temperature_sensor.handle_packet(packet)
        for pulse_counter in self.pulse_counters:
            await pulse_counter.handle_packet(packet)
        for listener in self._listeners:
            await asyncio.coroutine(listener)()


class MonitoringServer:
    """Listens for connections from GEMs and notifies a listener of each
    packet."""
    def __init__(self, port, listener):
        self._port = port
        self._server = None
        self._connections = set()
        self._listener = listener

    async def start(self):
        self._server = await asyncio.start_server(
            self._on_client_connected,
            None,
            self._port,
            family=socket.AF_INET)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        # Disallow new connections
        self._server.close()

        # Close out existing connections
        for connection in self._connections:
            connection.cancel()
        await asyncio.wait(self._connections)

        # Wait for shutdown
        await self._server.wait_closed()

    async def _on_client_connected(self, client_reader, client_writer):
        conn = asyncio.ensure_future(self._handle_packets(
            ServerPacketIterator(client_reader, client_writer)))
        self._connections.add(conn)

        await conn

    async def _handle_packets(self, packets):
        async with packets:
            async for packet in packets:
                await asyncio.coroutine(self._listener)(packet)


class Monitors:
    """Keeps track of all monitors that have reported data"""
    def __init__(self):
        self.monitors = {}
        self._listeners = []

    def add_listener(self, listener):
        self._listeners.append(listener)

    def remove_listener(self, listener):
        self._listeners.remove(listener)

    async def start_server(self, port):
        result = MonitoringServer(port, self._handle_packet)
        await result.start()
        return result

    async def _handle_packet(self, packet):
        serial_number = packet.device_id * 100000 + packet.serial_number
        new_monitor = False
        if serial_number not in self.monitors:
            LOG.info("Discovered new monitor: %s", serial_number)
            self.monitors[serial_number] = Monitor(serial_number)
            new_monitor = True

        monitor = self.monitors[serial_number]
        await monitor.handle_packet(packet)

        if new_monitor:
            await asyncio.wait([asyncio.coroutine(listener)(monitor)
                                for listener in self._listeners])
