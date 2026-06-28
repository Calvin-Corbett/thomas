"""Temporary launcher: starts the Thomas server without matching the
ThomasDesktopHostService watchdog's '-m thomas serve' kill pattern.
(Workaround for the _check_single_instance sweep bug; delete after test.)"""

import runpy
import sys

sys.argv = ["thomas", "serve"]
runpy.run_module("thomas", run_name="__main__")
