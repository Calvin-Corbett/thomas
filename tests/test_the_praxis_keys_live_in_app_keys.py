"""The Praxis keys and the two port helpers live in app_keys, and the old places still give the same things.

Nine files read a Praxis registry key or the port the server listens on. They used to import Praxis code at the top
only for that, so loading any one of them loaded Praxis too. This holds that the key move changed no value, that the
old names still resolve, and that importing launch no longer loads the Claude child runner, the run journal or the
Praxis routes.
"""

import subprocess
import sys
from pathlib import Path

from thomas.server import app_keys
from thomas.server.praxis import launch
from thomas.server.routes import evolve_agent_autopilot

ROOT = Path(__file__).resolve().parents[1]

KEYS = {
    "APP_PRAXIS_START_CODE_RUN": "praxis_start_code_run",
    "APP_PRAXIS_STOP_CODE_RUN": "praxis_stop_code_run",
    "APP_PRAXIS_RECOVERY_REPORT": "praxis_recovery_report",
    "APP_PRAXIS_RUN_CHANNELS": "praxis_run_channels",
}


def test_the_praxis_keys_keep_their_values():
    for name, value in KEYS.items():
        assert getattr(app_keys, name) == value


def test_the_old_names_still_give_the_same_keys_and_helpers():
    assert launch.APP_PRAXIS_START_CODE_RUN == app_keys.APP_PRAXIS_START_CODE_RUN
    assert launch.APP_PRAXIS_STOP_CODE_RUN == app_keys.APP_PRAXIS_STOP_CODE_RUN
    assert launch.APP_PRAXIS_RUN_CHANNELS == app_keys.APP_PRAXIS_RUN_CHANNELS
    assert launch.local_port is app_keys.local_port
    assert evolve_agent_autopilot.remember_port is app_keys.remember_port


def test_remember_port_is_read_back_by_local_port_when_the_socket_is_gone():
    class Transport:
        def get_extra_info(self, _name):
            return None

    class Request:
        transport = Transport()
        app: dict = {}

    request = Request()
    app_keys.remember_port(request.app, 4321)
    assert app_keys.local_port(request) == 4321


def test_importing_launch_does_not_load_the_run_channel_code():
    probe = (
        "import sys\n"
        "import thomas.server.praxis.launch\n"
        "loaded = [m for m in ('thomas.server.praxis.claude_child', 'thomas.server.praxis.recovery',"
        " 'thomas.server.routes.praxis_run_routes') if m in sys.modules]\n"
        "print(','.join(loaded))\n"
    )
    done = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == ""
