import asyncio
import logging
import sys

from greeneye.monitor import Monitors

num_packets = 0


async def main(port):
    monitors = Monitors()
    monitors.add_listener(on_new_monitor)
    async with await monitors.start_server(port):
        while True:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break


def on_new_monitor(monitor):
    for channel in monitor.channels:
        on_new_channel(channel)

    for counter in monitor.pulse_counters:
        on_new_counter(counter)

    for temp in monitor.temperature_sensors:
        on_new_temperature_sensor(temp)


def on_new_channel(channel):
    channel.add_listener(lambda: print_channel(channel))


def on_new_counter(counter):
    counter.add_listener(lambda: print_counter(counter))


def on_new_temperature_sensor(temp):
    temp.add_listener(lambda: print_temperature(temp))


def print_channel(channel):
    print("Channel {0}: {1} W (abs={2} kWh, pol={3} kWh)".format(
        channel.number,
        channel.watts,
        channel.absolute_watt_seconds / 3600000,
        channel.polarized_watt_seconds / 3600000))


def print_counter(counter):
    print("Pulse counter {0}: {1} ({2}/sec)".format(
        counter.number,
        counter.pulses,
        counter.pulses_per_second
    ))


def print_temperature(sensor):
    print("Temperature sensor {0}: {1} F".format(
        sensor.number,
        sensor.temperature))


if __name__ == "__main__":
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG,
        format='%(asctime)s [%(name)s](%(levelname)s) %(message)s')

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