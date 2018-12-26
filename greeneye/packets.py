"""
Packet formats defined in
https://www.brultech.com/software/files/downloadSoft/GEM-PKT_Packet_Format_2_1.pdf
"""
import codecs
from collections import OrderedDict
import json

from .fields import *


class MalformedPacketException(Exception):
    pass


class Packet(object):
    def __init__(
            self,
            packet_format,
            voltage,
            absolute_watt_seconds,
            device_id,
            serial_number,
            seconds,
            pulse_counts,
            temperatures,
            polarized_watt_seconds=None,
            currents=None,
            time_stamp=None,
            **kwargs):
        self.packet_format = packet_format
        self.voltage = voltage
        self.absolute_watt_seconds = absolute_watt_seconds
        if polarized_watt_seconds:
            self.polarized_watt_seconds = polarized_watt_seconds
        if currents:
            self.currents = currents
        self.device_id = device_id
        self.serial_number = serial_number
        self.seconds = seconds
        self.pulse_counts = pulse_counts
        self.temperatures = temperatures
        if time_stamp:
            self.time_stamp = time_stamp
        else:
            self.time_stamp = datetime.now()

    def __str__(self):
        return json.dumps({
            'device_id': self.device_id,
            'serial_number': self.serial_number,
            'seconds': self.seconds,
            'voltage': self.voltage,
            'absolute_watt_seconds': self.absolute_watt_seconds,
            'polarized_watt_seconds': self.polarized_watt_seconds if hasattr(self, 'polarized_watt_seconds') else None,
            'currents': self.currents if hasattr(self, 'currents') else None,
            'pulse_counts': self.pulse_counts,
            'temperatures': self.temperatures,
            'time_stamp': self.time_stamp.isoformat()
        })

    @property
    def type(self):
        return self.packet_format.name

    @property
    def num_channels(self):
        return self.packet_format.num_channels

    @property
    def max_seconds(self):
        return self.packet_format.fields["seconds"].max

    @property
    def max_pulse_count(self):
        return self.packet_format.fields["pulse_counts"].elem_field.max

    @property
    def max_absolute_watt_seconds(self):
        return self.packet_format.fields["absolute_watt_seconds"].elem_field.max

    @property
    def max_polarized_watt_seconds(self):
        return self.packet_format.fields["polarized_watt_seconds"].elem_field.max


class PacketFormat(object):
    NUM_PULSE_COUNTERS = 4
    NUM_TEMPERATURE_SENSORS = 8

    def __init__(self, name, num_channels, has_net_metering=False,
                 has_time_stamp=False):
        self.name = name
        self.num_channels = num_channels
        self.fields = OrderedDict()

        self.fields["header"] = NumericField(3, hi_to_lo)
        self.fields["voltage"] = FloatingPointField(2, hi_to_lo, 10.0)
        self.fields["absolute_watt_seconds"] = \
            ArrayField(num_channels, NumericField(5, lo_to_hi))
        if has_net_metering:
            self.fields["polarized_watt_seconds"] = \
                ArrayField(num_channels, NumericField(5, lo_to_hi))
        self.fields["serial_number"] = NumericField(2, hi_to_lo)
        self.fields["reserved"] = ByteField()
        self.fields["device_id"] = NumericField(1, hi_to_lo)
        self.fields["currents"] = \
            ArrayField(num_channels, FloatingPointField(2, lo_to_hi, 50.0))
        self.fields["seconds"] = NumericField(3, lo_to_hi)
        self.fields["pulse_counts"] = ArrayField(
            PacketFormat.NUM_PULSE_COUNTERS,
            NumericField(3, lo_to_hi))
        self.fields["temperatures"] = ArrayField(
            PacketFormat.NUM_TEMPERATURE_SENSORS,
            NumericField(2, lo_to_hi))
        if num_channels == 32:
            self.fields["spare_bytes"] = BytesField(2)
        if has_time_stamp:
            self.fields["time_stamp"] = DateTimeField()
        self.fields["footer"] = NumericField(2, hi_to_lo)
        self.fields["checksum"] = ByteField()

    @property
    def size(self):
        result = 0
        for value in self.fields.values():
            result += value.size

        return result

    def parse(self, packet):
        _checksum(packet)

        offset = 0
        args = {
            "packet_format": self,
        }
        for key, value in self.fields.items():
            args[key] = value.read(packet, offset)
            offset += value.size

        if args["footer"] != 0xfffe:
            raise MalformedPacketException(
                "bad footer {0} in packet: {1}".format(
                    hex(args["footer"]),
                    codecs.encode(packet, 'hex')))

        return Packet(**args)


def _checksum(packet):
    checksum = 0
    for i in packet[:-1]:
        checksum += i
    checksum = checksum % 256
    if checksum != packet[-1]:
        raise MalformedPacketException(
            "bad checksum for packet: {0}".format(
                codecs.encode(packet, 'hex')))


BIN48_NET_TIME = PacketFormat(
    name="BIN48-NET-TIME",
    num_channels=48,
    has_net_metering=True,
    has_time_stamp=True)

BIN48_NET = PacketFormat(
    name="BIN48-NET",
    num_channels=48,
    has_net_metering=True,
    has_time_stamp=False)

BIN48_ABS = PacketFormat(
    name="BIN48-ABS",
    num_channels=48,
    has_net_metering=False,
    has_time_stamp=False)

BIN32_NET = PacketFormat(
    name="BIN32-NET",
    num_channels=32,
    has_net_metering=True,
    has_time_stamp=False)

BIN32_ABS = PacketFormat(
    name="BIN32-ABS",
    num_channels=32,
    has_net_metering=False,
    has_time_stamp=False)
