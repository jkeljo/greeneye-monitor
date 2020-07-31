Changelog
*********

greeneye-monitor
++++++++++++++++

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
