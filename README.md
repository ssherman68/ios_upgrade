ios_upgrade.py

Original Version: Stacy Sherman 8/24/16

This script in its current form upgrades a dual supervisor Cisco
6500 series switch to the given version of IOS.

Assumes that the new IOS file has already been copied to all 
switches/supervisors.

Libraries required: netmiko, getpass, time

There is a timing issue in the mon_reload_sup function. Worked in testing
but did not work on production switch. Easily fixable with some testing.

This script was mostly done as a learning exercise. A lot of the code can be
re-used for similar scripts.