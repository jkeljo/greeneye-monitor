from __future__ import annotations

import aiohttp
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, unique
import logging
from typing import Any, Optional, Tuple
from siobrultech_protocols.gem.api import (
    ApiCall,
    call_api,
)
from siobrultech_protocols.gem.packets import PacketFormatType
from siobrultech_protocols.gem.protocol import BidirectionalProtocol
import struct

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
    temperature_unit: TemperatureUnit
    channel_net_metering: list[bool]


async def get_all_settings(
    protocol: BidirectionalProtocol, serial_number: Optional[int] = None
) -> GemSettings:
    async with call_api(_GET_ALL_SETTINGS, protocol, serial_number) as f:
        return await f(None)


_ALL_SETTINGS_RESPONSE_PREFIX = "ALL\r\n"


def _parse_all_settings(response: str) -> GemSettings:
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

    # Unpack all the options defined in the docs. The docs are somewhat spotty, and we only currently
    # need a few of these, so we're exposing only a few accessors.
    _channel_options = unpack("x48B")
    channel_net_metering = [options & 0x40 == 0 for options in _channel_options]
    channel_polarity_toggled = [options & 0x80 == 0x80 for options in _channel_options]
    _ct_types = unpack("48B")
    _ct_ranges = unpack("24B")  # These are actually one nybble per CT
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
    )


_CMD_GET_ALL_SETTINGS = "^^^RQSALL"
_GET_ALL_SETTINGS = ApiCall[None, GemSettings](
    formatter=lambda _: _CMD_GET_ALL_SETTINGS, parser=_parse_all_settings
)
