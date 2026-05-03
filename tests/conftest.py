"""Pytest conftest — mock EDMC modules so SpanshTools can be imported outside EDMC."""

import gc
import os
import shutil
import sys
import tkinter as tk
import types
import tempfile
import json
import pytest
from unittest.mock import MagicMock

_TESTS_DIR = os.path.dirname(__file__)
_PLUGIN_ROOT = os.path.dirname(_TESTS_DIR)

with open(os.path.join(_PLUGIN_ROOT, "version.json"), "r", encoding="utf-8") as _handle:
    PLUGIN_VERSION = json.load(_handle)["version"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STANDARD_5A_FSD_SPEC = {
    "class": 5,
    "rating": "A",
    "optimal_mass": 1050.0,
    "max_fuel_per_jump": 5.0,
    "fuel_power": 2.45,
    "fuel_multiplier": 0.012,
    "supercharge_multiplier": 4,
}


def bump_patch(version):
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Unsupported version format: {version}")
    major, minor, patch = parts
    return f"{major}.{minor}.{int(patch) + 1}"

# ---------------------------------------------------------------------------
# EDMC module mocks
# ---------------------------------------------------------------------------
_config = types.ModuleType("config")
_config.appname = "EDMarketConnector"
# PlaceHolder.py does `from config import config` and calls config.get_int(), config.get_str()
_config_store = {}
_config_obj = MagicMock()
_config_obj.get_int.side_effect = lambda key, default=0: _config_store.get(key, default)
_config_obj.get_str.side_effect = lambda key, default="": _config_store.get(key, default) if key != 'dark_text' else "black"
_config_obj.get_bool.side_effect = lambda key, default=False: _config_store.get(key, default)
_config_obj.set.side_effect = lambda key, val: _config_store.__setitem__(key, val)
_config.config = _config_obj
sys.modules["config"] = _config

_monitor_mod = types.ModuleType("monitor")
_monitor_obj = MagicMock()
_monitor_obj.state = {"SystemName": "Sol"}
_monitor_obj.ship.return_value = None
_monitor_mod.monitor = _monitor_obj
sys.modules["monitor"] = _monitor_mod

# Mock EDMCOverlay so overlay detection works
_edmc_overlay_pkg = types.ModuleType("EDMCOverlay")
_edmcoverlay_mod = types.ModuleType("EDMCOverlay.edmcoverlay")

class _MockOverlay:
    def __init__(self):
        pass

    def send_message(self, *args, **kwargs):
        pass
    def connect(self):
        pass

_edmcoverlay_mod.Overlay = _MockOverlay
_edmc_overlay_pkg.edmcoverlay = _edmcoverlay_mod
sys.modules["EDMCOverlay"] = _edmc_overlay_pkg
sys.modules["EDMCOverlay.edmcoverlay"] = _edmcoverlay_mod

# Mock overlay_plugin.overlay_api
_overlay_plugin = types.ModuleType("overlay_plugin")
_overlay_api = types.ModuleType("overlay_plugin.overlay_api")
_overlay_api.send_overlay_message = MagicMock(return_value=True)
_overlay_plugin.overlay_api = _overlay_api
sys.modules["overlay_plugin"] = _overlay_plugin
sys.modules["overlay_plugin.overlay_api"] = _overlay_api

# Create a Tcl interpreter so tkinter variables work without a display
_root = tk.Tcl()
tk._default_root = _root


# ---------------------------------------------------------------------------
# Dummy test classes
# ---------------------------------------------------------------------------

class DummyWidget:
    def __init__(self):
        self.visible = False
        self.config_calls = []
        self._exists = True

    def grid(self, *args, **kwargs):
        self.visible = True

    def grid_remove(self, *args, **kwargs):
        self.visible = False

    def pack(self, *args, **kwargs):
        self.visible = True

    def pack_forget(self, *args, **kwargs):
        self.visible = False

    def config(self, *args, **kwargs):
        self.config_calls.append((args, kwargs))

    configure = config

    def winfo_exists(self):
        return self._exists

    def event_generate(self, *_args, **_kwargs):
        pass

    def bind(self, *_args, **_kwargs):
        pass


class DummyFrame(DummyWidget):
    def after(self, delay, func, *args):
        return func(*args)


class DummyAC:
    """Fake AutoCompleter widget for tests that set up plotter fields."""

    def __init__(self, text, placeholder=""):
        self._text = text
        self.placeholder = placeholder

    def get(self):
        return self._text

    def hide_list(self):
        pass

    def set_text(self, text, _placeholder_style=False):
        self._text = text

    def is_effectively_empty(self):
        return not self._text or self._text == self.placeholder


class DummyEntry:
    """Fake Entry/Spinbox widget for tests that read form values."""

    def __init__(self, value, minimum=0, maximum=100):
        self._value = value
        self._minimum = minimum
        self._maximum = maximum

    def get(self):
        return self._value

    def delete(self, *_args, **_kwargs):
        self._value = ""

    def insert(self, _index, value):
        self._value = str(value)

    def cget(self, key):
        if key == "from":
            return self._minimum
        if key == "to":
            return self._maximum
        raise KeyError(key)


class DummyParent:
    def clipboard_clear(self):
        pass

    def clipboard_append(self, text):
        self._clipboard = text

    def update(self):
        pass

    def winfo_pointerx(self):
        return 0

    def winfo_pointery(self):
        return 0


# ---------------------------------------------------------------------------
# Factory & fixture
# ---------------------------------------------------------------------------

def create_router(SpanshTools):
    tmpdir = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmpdir, "SpanshTools", "data"), exist_ok=True)
    with open(os.path.join(tmpdir, "version.json"), "w") as f:
        f.write(f'{{"version": "{PLUGIN_VERSION}"}}')
    router = SpanshTools(tmpdir)
    router._tmpdir = tmpdir
    router.parent = DummyParent()
    router.frame = DummyFrame()
    router.plotter_win = None
    router.overlay_cb_frame = DummyWidget()
    router.overlay_pos_frame = DummyWidget()
    router.neutron_pos_frame = DummyWidget()
    router.bodies_lbl = DummyWidget()
    router.fleetrestock_lbl = DummyWidget()
    router.refuel_lbl = DummyWidget()
    router.waypoint_prev_btn = DummyWidget()
    router.waypoint_btn = DummyWidget()
    router.waypoint_next_btn = DummyWidget()
    router.jumpcounttxt_lbl = DummyWidget()
    router.dist_prev_lbl = DummyWidget()
    router.dist_next_lbl = DummyWidget()
    router.dist_remaining_lbl = DummyWidget()
    router.planner_dropdown = DummyWidget()
    router.plot_btn = DummyWidget()
    router.csv_route_btn = DummyWidget()
    router.nearest_btn = DummyWidget()
    router.clear_route_btn = DummyWidget()
    router.show_csv_btn = DummyWidget()
    router.overlay_var = tk.BooleanVar(master=_root, value=False)
    router.neutron_overlay_var = tk.BooleanVar(master=_root, value=False)
    router.overlay_x_var = tk.IntVar(master=_root, value=590)
    router.overlay_y_var = tk.IntVar(master=_root, value=675)
    router.neutron_x_var = tk.IntVar(master=_root, value=600)
    router.neutron_y_var = tk.IntVar(master=_root, value=675)
    router._overlay_loading = False
    router.update_gui = MagicMock()
    router.copy_waypoint = MagicMock()
    # Compat shim: tests reference save_route_path (removed from source).
    # Provide a path in the temp dir so JSON tests can derive .json paths.
    router.save_route_path = os.path.join(tmpdir, "SpanshTools", "data", "route.csv")
    return router

@pytest.fixture
def router(tmp_path):
    """Provides a fresh, mocked router instance using pytest tmp_path."""
    from SpanshTools.core import SpanshTools
    router_instance = create_router(SpanshTools)
    # create_router already makes a tempdir; clean it up and switch to pytest's tmp_path
    original_tmpdir = router_instance._tmpdir
    router_instance._tmpdir = str(tmp_path)
    router_instance.plugin_dir = str(tmp_path)
    data_dir = os.path.join(str(tmp_path), "SpanshTools", "data")
    os.makedirs(data_dir, exist_ok=True)
    router_instance.save_route_path = os.path.join(data_dir, "route.csv")
    router_instance.plotter_settings_path = os.path.join(data_dir, "plotter_settings.json")
    shutil.rmtree(original_tmpdir, ignore_errors=True)
    try:
        yield router_instance
    finally:
        for name, value in list(vars(router_instance).items()):
            if isinstance(value, tk.Variable):
                setattr(router_instance, name, None)
        gc.collect()
