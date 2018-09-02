==================
`greeneye-monitor`
==================

Receive data from your `GreenEye Monitor <http://www.brultech.com/greeneye/>`_ in Python.

This module provides a layered API for parsing individual packets (`greeneye.packets`), processing streams of packets
(`greeneye.streams`), or monitoring the current state reported by one or more monitors (`greeneye.monitor`). It's an
API intended to be integrated with other systems; it does not itself provide those integrations or any sort of data
storage. If you're looking for something like that, check out
`btmon.py <https://github.com/matthewwall/mtools/blob/master/bin/btmon.py>`_.

Features include:
* Parsing for all binary packet formats
* Receive data from multiple monitors
* Computes rate-of-change (Watts, pulses/sec) in addition to reporting total values

***********
Quick start
***********

API Usage
=========
See `dump_packets.py <https://github.com/jkeljo/greeneye-monitor/blob/master/dump_packets.py>`_ for a simple usage example.

GEM Setup
=========
Your GEM must be set to send binary format packets (formats that begin with Bin, e.g. Bin32 NET) to
the IP address of the computer on which you're running this software.
Your `GEM configuration manual <https://www.brultech.com/software/files/downloadSoft/GEM_Configuration_CFG_ver3_2.pdf>`_
is the canonical source for how to do this, but here are the steps as of this writing:

1. Navigate to your GEM's web UI (`http://<GEM IP>:8000`)
2. Click "Enter Setup Mode"
3. Click the "Packet Send" tab
4. Set the "Primary (Com1) Packet Format" to one of the "Bin" formats. I recommend:
    * Bin32 ABS if you have a 32-channel GEM with no channels set for net metering
    * Bin32 NET if you have a 32-channel GEM and some channels are set for net metering
    * Bin48 ABS if you have a 48-channel GEM with no channels set for net metering
    * Bin48 NET if you have a 48-channel GEM and some channels are set for net metering
5. Set the "Packet Send Interval" if you want something other than the default
6. Click "Save"
7. Click the "Network" tab
8. Enter the IP address of the computer on which you'll be running this software, and the port of your choice
9. Click "Save"
10. Click "Return" when it becomes available
11. Click "Exit Setup Mode"
