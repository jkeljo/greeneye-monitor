import asyncio
import logging
import sys

from greeneye.monitor import (
    Channel,
    Monitor,
    Monitors,
    PulseCounter,
    TemperatureSensor,
    VoltageSensor,
)

num_packets = 0


async def main(port):
    async with Monitors() as monitors:
        monitors.add_listener(on_new_monitor)
        await monitors.start_server(port)
        while True:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break


def on_new_monitor(monitor: Monitor):
    monitor.add_listener(lambda: print_monitor(monitor))

    monitor.voltage_sensor.add_listener(lambda: print_voltage(monitor.voltage_sensor))

    for channel in monitor.channels:
        on_new_channel(channel)

    for counter in monitor.pulse_counters:
        on_new_counter(counter)

    for temp in monitor.temperature_sensors:
        on_new_temperature_sensor(temp)


def on_new_channel(channel: Channel):
    channel.add_listener(lambda: print_channel(channel))


def on_new_counter(counter: PulseCounter):
    counter.add_listener(lambda: print_counter(counter))


def on_new_temperature_sensor(temp: TemperatureSensor):
    temp.add_listener(lambda: print_temperature(temp))


def print_monitor(monitor: Monitor):
    print(
        f"Monitor {monitor.serial_number} sending packets every {monitor.packet_send_interval}"
    )


def print_voltage(voltage_sensor: VoltageSensor):
    print(f"Voltage: {voltage_sensor.voltage} V")


def print_channel(channel: Channel):
    print(
        "Channel {0}: {1:.0f} W ({2:.3f} kWh {3})".format(
            channel.number,
            channel.watts,
            channel.kilowatt_hours,
            "net" if channel.net_metering else "abs",
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
    task = asyncio.ensure_future(main(int(sys.argv[1])))
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
    loop.close()
