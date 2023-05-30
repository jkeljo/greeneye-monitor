import aiohttp
from argparse import ArgumentParser
import asyncio
import logging
import sys
from typing import Tuple

from siobrultech_protocols.gem.packets import PacketFormatType

from greeneye.monitor import (
    Aux,
    Channel,
    Monitor,
    MonitorType,
    Monitors,
    PulseCounter,
    TemperatureSensor,
    VoltageSensor,
)

num_packets = 0


async def main():
    parser = ArgumentParser()
    subcommands = parser.add_subparsers(dest="subcommand")

    listen_command = subcommands.add_parser(
        "listen", description="Listens for incoming connections from GEMs."
    )
    listen_command.add_argument(
        "port", help="Port on which to listen for incoming GEM packets."
    )

    spy_command = subcommands.add_parser(
        "spy",
        description="Connects to a GEM at the given IP and spies on whatever packets it is sending (regardless of their destination).",
    )
    spy_command.add_argument(
        "host", help="Hostname or IP address of the GEM to which to connect."
    )

    redirect_command = subcommands.add_parser(
        "redirect",
        description="Connects to a GEM and redirects its packets to this machine, redirecting back afterwards.",
    )
    redirect_command.add_argument(
        "--gem", required=True, help="Hostname or IP address of the GEM."
    )
    redirect_command.add_argument(
        "--redirect-to-host",
        required=True,
        help="Hostname of the machine to redirect packets to.",
    )
    redirect_command.add_argument(
        "--redirect-to-port",
        type=int,
        required=True,
        help="Port of the machine to redirect packets to.",
    )
    redirect_command.add_argument(
        "--restore-to-host",
        required=True,
        help="Hostname of the target machine to restore after the run.",
    )
    redirect_command.add_argument(
        "--restore-to-port",
        type=int,
        required=True,
        help="Port of the target machine to restore after the run.",
    )

    args = parser.parse_args()
    if args.subcommand == "listen":
        await listen(args.port)
    elif args.subcommand == "spy":
        await spy(args.host)
    elif args.subcommand == "redirect":
        await redirect(
            gem=args.gem,
            original=(args.restore_to_host, args.restore_to_port),
            redirect=(args.redirect_to_host, args.redirect_to_port),
        )
    else:
        print(f"Unknown subcommand: {args.subcommand}")
        sys.exit(-1)


async def listen(port: int) -> None:
    async with Monitors() as monitors:
        monitors.add_listener(on_new_monitor)
        await monitors.start_server(port)
        while True:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break


async def spy(host: str) -> None:
    async with Monitors() as monitors:
        monitors.add_listener(on_new_monitor)
        monitor = await monitors.connect(host)
        while True:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break


async def redirect(
    gem: str, original=Tuple[str, int], redirect=Tuple[str, int]
) -> None:
    async with aiohttp.ClientSession() as session:
        async with Monitors() as monitors:
            monitor = await monitors.connect(gem)
            old_packet_format = monitor.packet_format
            assert old_packet_format
            if not monitor.control:
                raise Exception("Could not get monitor control interface")
            await monitor.control.set_packet_format(PacketFormatType.BIN48_NET_TIME)
            await monitor.control.set_packet_destination(
                redirect[0], redirect[1], session
            )

        await listen(redirect[1])

        async with Monitors() as monitors:
            monitor = await monitors.connect(gem)
            if not monitor.control:
                raise Exception("Could not get monitor control interface")
            await monitor.control.set_packet_format(old_packet_format)
            await monitor.control.set_packet_destination(
                original[0], original[1], session
            )


def on_new_monitor(monitor: Monitor):
    monitor.add_listener(lambda: print_monitor(monitor))

    monitor.voltage_sensor.add_listener(lambda: print_voltage(monitor.voltage_sensor))

    if monitor.type != MonitorType.GEM:
        for channel in monitor.channels:
            channel.net_metering = False

    for channel in monitor.channels:
        on_new_channel(channel)

    for counter in monitor.pulse_counters:
        on_new_counter(counter)

    for temp in monitor.temperature_sensors:
        on_new_temperature_sensor(temp)

    for aux in monitor.aux:
        on_new_aux(aux)


def on_new_channel(channel: Channel):
    channel.add_listener(lambda: print_channel(channel))


def on_new_counter(counter: PulseCounter):
    counter.add_listener(lambda: print_counter(counter))


def on_new_temperature_sensor(temp: TemperatureSensor):
    temp.add_listener(lambda: print_temperature(temp))


def on_new_aux(aux: Channel | Aux):
    if isinstance(aux, Channel):
        on_new_channel(aux)
    else:
        on_new_channel(aux.channel)
        on_new_counter(aux.pulse_counter)


def print_monitor(monitor: Monitor):
    print(
        f"Monitor {monitor.serial_number} ({monitor.type}) sending packets every {monitor.packet_send_interval}"
    )


def print_voltage(voltage_sensor: VoltageSensor):
    print(f"Voltage: {voltage_sensor.voltage} V")


def print_channel(channel: Channel):
    if channel.watts and channel.kilowatt_hours:
        print(
            "Channel {0} (type={4} range={5}): {1:.0f} W ({2:.3f} kWh {3})".format(
                channel.number,
                channel.watts,
                channel.kilowatt_hours,
                "net" if channel.net_metering else "abs",
                channel.ct_type,
                channel.ct_range,
            )
        )


def print_counter(counter: PulseCounter):
    print(
        "Pulse counter {0}: {1} ({2}/sec)".format(
            counter.number, counter.pulses, counter.pulses_per_second
        )
    )


def print_temperature(sensor: TemperatureSensor):
    print(
        "Temperature sensor {0}: {1} {2}".format(
            sensor.number, sensor.temperature, sensor.unit
        )
    )


if __name__ == "__main__":
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s](%(levelname)s) %(message)s",
    )

    loop = asyncio.get_event_loop()
    task = asyncio.ensure_future(main())
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
    loop.close()
