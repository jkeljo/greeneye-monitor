Changelog
*********

greeneye-monitor
++++++++++++++++

[4.0.1] - 2023-08-06
====================
Fixed
-----
* Don't re-create PulseCounter objects when re-configuring a Monitor from settings

[4.0] - 2023-05-30
==================
New Features
------------
* Support for ECM-1220 and ECM-1240, including basic API support
* API support for setting packet interval and CT type and range
* Generally faster and more robust

Fixed
-----
* Don't crash when monitors ignore API calls (e.g. if there is a DashBox in the middle)
* Don't crash if two packets come in with no seconds in between

[3.0.3] - 2022-02-20
====================

Fixed
-----
* Fixed a typo

[3.0.2] - 2022-02-20
====================

Fixed
-----
* Fixed an issue where we would add Monitor objects to the lookup map before they were completely initialized

[3.0.1] - 2022-01-06
====================

Fixed
-----
* Added a few missing types

[3.0] - 2022-01-06
==================

New Features
------------
* Connect to a GEM by hostname or IP address
* `Channel`s now know if they are configured for net metering. `kilowatt_hours` property takes that into account.
* `TemperatureSensor`s now know what unit they are reporting.
* Full `py.typed` info is now provided
* Configure where the GEM sends its packets using `Monitor.set_packet_destination`
* Configure what format of packet the GEM sends using `Monitor.set_packet_format`

Changed
-------
* Voltage is now reported as a `VoltageSensor` instead of a property of the `Monitor` (breaking change)
* `Monitors.start_server` now returns `None` (breaking change)
* `Monitors` now has a `close` method that must be called, and is now an async context manager (breaking change)

Fixed
-----
* Closing `Monitors` will now close all existing connections
* Deltas for values that have wrapped around are now computed correctly

[2.1] - 2020-07-30
==================

Fixed
-----
* Fixed issue where negative temperatures were not handled correctly (thanks @drkp!)

[2.0] - 2020-02-16
==================

Fixed
-----
* Fixed issue where temperatures were reported as twice their actual value (breaking change)

[1.0.1] - 2019-10-31
====================

Changed
-------
* Rewrote stream parser to be more robust

Fixed
-----
* Fixed crash when no listeners are registered

[1.0] - 2018-12-25
==================

Changed
-------
* Use full 8-digit serial number as identification of monitor (instead of last 5 digits as appears in the packet `serial_number` field)

[0.1] - 2018-09-02
====================

Initial release.
