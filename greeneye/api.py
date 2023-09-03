from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, unique
from itertools import chain
from typing import Any, Optional, Tuple

import aiohttp
from siobrultech_protocols.gem.api import call_api
from siobrultech_protocols.gem.packets import PacketFormatType
from siobrultech_protocols.gem.protocol import ApiCall, ApiType, BidirectionalProtocol

LOG = logging.getLogger(__name__)


async def set_packet_destination(
    gem_host: str, dest_host: str, dest_port: int, session: aiohttp.ClientSession
) -> None:
    # Set target
    LOG.debug("%s: Setting target to %s:%d", gem_host, dest_host, dest_port)
    async with session.get(
        f"http://{gem_host}:8000/1?DNS={dest_host}&PTH={dest_port}"
    ) as resp:
        await resp.read()
        resp.raise_for_status()

    LOG.debug("Sleeping 20 seconds to simulate the GEM UI delay...")
    await asyncio.sleep(20)

    LOG.debug("%s: Exiting setup", gem_host)
    # Exit setup mode (seems to help it actually start sending packets)
    async with session.get(f"http://{gem_host}:8000/z") as resp:
        await resp.read()
        resp.raise_for_status()


@unique
class TemperatureUnit(Enum):
    CELSIUS = "C"
    FAHRENHEIT = "F"


@dataclass(frozen=True)
class GemSettings:
    packet_format: PacketFormatType | None
    packet_send_interval: timedelta
    num_channels: int
    temperature_unit: TemperatureUnit | None
    channel_net_metering: list[bool | None]
    ct_types: list[int]
    ct_ranges: list[int]


async def get_all_settings(
    protocol: BidirectionalProtocol,
    serial_number: Optional[int] = None,
    timeout: timedelta | None = None,
) -> GemSettings:
    async with call_api(_GET_ALL_SETTINGS, protocol, serial_number, timeout) as f:
        return await f(None)


async def send_one_packet(
    protocol: BidirectionalProtocol, serial_number: Optional[int] = None
) -> None:
    async with call_api(_SEND_ONE_PACKET, protocol, serial_number) as f:
        return await f(None)


async def set_ct_type(
    protocol: BidirectionalProtocol,
    channel: int,
    type: int,
    serial_number: Optional[int] = None,
) -> None:
    assert protocol.api_type == ApiType.GEM
    async with call_api(_SET_CT_TYPE, protocol, serial_number) as f:
        await f((channel, type))


async def set_ct_range(
    protocol: BidirectionalProtocol,
    channel: int,
    range: int,
    serial_number: Optional[int] = None,
) -> None:
    assert protocol.api_type == ApiType.GEM
    async with call_api(_SET_CT_RANGE, protocol, serial_number) as f:
        await f((channel, range))


async def set_ct_type_and_range(
    protocol: BidirectionalProtocol,
    channel: int,
    type: int,
    range: int,
    serial_number: Optional[int] = None,
) -> None:
    if protocol.api_type == ApiType.GEM:
        await set_ct_type(protocol, channel, type, serial_number)
        await set_ct_range(protocol, channel, range, serial_number)
    elif protocol.api_type == ApiType.ECM:
        async with call_api(_SET_CT_TYPE_AND_RANGE, protocol, serial_number) as f:
            await f((channel, type, range))
    else:
        assert False


_ALL_SETTINGS_RESPONSE_PREFIX = "ALL\r\n"


def _parse_all_settings(response: str) -> GemSettings | None:
    if len(response) < 1542:
        return None
    assert response.startswith(_ALL_SETTINGS_RESPONSE_PREFIX)
    binary = bytes.fromhex(
        response[len(_ALL_SETTINGS_RESPONSE_PREFIX) :].replace(",", "")
    )
    offset = 0

    def unpack(format: str | bytes) -> Tuple[Any, ...]:
        nonlocal binary
        nonlocal offset
        size = struct.calcsize(format)
        result = struct.unpack_from(format, binary, offset)
        offset += size
        return result

    # Unpack all the options defined in the docs. The docs are somewhat spotty, and we
    # only currently need a few of these, so we're exposing only a few accessors.
    _channel_options = unpack("x48B")
    channel_net_metering = [options & 0x40 == 0 for options in _channel_options]
    _channel_polarity_toggled = [options & 0x80 == 0x80 for options in _channel_options]
    ct_types = list(unpack("48B"))
    ct_ranges = list(
        chain.from_iterable([[b & 0x0F, (b & 0xF0) >> 4] for b in unpack("24B")])
    )  # These are actually one nybble per CT
    _pt_type = unpack("B")[0]
    _pt_range = unpack("B")[0]
    _packet_format_int = unpack("B")[0]
    try:
        packet_format = PacketFormatType(_packet_format_int)
    except ValueError:
        packet_format = None
    packet_send_interval = timedelta(seconds=unpack("B")[0])
    _wifi_auto_reset_timer = unpack("B")[0]
    _wifi_missing_response_reset = unpack("B")[0]
    _cop_timeout = unpack("B")[0]
    _xbee_auto_reset_timer = unpack("B")[0]
    _eng_offset = unpack("B")[0]
    _com2_packet_format = unpack("B")[0]
    _number_of_ecm1240_to_simulate = unpack("B")[0]
    _channel_packet_options = unpack("48B")
    _counter_options = unpack("B")[0]  # TODO: it's only bits 0-3
    _temperature_enable = unpack("B")[0]  # TODO: 8 individual bits
    _temperature_rom_codes = [
        unpack("8s")[0],
        unpack("8s")[0],
        unpack("8s")[0],
        unpack("8s")[0],
        unpack("8s")[0],
        unpack("8s")[0],
        unpack("8s")[0],
        unpack("8s")[0],
    ]
    _temperature_channel_enabled_to_be_converted_and_read = unpack("B")[0]
    _com2_missing_response_counter = unpack("B")[0]
    _hardware_modules_installed = unpack("B")[0]
    num_channels = unpack("B")[0]
    _system_options = unpack("B")[0]
    unpack("40x")
    _setup_password = unpack("7s")[0]
    _current_constant = unpack("B")[0]
    unpack("7x")
    _channels_for_http_put = unpack("6B")  # bits
    _pulse_counters_for_http_put = unpack("B")  # bits 0-3
    _temperature_channels_for_http_put = unpack("B")  # bits
    _general_packet_options = unpack("H")[0]
    _net_metering_options = unpack("B")[0]
    _chunk_size = unpack(">H")[0]
    _enabled_pulse_counters = unpack("B")[0]
    _flags = unpack("B")[0]
    temperature_unit = (
        TemperatureUnit.FAHRENHEIT if _flags & 0x10 else TemperatureUnit.CELSIUS
    )
    _inter_chunk_time = unpack(">H")[0]
    _buffer_full_address = unpack("H")[0]

    channel_net_metering = channel_net_metering[:num_channels]

    return GemSettings(
        packet_format=packet_format,
        packet_send_interval=packet_send_interval,
        num_channels=num_channels,
        temperature_unit=temperature_unit,
        channel_net_metering=channel_net_metering,
        ct_types=ct_types,
        ct_ranges=ct_ranges,
    )


def _parse_all_ecm_settings(binary: bytes) -> GemSettings | None:
    if len(binary) < 33:
        return None

    offset = 0

    def unpack(format: str | bytes) -> Tuple[Any, ...]:
        nonlocal binary
        nonlocal offset
        size = struct.calcsize(format)
        result = struct.unpack_from(format, binary, offset)
        offset += size
        return result

    actual_sum = sum(binary[:32])

    ct1_type = unpack("B")[0]
    ct1_range = unpack("B")[0]
    ct2_type = unpack("B")[0]
    ct2_range = unpack("B")[0]
    ct_types = [ct1_type, ct2_type]
    ct_ranges = [ct1_range, ct2_range]
    _pt_type = unpack("B")[0]
    _pt_range = unpack("B")[0]
    packet_send_interval = timedelta(seconds=unpack("B")[0])
    _data_logger_interval = unpack("B")[0]
    _firmware_version = unpack(">H")[0]
    _device_id = unpack("B")[0]
    _serial_number = unpack(">H")[0]
    unpack("16x")
    _trigger_value = unpack("<H")[0]
    zero = unpack("B")[0]
    assert zero == 0
    checksum = unpack("B")[0]
    assert checksum == actual_sum % 256

    return GemSettings(
        packet_format=PacketFormatType.ECM_1220,
        packet_send_interval=packet_send_interval,
        num_channels=2,
        temperature_unit=None,
        channel_net_metering=[None, None],
        ct_types=ct_types,
        ct_ranges=ct_ranges,
    )


_CMD_GET_ALL_SETTINGS = "^^^RQSALL"
_GET_ALL_SETTINGS = ApiCall[None, GemSettings](
    gem_formatter=lambda _: _CMD_GET_ALL_SETTINGS,
    gem_parser=_parse_all_settings,
    ecm_formatter=lambda _: [b"\xfc", b"SET", b"RCV"],
    ecm_parser=_parse_all_ecm_settings,
)

_CMD_SEND_ONE_PACKET = "^^^APISPK"
_SEND_ONE_PACKET = ApiCall[None, None](
    gem_formatter=lambda _: _CMD_SEND_ONE_PACKET,
    gem_parser=None,
    ecm_formatter=None,
    ecm_parser=None,
)

_SET_CT_TYPE = ApiCall[Tuple[int, int], None](
    gem_formatter=lambda args: f"^^^C{args[0]:02}TYP{args[1]}",
    gem_parser=None,
    ecm_formatter=None,
    ecm_parser=None,
)
_SET_CT_RANGE = ApiCall[Tuple[int, int], None](
    gem_formatter=lambda args: f"^^^C{args[0]:02}RNG{args[1]}",
    gem_parser=None,
    ecm_formatter=None,
    ecm_parser=None,
)
_SET_CT_TYPE_AND_RANGE = ApiCall[Tuple[int, int, int], None](
    gem_formatter=None,  # type: ignore
    gem_parser=None,
    ecm_formatter=lambda args: [
        b"\xfc",
        b"SET",
        f"CT{args[0]}".encode(),
        b"TYP",
        bytes([args[1]]),
        b"RNG",
        bytes([args[2]]),
    ],
    ecm_parser=None,
)
