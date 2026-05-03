"""Tests for SpanshTools.plotters -- exact, exploration, and fleet carrier."""

import sys
import os
import json
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
import SpanshTools.core as spans_mod
import SpanshTools.plotters as plotters_mod
from SpanshTools.core import SpanshTools
from conftest import DummyAC, DummyFrame, DummyWidget, DummyEntry, create_router, _root




# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOCK_ROUTE_DATA = {
    "status": "ok",
    "result": {
        "jumps": [
            {
                "name": "Sol",
                "distance": 0,
                "distance_to_destination": 100.5,
                "fuel_in_tank": 32.0,
                "fuel_used": 0,
                "has_neutron": False,
                "is_scoopable": False,
                "must_refuel": False,
                "id64": 10477373803,
                "x": 0, "y": 0, "z": 0,
            },
            {
                "name": "Alpha Centauri",
                "distance": 4.38,
                "distance_to_destination": 96.12,
                "fuel_in_tank": 31.9,
                "fuel_used": 0.1,
                "has_neutron": False,
                "is_scoopable": True,
                "must_refuel": True,
                "id64": 1178708478315,
                "x": 3.03, "y": -0.09, "z": 3.16,
            },
            {
                "name": "Barnard's Star",
                "distance": 5.95,
                "distance_to_destination": 90.17,
                "fuel_in_tank": 30.5,
                "fuel_used": 1.4,
                "has_neutron": False,
                "is_scoopable": True,
                "must_refuel": False,
                "id64": 12345,
                "x": -4.0, "y": 1.0, "z": 5.0,
            },
        ]
    },
}

CURRENT_SHIP_LOADOUT = {
    "event": "Loadout",
    "Ship": "python",
    "ShipName": "Whisper of Void",
    "ShipIdent": "MU-28P",
    "Modules": [
        {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5"},
    ],
    "FuelCapacity": {"Main": 32.0, "Reserve": 0.63},
    "UnladenMass": 500.0,
    "CargoCapacity": 64,
}

IMPORTED_SHIP_LOADOUT = {
    "event": "Loadout",
    "Ship": "diamondbackxl",
    "ShipName": "Far Hopper",
    "ShipIdent": "DBX-1",
    "Modules": [
        {
            "Slot": "FrameShiftDrive",
            "Item": "int_hyperdrive_size4_class5",
            "Engineering": {
                "Modifiers": [
                    {"Label": "FSDOptimalMass", "Value": 900.0},
                ],
            },
        },
    ],
    "FuelCapacity": {"Main": 16.0, "Reserve": 0.5},
    "UnladenMass": 210.0,
    "CargoCapacity": 24,
}

RICHES_SYSTEMS = [
    {
        "name": "Sol",
        "jumps": 0,
        "bodies": [
            {
                "name": "Sol A 1",
                "subtype": "Earth-like world",
                "is_terraformable": True,
                "distance_to_arrival": 523,
                "estimated_scan_value": 1200000,
                "estimated_mapping_value": 3200000,
            },
            {
                "name": "Sol A 2",
                "subtype": "Water world",
                "is_terraformable": False,
                "distance_to_arrival": 1100,
                "estimated_scan_value": 400000,
                "estimated_mapping_value": 900000,
            },
        ],
    },
    {
        "name": "Achenar",
        "jumps": 5,
        "bodies": [
            {
                "name": "Achenar 3",
                "subtype": "High metal content world",
                "is_terraformable": True,
                "distance_to_arrival": 300,
                "estimated_scan_value": 500000,
                "estimated_mapping_value": 1500000,
            },
        ],
    },
]

EXOBIOLOGY_SYSTEMS = [
    {
        "name": "Shinrarta Dezhra",
        "jumps": 0,
        "bodies": [
            {
                "name": "Shinrarta Dezhra A 1",
                "subtype": "Rocky body",
                "distance_to_arrival": 200,
                "landmarks": [
                    {"subtype": "bacterium", "count": 2, "value": 19000000},
                    {"subtype": "fungoida", "count": 1, "value": 7000000},
                ],
            }
        ],
    },
    {
        "name": "Colonia",
        "jumps": 3,
        "bodies": [
            {
                "name": "Colonia 2",
                "subtype": "High metal content world",
                "distance_to_arrival": 450,
                "landmarks": [
                    {"subtype": "frutexa", "count": 3, "value": 12000000},
                ],
            }
        ],
    },
]

AMMONIA_SYSTEMS = [
    {
        "name": "Sol",
        "jumps": 0,
        "bodies": [
            {
                "name": "Sol A 1",
                "subtype": "Ammonia world",
                "is_terraformable": False,
                "distance_to_arrival": 523,
                "estimated_scan_value": 1200000,
                "estimated_mapping_value": 3200000,
            },
        ],
    },
    {
        "name": "Achenar",
        "jumps": 5,
        "bodies": [
            {
                "name": "Achenar 3",
                "subtype": "Ammonia world",
                "is_terraformable": False,
                "distance_to_arrival": 300,
                "estimated_scan_value": 500000,
                "estimated_mapping_value": 1500000,
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


class _DummyAnimatedButton(DummyWidget):
    def __init__(self):
        super().__init__()
        self._values = {}
        self.after_calls = []
        self.cancelled_jobs = []

    def config(self, *args, **kwargs):
        super().config(*args, **kwargs)
        self._values.update(kwargs)

    configure = config

    def cget(self, key):
        return self._values.get(key, "")

    def after(self, delay, func):
        job = f"job-{len(self.after_calls) + 1}"
        self.after_calls.append((delay, func, job))
        return job

    def after_cancel(self, job):
        self.cancelled_jobs.append(job)


class _FakeDialogWindow:
    def __init__(self, _parent=None):
        self.parent = _parent
        self._exists = True
        self.protocols = {}

    def title(self, _text):
        return None

    def grid_columnconfigure(self, *_a, **_kw):
        return None

    def grid_rowconfigure(self, *_a, **_kw):
        return None

    def withdraw(self):
        pass

    def deiconify(self):
        pass

    def geometry(self, _v):
        pass

    def resizable(self, *_a):
        pass

    def minsize(self, *_a):
        pass

    def maxsize(self, *_a):
        pass

    def protocol(self, name, callback):
        self.protocols[name] = callback

    def winfo_exists(self):
        return self._exists

    def destroy(self):
        self._exists = False

    def lift(self):
        pass

    def focus_force(self):
        pass

    def attributes(self, *_a, **_kw):
        return None

    def after_idle(self, callback):
        if callable(callback):
            callback()

    def update_idletasks(self):
        return None

    def transient(self, _h):
        return None

    def winfo_reqwidth(self):
        return 320

    def winfo_reqheight(self):
        return 280

    def winfo_width(self):
        return 320

    def winfo_height(self):
        return 280

    def winfo_rootx(self):
        return 0

    def winfo_rooty(self):
        return 0

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080


class _FakeSimpleWidget:
    def __init__(self, *_a, **kwargs):
        self.command = kwargs.get("command")

    def grid(self, *_a, **_kw):
        return None

    def grid_remove(self, *_a, **_kw):
        return None

    def pack(self, *_a, **_kw):
        return None

    def place(self, *_a, **_kw):
        return None


class _FakeFrameWidget(_FakeSimpleWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tk = MagicMock()

    def grid_columnconfigure(self, *_a, **_kw):
        return None

    def grid_rowconfigure(self, *_a, **_kw):
        return None


class _FakeTextWidget:
    instances = []

    def __init__(self, *_a, **_kw):
        self.bindings = {}
        self.content = ""
        _FakeTextWidget.instances.append(self)

    def grid(self, *_a, **_kw):
        return None

    def bind(self, sequence, callback, add=None):
        self.bindings[sequence] = (callback, add)

    def get(self, *_a, **_kw):
        return self.content

    def insert(self, *_a):
        if len(_a) > 1:
            self.content += _a[1]


class FakeMenu:
    def __init__(self, *_args, **_kwargs): pass
    def add_command(self, *_args, **_kwargs): pass
    def add_radiobutton(self, *_args, **_kwargs): pass
    def add_cascade(self, *_args, **_kwargs): pass
    def add_separator(self, *_args, **_kwargs): pass
    def add_checkbutton(self, *_args, **_kwargs): pass
    def tk_popup(self, *_args, **_kwargs): pass


class FakeTopLevel:
    created = []

    def __init__(self, _parent):
        self.tk = _root
        self.exists = True
        self.destroyed = False
        self.lifted = 0
        self.focused = 0
        FakeTopLevel.created.append(self)

    def title(self, *_args, **_kwargs): pass
    def resizable(self, *_args, **_kwargs): pass
    def minsize(self, *_args, **_kwargs): pass
    def protocol(self, *_args, **_kwargs): pass

    def config(self, *_args, **_kwargs): pass
    configure = config

    def grid_rowconfigure(self, *_args, **_kwargs): pass
    def grid_columnconfigure(self, *_args, **_kwargs): pass

    def destroy(self):
        self.destroyed = True
        self.exists = False

    def winfo_exists(self):
        return self.exists

    def lift(self):
        self.lifted += 1

    def focus_force(self):
        self.focused += 1

    def winfo_width(self): return 800
    def winfo_height(self): return 600
    def winfo_screenwidth(self): return 1920

    def after(self, *_args, **_kwargs): pass

    def after_idle(self, callback=None, *_args, **_kwargs):
        if callable(callback):
            callback()

    def after_cancel(self, *_args, **_kwargs): pass
    def bind(self, *_args, **_kwargs): pass
    def update_idletasks(self): pass
    def winfo_ismapped(self): return True
    def geometry(self, *_args, **_kwargs): pass

    def state(self, *_args, **_kwargs):
        return "normal"

    def deiconify(self): pass


class FakeSheet:
    last_instance = None

    def __init__(self, *_args, **kwargs):
        self.init_headers = kwargs.get("headers", [])
        self.init_data = kwargs.get("data", [])
        self.init_row_index = kwargs.get("row_index", [])
        FakeSheet.last_instance = self

    def grid(self, *_args, **_kwargs): pass
    def enable_bindings(self, *_args, **_kwargs): pass
    def extra_bindings(self, *_args, **_kwargs): pass
    def headers(self, *_args, **_kwargs): pass
    def row_index(self, *_args, **_kwargs): pass
    def display_columns(self, *_args, **_kwargs): pass
    def set_options(self, *_args, **_kwargs): pass
    def set_index_width(self, *_args, **_kwargs): pass
    def index_align(self, *_args, **_kwargs): pass
    def highlight_rows(self, *_args, **_kwargs): pass
    def highlight_cells(self, *_args, **_kwargs): pass
    def set_index_data(self, *_args, **_kwargs): pass
    def readonly_columns(self, *_args, **_kwargs): pass
    def column_width(self, *_args, **_kwargs): pass
    def get_column_widths(self): return []
    def popup_menu_add_command(self, *_args, **_kwargs): pass
    def bind(self, *_args, **_kwargs): pass
    def see(self, *_args, **_kwargs): pass
    def refresh(self, *_args, **_kwargs): pass
    def winfo_width(self): return 800
    def winfo_height(self): return 600
    def identify_region(self, *_args, **_kwargs): return ""
    def identify_row(self, *_args, **_kwargs): return None
    MT = MagicMock()

    class RI:
        @staticmethod
        def bind(*_args, **_kwargs): pass


# ---------------------------------------------------------------------------
# Exploration helpers
# ---------------------------------------------------------------------------


def _patch_viewer():
    """Context-manager stack that patches all tk widgets needed by the viewer."""
    _dummy = lambda *_args, **_kwargs: DummyWidget()
    return [
        patch("SpanshTools.core.tk.Toplevel", FakeTopLevel),
        patch("SpanshTools.core.tk.Frame", _dummy),
        patch("SpanshTools.core.tk.Button", _dummy),
        patch("SpanshTools.core.tk.Label", _dummy),
        patch("SpanshTools.core.tk.Menu", FakeMenu),
        patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel),
        patch("SpanshTools.route_viewer.tk.Frame", _dummy),
        patch("SpanshTools.route_viewer.tk.Label", _dummy),
        patch("SpanshTools.route_viewer.tk.Button", _dummy),
        patch("SpanshTools.route_viewer.tk.Entry", _dummy),
        patch("SpanshTools.route_viewer.tk.Menubutton", _dummy),
        patch("SpanshTools.route_viewer.tk.Menu", FakeMenu),
        patch("SpanshTools.route_viewer.TkSheet", FakeSheet),
    ]


def _prepare_exploration_form(router):
    """Wire up all widgets the exploration plotter reads from."""
    router._exp_error_txt = MagicMock()
    router._exp_calc_btn = MagicMock()
    router._exp_source_ac = DummyAC("Sol", "Source System")
    router._exp_dest_ac = DummyAC("Achenar", "Destination System")
    router._exp_range = DummyEntry("87", minimum=0, maximum=100)
    router._exp_radius = DummyEntry("25", minimum=1, maximum=1000)
    router._exp_max_results = DummyEntry("100", minimum=1, maximum=2000)
    router._exp_max_distance = DummyEntry("1000000", minimum=1, maximum=1000000)
    router._exp_min_value = DummyEntry("100000", minimum=0, maximum=1000000)
    router._exp_loop = MagicMock(get=MagicMock(return_value=True))
    router._exp_avoid_thargoids_var = MagicMock(get=MagicMock(return_value=True))
    router._exp_use_mapping_var = MagicMock(get=MagicMock(return_value=True))


def _open_viewer(router):
    """Open the CSV viewer with all tk widgets patched out."""
    FakeTopLevel.created = []
    FakeSheet.last_instance = None
    ctx = _patch_viewer()
    for c in ctx:
        c.start()
    try:
        router.show_csv_viewer()
    finally:
        for c in reversed(ctx):
            c.stop()
    return FakeSheet.last_instance


def _reload_router(source_router):
    """Save state from *source_router*, create a fresh router and reload."""
    source_router.save_all_route()
    router2 = create_router(SpanshTools)
    router2._tmpdir = source_router._tmpdir
    router2.plugin_dir = source_router._tmpdir
    router2.save_route_path = source_router.save_route_path
    router2.plotter_settings_path = source_router.plotter_settings_path
    router2.open_last_route()
    return router2


# ---------------------------------------------------------------------------
# 1. Exact plot success -- single comprehensive test
# ---------------------------------------------------------------------------


def test_exact_plot_success_comprehensive(router):
    """Merged: route populated, names, distances, jumps, refuel, source skip, data preserved."""
    with patch("SpanshTools.core.monitor.state", {"SystemName": "Sol"}):
        router._exact_plot_success(MOCK_ROUTE_DATA)

    # Route populated
    assert router.exact_plotter is True
    assert router.fleetcarrier is False
    assert len(router.route) == 3
    assert len(router.exact_route_data) == 3

    # System names
    assert router.route[0][0] == "Sol"
    assert router.route[1][0] == "Alpha Centauri"
    assert router.route[2][0] == "Barnard's Star"

    # Distances
    assert router.route[0][2] == "0"
    assert router.route[1][2] == "4.38"

    # Jumps counted (source is not a jump)
    assert router.jumps_left == 2

    # Source skip: at Sol, so offset moves to 1
    assert router.offset == 1
    assert router.next_stop == "Alpha Centauri"
    assert router.exact_route_data[0]["done"] is True

    # Refuel status: Alpha Centauri has must_refuel=True
    assert router.pleaserefuel is True

    # exact_route_data preserved
    assert router.exact_route_data[0]["must_refuel"] is True
    assert router.exact_route_data[1]["is_scoopable"] is True
    assert router.exact_route_data[2]["must_refuel"] is False


# ---------------------------------------------------------------------------
# 2. Clipboard -- linux external helper
# ---------------------------------------------------------------------------


def test_linux_clipboard_uses_external_helper_not_tk(monkeypatch, router):
    router.parent.clipboard_clear = MagicMock(side_effect=AssertionError("should not use tk"))
    router.parent.clipboard_append = MagicMock(side_effect=AssertionError("should not use tk"))

    commands = []

    class ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    class FakeProc:
        def __init__(self, command):
            self.command, self.returncode = command, 0

        def communicate(self, data, timeout=None):
            commands.append((self.command, data.decode("utf-8"), timeout))
            return (b"", b"")

    monkeypatch.setattr(spans_mod.sys, "platform", "linux")
    monkeypatch.setattr(spans_mod.threading, "Thread", ImmediateThread)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        spans_mod.subprocess, "Popen",
        lambda command, stdin=None, stdout=None, stderr=None: FakeProc(command),
    )

    assert router._copy_to_clipboard("HIP 100000") is True
    assert commands[0][0] == ["wl-copy"]
    assert commands[0][1] == "HIP 100000"


# ---------------------------------------------------------------------------
# 3. Update button -- parametrized available vs staged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("staged,expected_text,expected_tooltip_substr", [
    (False, "Update", "Version v1.0.2 is available"),
    (True, "Update Ready", "staged and will install automatically"),
])
def test_update_button_reflects_staged_state(router, staged, expected_text, expected_tooltip_substr):
    router.spansh_updater = MagicMock(version="1.0.2")
    router.spansh_updater.is_staged.return_value = staged

    assert router._update_button_text() == expected_text
    assert expected_tooltip_substr in router._update_button_tooltip_text()


# ---------------------------------------------------------------------------
# 4. Animation -- start + stop cycle
# ---------------------------------------------------------------------------


def test_set_plot_running_state_start_and_stop_cycle(router):
    router._mark_plot_started = MagicMock()
    router._mark_plot_stopped = MagicMock()
    router._set_main_controls_enabled = MagicMock()
    router._set_plotter_windows_enabled = MagicMock()
    button = _DummyAnimatedButton()
    button._values["fg"] = "black"

    # Start
    router._set_plot_running_state(active=True, button=button)
    assert button.cget("state") == plotters_mod.tk.DISABLED
    assert button.cget("text") == "Computing"
    assert getattr(button, "_busy_plot_button", False) is True
    assert getattr(router, "_plotter_button_animation_job") == "job-1"

    # Tick once
    _delay, callback, _ = button.after_calls[-1]
    assert _delay == 675
    callback()
    assert button.cget("text") == "Computing."

    # Stop
    router._set_plot_running_state(active=False, button=button)
    assert button.cget("state") == plotters_mod.tk.NORMAL
    assert button.cget("text") == "Calculate"
    assert getattr(button, "_busy_plot_button", False) is False
    assert getattr(router, "_plotter_button_animation_job", None) is None
    assert button.cancelled_jobs == ["job-2"]


# ---------------------------------------------------------------------------
# 5. Ship import/export (4 tests)
# ---------------------------------------------------------------------------


def test_ship_import_accepts_wrapped_json(router):
    payload = [{"header": {"appName": "EDMarketConnector", "appVersion": "6.1.2"}, "data": IMPORTED_SHIP_LOADOUT}]
    loadout = router._ship_loadout_from_import_payload(payload)
    assert loadout["ShipName"] == "Far Hopper"
    assert loadout["Modules"][0]["Slot"] == "FrameShiftDrive"


def test_ship_import_rejects_missing_ship(router):
    payload = [{"header": {"appName": "EDMarketConnector"}, "data": {"Modules": [{"Slot": "FrameShiftDrive"}]}}]
    assert router._ship_loadout_from_import_payload(payload) is None


def test_ship_export_wraps_current_loadout(router):
    payload = router._ship_export_payload(CURRENT_SHIP_LOADOUT)
    assert payload[0]["header"]["appName"] == "EDMC-SpanshTools"
    assert payload[0]["header"]["appVersion"] == router.plugin_version
    assert payload[0]["data"]["ShipName"] == "Whisper of Void"


def test_ship_import_then_reset_cycle(router):
    router.current_ship_loadout = CURRENT_SHIP_LOADOUT
    router.process_loadout(CURRENT_SHIP_LOADOUT)
    router.exact_fsd_status_lbl = DummyWidget()

    router._apply_exact_ship_import(IMPORTED_SHIP_LOADOUT)
    assert router._active_exact_ship_loadout()["ShipName"] == "Far Hopper"
    assert router._active_exact_ship_fsd_data()["optimal_mass"] == 900.0

    router._reset_exact_ship_to_current()
    assert router._active_exact_ship_loadout()["ShipName"] == "Whisper of Void"
    assert router._active_exact_ship_fsd_data()["optimal_mass"] == 1050.0


# ---------------------------------------------------------------------------
# 6. Ship dialog -- singleton only
# ---------------------------------------------------------------------------


def test_exact_ship_import_dialog_is_singleton(router, monkeypatch):
    router._plotter_window_kind = "Exact Plotter"
    router.plotter_win = DummyWidget()
    created = []

    def fake_toplevel(parent):
        w = _FakeDialogWindow(parent)
        created.append(w)
        return w

    monkeypatch.setattr(plotters_mod.tk, "Toplevel", fake_toplevel)
    monkeypatch.setattr(plotters_mod.tk, "Label", _FakeSimpleWidget)
    monkeypatch.setattr(plotters_mod.tk, "Text", _FakeTextWidget)
    monkeypatch.setattr(plotters_mod.tk, "Button", _FakeSimpleWidget)
    monkeypatch.setattr(plotters_mod.tk, "Entry", _FakeSimpleWidget)
    monkeypatch.setattr(plotters_mod.tk, "Frame", _FakeFrameWidget)
    monkeypatch.setattr(plotters_mod.tk, "Menu", FakeMenu)
    monkeypatch.setattr(router, "_configure_child_window", lambda _win: None)
    monkeypatch.setattr(router, "_position_child_window_next_to_host", lambda _w, _h: None)
    monkeypatch.setattr(router, "_host_toplevel", lambda: None)
    monkeypatch.setattr(router, "_ship_list_selected_entry", lambda: None)
    monkeypatch.setattr(router, "_finalize_exact_ship_dialog", lambda _w: None)
    raise_calls = []
    monkeypatch.setattr(router, "_raise_child_window", lambda w: raise_calls.append(w))

    router._show_exact_ship_import_dialog()
    router._show_exact_ship_import_dialog()

    assert len(created) == 1
    assert raise_calls[-1] is created[0]
    assert router._exact_ship_import_win is created[0]


# ---------------------------------------------------------------------------
# 7. Persistence -- single comprehensive test
# ---------------------------------------------------------------------------


def test_persistence_save_load_offset(router):
    """Merged: save, load, offset restore."""
    router._exact_plot_success(MOCK_ROUTE_DATA)
    router.offset = 2
    router.save_all_route()

    path = router._route_state_path()
    assert os.path.exists(path)
    with open(path, "r") as f:
        payload = json.load(f)
    assert payload["planner"] == "Exact Plotter"
    assert payload["route_type"] == "exact"
    assert len(payload["route"]) == 3
    assert payload["exact_route_data"][0]["fuel_in_tank"] == 32.0

    # Load into fresh router
    router2 = create_router(SpanshTools)
    router2._tmpdir = router._tmpdir
    router2.plugin_dir = router._tmpdir
    router2.save_route_path = router.save_route_path
    router2.open_last_route()

    assert router2.exact_plotter is True
    assert router2.current_plotter_name == "Exact Plotter"
    assert len(router2.route) == 3
    assert router2.offset == 2
    assert router2.route[2][0] == "Barnard's Star"
    assert router2.exact_route_data[0]["must_refuel"] is True


# ---------------------------------------------------------------------------
# 8. Clear
# ---------------------------------------------------------------------------


def test_clear_resets_exact_plotter_state(router):
    router._exact_plot_success(MOCK_ROUTE_DATA)
    assert router.exact_plotter is True

    router.clear_route(show_dialog=False)

    assert router.exact_plotter is False
    assert router.exact_route_data == []
    assert router.route == []
    assert router.overlay_var.get() is False


# ---------------------------------------------------------------------------
# 9. Update route -- advance sets refuel + advance past clears it
# ---------------------------------------------------------------------------


def test_advance_sets_and_clears_refuel(router):
    router._exact_plot_success(MOCK_ROUTE_DATA)
    router.offset = 0

    router.update_route(direction=1)
    assert router.next_stop == "Alpha Centauri"
    assert router.pleaserefuel is True

    router.update_route(direction=1)
    assert router.next_stop == "Barnard's Star"
    assert router.pleaserefuel is False


# ---------------------------------------------------------------------------
# 10. API params -- clamp test
# ---------------------------------------------------------------------------


def test_plot_exact_route_clamps_spinbox_values(monkeypatch, router):
    class _SpinboxStub:
        def __init__(self, value, lo, hi):
            self.value = str(value)
            self._opts = {"from": str(lo), "to": str(hi)}

        def get(self):
            return self.value

        def delete(self, *_a, **_kw):
            self.value = ""

        def insert(self, _i, v):
            self.value = str(v)

        def cget(self, key):
            return self._opts[key]

    captured = {}

    class _Capture:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            captured["args"] = args

        def start(self):
            pass

    router.ship_fsd_data = {
        "optimal_mass": 1800.0, "max_fuel_per_jump": 8.0, "fuel_power": 2.6,
        "fuel_multiplier": 0.012, "tank_size": 32.0, "reserve_size": 0.63,
        "unladen_mass": 800.0, "range_boost": 10.5, "supercharge_multiplier": 4,
    }
    router.exact_source_ac = DummyAC("Sol", "Source System")
    router.exact_dest_ac = DummyAC("Colonia", "Destination System")
    router.exact_cargo_entry = _SpinboxStub("12000", 0, 9999)
    router.exact_reserve_entry = _SpinboxStub("99.5", 0, 32)
    router.exact_is_supercharged = MagicMock(get=MagicMock(return_value=False))
    router.exact_use_supercharge = MagicMock(get=MagicMock(return_value=True))
    router.exact_use_injections = MagicMock(get=MagicMock(return_value=False))
    router.exact_exclude_secondary = MagicMock(get=MagicMock(return_value=False))
    router.exact_refuel_every_scoopable = MagicMock(get=MagicMock(return_value=True))
    router.exact_algorithm = MagicMock(get=MagicMock(return_value="trunkle"))
    router.exact_calculate_btn = MagicMock()
    router.exact_error_txt = MagicMock()
    router._set_plot_running_state = MagicMock()
    router._next_plot_token = MagicMock(return_value=7)
    router._detect_fsd_from_monitor = MagicMock()
    router._set_exact_error = MagicMock()

    monkeypatch.setattr(plotters_mod.threading, "Thread", _Capture)
    router.plot_exact_route()

    params = captured["args"][0]
    assert params["cargo"] == 9999
    assert params["reserve_size"] == 32


# ---------------------------------------------------------------------------
# 11. JSON import (5 tests)
# ---------------------------------------------------------------------------


def test_json_import_neutron(router):
    payload = {
        "status": "ok", "state": "completed", "job": "abc",
        "parameters": {"from": "Sol", "to": "HIP 100000", "range": 87, "efficiency": 0.6, "supercharge_multiplier": 4},
        "result": {"system_jumps": [
            {"system": "Sol", "jumps": 0, "distance_jumped": 0, "distance_left": 731.32, "neutron_star": False},
            {"system": "HIP 100000", "jumps": 2, "distance_jumped": 344.9, "distance_left": 0, "neutron_star": True},
        ]},
    }
    path = router.save_route_path.replace(".csv", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    router.plot_json(path)

    assert router.current_plotter_name == "Neutron Plotter"
    assert router.route[1][0] == "HIP 100000"
    assert router.route[1][4] == "Yes"


def test_json_import_exact(router):
    payload = {
        "status": "ok", "state": "completed", "job": "abc",
        "parameters": {"source_system": "Sol", "destination_system": "Alpha Centauri", "algorithm": "optimistic"},
        "result": {"jumps": [
            {"name": "Sol", "distance": 0, "distance_to_destination": 100.5, "fuel_in_tank": 32.0, "fuel_used": 0, "must_refuel": False, "has_neutron": False, "is_scoopable": False},
            {"name": "Alpha Centauri", "distance": 4.38, "distance_to_destination": 96.12, "fuel_in_tank": 31.9, "fuel_used": 0.1, "must_refuel": True, "has_neutron": False, "is_scoopable": True},
        ]},
    }
    path = router.save_route_path.replace(".csv", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    router.plot_json(path)

    assert router.exact_plotter is True
    assert router.route[1][0] == "Alpha Centauri"
    assert router.exact_route_data[1]["must_refuel"] is True


def test_json_import_fleet(router):
    payload = {
        "status": "ok", "state": "completed", "job": "abc",
        "parameters": {
            "source_system": "Sol", "destination_systems": ["Carang Hut"],
            "refuel_destinations": [], "capacity": 50000, "capacity_used": 0,
            "current_fuel": 1000, "tritium_amount": 0, "calculate_starting_fuel": False,
        },
        "result": {
            "source": "Sol", "destinations": ["Carang Hut"],
            "jumps": [
                {"name": "Sol", "distance": 0, "distance_to_destination": 22.94, "fuel_in_tank": 1000, "fuel_used": 0, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0, "is_desired_destination": 1},
                {"name": "Carang Hut", "distance": 22.94, "distance_to_destination": 0, "fuel_in_tank": 778, "fuel_used": 10, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0, "is_desired_destination": 1},
            ],
        },
    }
    path = router.save_route_path.replace(".csv", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    router.plot_json(path)

    assert router.fleetcarrier is True
    assert router.fleet_carrier_data[0]["is_waypoint"] is True


def test_json_import_riches_done_progress(router):
    payload = {
        "status": "ok", "state": "completed",
        "parameters": {"planner": "Road to Riches"},
        "result": [
            {"name": "Sol", "jumps": 0, "bodies": [{"name": "Sol A 1", "subtype": "HMC", "is_terraformable": True, "distance_to_arrival": 100, "estimated_scan_value": 1000, "estimated_mapping_value": 2000, "done": True}]},
            {"name": "Achenar", "jumps": 2, "bodies": [{"name": "Achenar 1", "subtype": "HMC", "is_terraformable": False, "distance_to_arrival": 50, "estimated_scan_value": 500, "estimated_mapping_value": 900, "done": False}]},
        ],
    }
    path = router.save_route_path.replace(".csv", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    router.plot_json(path)

    assert router.exploration_mode == "Road to Riches"
    assert router.offset == 1
    assert router.next_stop == "Achenar"


def test_json_import_exo_done_progress(router):
    payload = {
        "status": "ok", "state": "completed",
        "parameters": {"planner": "Exomastery"},
        "result": [
            {"name": "Sol", "jumps": 0, "bodies": [{"name": "Sol A 1", "subtype": "Rocky body", "distance_to_arrival": 100, "landmarks": [{"subtype": "Bacterium", "count": 1, "value": 1000, "done": True}]}]},
            {"name": "Achenar", "jumps": 2, "bodies": [{"name": "Achenar 1", "subtype": "Rocky body", "distance_to_arrival": 50, "landmarks": [{"subtype": "Osseus", "count": 1, "value": 900, "done": False}]}]},
        ],
    }
    path = router.save_route_path.replace(".csv", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    router.plot_json(path)

    assert router.exploration_mode == "Exomastery"
    assert router.offset == 1
    assert router.next_stop == "Achenar"


# ---------------------------------------------------------------------------
# 12. JSON export (3 tests)
# ---------------------------------------------------------------------------


def test_json_export_exploration_defaults(router):
    router.exploration_plotter = True
    router.route_type = "exploration"
    router.exploration_mode = "Rocky/HMC Route"
    router.current_plotter_name = "Rocky/HMC Route"
    router.route = [["Sol", "0"], ["HIP 100000", "2"]]
    router.exploration_route_data = [
        {"name": "Sol", "jumps": 0, "bodies": [{"name": "Sol A 1", "distance_to_arrival": 100, "done": False}]},
        {"name": "HIP 100000", "jumps": 2, "bodies": [{"name": "HIP 100000 A 1", "distance_to_arrival": 50, "done": False}]},
    ]
    router._plotter_settings = {}

    payload = router._spansh_json_export_payload()
    assert payload["parameters"]["planner"] == "Rocky/HMC Route"
    assert payload["parameters"]["body_types"] == ["Rocky body", "High metal content world"]


def test_json_export_exact_defaults(router):
    router.exact_plotter = True
    router.route_type = "exact"
    router.current_plotter_name = "Exact Plotter"
    router.route = [["Sol", "0"], ["Colonia", "1"]]
    router.exact_route_data = [
        {"name": "Sol", "distance": 0, "distance_to_destination": 100, "fuel_in_tank": 32, "fuel_used": 0, "must_refuel": True, "has_neutron": False},
        {"name": "Colonia", "distance": 100, "distance_to_destination": 0, "fuel_in_tank": 20, "fuel_used": 12, "must_refuel": False, "has_neutron": False},
    ]
    router._plotter_settings = {}

    payload = router._spansh_json_export_payload()
    assert payload["parameters"]["source"] == "Sol"
    assert payload["parameters"]["destination"] == "Colonia"
    assert payload["parameters"]["algorithm"] == "optimistic"


def test_json_export_fleet_carrier_profile(router):
    router.fleetcarrier = True
    router.route_type = "fleet_carrier"
    router.fleet_carrier_data = [{"name": "Sol"}]
    router._plotter_settings = {
        "planners": {
            "Fleet Carrier Router": {
                "source": "Sol", "destinations": ["Carang Hut"],
                "refuel_destinations": [], "carrier_type": "squadron",
                "used_capacity": 1234, "determine_required_fuel": True,
                "tritium_fuel": 1000, "tritium_market": 0,
            },
        },
    }

    payload = router._spansh_json_export_payload()
    assert payload["parameters"]["carrier_type"] == "squadron"
    assert payload["parameters"]["capacity"] == 60000
    assert payload["parameters"]["mass"] == 15000


# ---------------------------------------------------------------------------
# 13. Route state (2 tests)
# ---------------------------------------------------------------------------


def test_signature_detects_done_changes(router):
    router.route = [["A"], ["B"], ["C"], ["D"], ["E"]]
    router.route_done = [True, False, True, False, True]
    sig1 = router._route_rows_signature()

    router.route_done = [True, True, False, False, True]
    router._invalidate_route_rows()
    sig2 = router._route_rows_signature()

    assert sig1 != sig2


def test_cache_refresh_after_invalidation(router):
    router.route_type = "simple"
    router.route = [["Sol", "1", "10", "20"]]
    router.route_done = [False]

    first = router._route_row_state_at(0)
    router.route[0][0] = "Achenar"
    router.route[0][2] = "35"
    router._invalidate_route_rows()
    second = router._route_row_state_at(0)

    assert first["name"] == "Sol"
    assert second["name"] == "Achenar"
    assert second["distance_to_arrival"] == 35.0


# ---------------------------------------------------------------------------
# 15. Journal events (2 tests)
# ---------------------------------------------------------------------------


def test_pre_gui_replay(router):
    router.frame = None
    router.handle_journal_entry(
        "Sol",
        {"event": "Location", "StarSystem": "Sol", "StarPos": [1, 2, 3]},
        {"SystemName": "Sol", "StarPos": [1, 2, 3]},
    )
    assert router._pending_journal_event is not None

    router.frame = DummyFrame()
    router._replay_buffered_startup_events()

    coords, system = router._get_current_location()
    assert coords == [1, 2, 3]
    assert system == "Sol"
    assert router._pending_journal_event is None


def test_carrier_jump_clears_coords(router):
    router._set_current_location(coords=[10, 20, 30], system="Old System")

    router._handle_journal_entry_ui(
        "", {"event": "CarrierJump", "StarSystem": "New System"}, {},
    )

    coords, system = router._get_current_location()
    assert coords is None
    assert system == "New System"


# ---------------------------------------------------------------------------
# 16. Validation (2 tests)
# ---------------------------------------------------------------------------


def test_destination_lookup_failure(router):
    router._check_system_in_spansh = MagicMock(return_value=None)

    ok, message = router._validate_destination_system("Achenar")
    assert ok is False
    assert "Failed to look up destination system" in message


def test_source_lookup_failure(router):
    router._resolve_system_record = MagicMock(return_value=None)
    router._check_system_in_spansh = MagicMock(return_value=None)

    ok, record, nearest, message = router._resolve_valid_source_record("Sol")
    assert ok is False
    assert record is None
    assert "Failed to look up source system" in message


# ---------------------------------------------------------------------------
# 17. Fleet empty payload
# ---------------------------------------------------------------------------


def test_fleet_empty_payload_preserves_route(router):
    router.route = [["Existing", "1", "10", "20"]]
    router.plotter_win = DummyWidget()
    router._fc_calc_btn = MagicMock()
    router._fc_error_txt = MagicMock()
    router.clear_route = MagicMock()
    router._close_plotter_window = MagicMock()
    router.show_error = MagicMock()

    router._fleet_carrier_route_success(
        {},
        {
            "source": "Sol", "destinations": ["Achenar"],
            "refuel_destinations": [], "carrier_type": "fleet",
            "used_capacity": 1234, "determine_required_fuel": True,
            "tritium_fuel": 0, "tritium_market": 0,
        },
    )

    router.clear_route.assert_not_called()
    assert router.route == [["Existing", "1", "10", "20"]]
    router._fc_error_txt.set.assert_called_once()


# ---------------------------------------------------------------------------
# _parse_number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("", None),
    ("  ", None),
    (42, 42.0),
    (3.14, 3.14),
    ("1,200,000", 1200000.0),
    ("523Ls", 523.0),
    ("100.5 LY", 100.5),
    ("3,200,000Cr", 3200000.0),
    ("invalid", None),
], ids=["none", "empty", "whitespace", "int", "float", "commas", "ls-suffix", "ly-suffix", "cr-suffix", "invalid"])
def test_parse_number(router, value, expected):
    assert router._parse_number(value) == expected


# ---------------------------------------------------------------------------
# _infer_fleet_carrier_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kwargs,expected", [
    ({"explicit_type": "squadron"}, "squadron"),
    ({"explicit_type": "Squadron Carrier"}, "squadron"),
    ({"explicit_type": "fleet"}, "fleet"),
    ({"explicit_type": "", "capacity": 60000}, "squadron"),
    ({"explicit_type": "", "capacity": 25000}, "fleet"),
    ({"explicit_type": "", "mass": 15000}, "squadron"),
    ({"explicit_type": "", "capacity": None, "mass": None}, "fleet"),
], ids=["explicit-squadron", "explicit-squadron-carrier", "explicit-fleet", "capacity-60k", "capacity-25k", "mass-15k", "fallback-fleet"])
def test_infer_fleet_carrier_type(router, kwargs, expected):
    assert router._infer_fleet_carrier_type(**kwargs) == expected


# ---------------------------------------------------------------------------
# Exploration payload building
# ---------------------------------------------------------------------------

class TestExplorationPayloads:
    def test_riches_payload_matches_spansh_fields(self, router):
        _prepare_exploration_form(router)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_exploration_route("Road to Riches")

        api_url, params, planner = thread_cls.call_args.kwargs["args"][:3]
        assert api_url == "https://spansh.co.uk/api/riches/route"
        assert planner == "Road to Riches"
        assert params["from"] == "Sol"
        assert params["to"] == "Achenar"
        assert params["range"] == 87.0
        assert params["radius"] == 25
        assert params["max_results"] == 100
        assert params["max_distance"] == 1000000
        assert params["min_value"] == 100000
        assert params["use_mapping_value"] == 1
        assert params["loop"] == 1

    def test_exomastery_payload_uses_exobiology_api(self, router):
        _prepare_exploration_form(router)
        router._exp_min_value = DummyEntry("10000000", minimum=0, maximum=10000000)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_exploration_route("Exomastery")

        api_url, params, planner = thread_cls.call_args.kwargs["args"][:3]
        assert api_url == "https://spansh.co.uk/api/exobiology/route"
        assert planner == "Exomastery"
        assert params["min_value"] == 10000000
        assert params["avoid_thargoids"] == 1
        assert "use_mapping_value" not in params

    def test_specialized_body_type_route_uses_body_types(self, router):
        _prepare_exploration_form(router)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_exploration_route("Rocky/HMC Route")

        _, params, planner = thread_cls.call_args.kwargs["args"][:3]
        assert planner == "Rocky/HMC Route"
        assert params["body_types"] == ["Rocky body", "High metal content world"]
        assert params["min_value"] == 1
        assert "use_mapping_value" not in params

    def test_exploration_values_are_clamped_to_spinbox_limits(self, router):
        _prepare_exploration_form(router)
        router._exp_range = DummyEntry("500", minimum=0, maximum=100)
        router._exp_radius = DummyEntry("5000", minimum=1, maximum=1000)
        router._exp_max_results = DummyEntry("9999", minimum=1, maximum=2000)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_exploration_route("Road to Riches")

        _, params, _ = thread_cls.call_args.kwargs["args"][:3]
        assert params["range"] == 100.0
        assert params["radius"] == 1000
        assert params["max_results"] == 2000


# ---------------------------------------------------------------------------
# Exploration row formatting
# ---------------------------------------------------------------------------

class TestExplorationViewRows:
    def test_riches_rows_grouped_with_totals(self, router):
        router._apply_exploration_route_data("Road to Riches", RICHES_SYSTEMS)

        rows = [row["values"] for row in router._exploration_view_rows()]

        assert rows[0] == [
            "\u25a1", "Sol", "Sol A 1", "Earth-like world", "\u2713",
            "523", "1,200,000", "3,200,000", 0,
        ]
        assert rows[1][1] == ""
        assert rows[-1][0] == "Total"
        assert rows[-1][6] == "2,100,000"
        assert rows[-1][7] == "5,600,000"

    def test_exobiology_rows_include_landmarks(self, router):
        router._apply_exploration_route_data("Exomastery", EXOBIOLOGY_SYSTEMS)

        rows = [row["values"] for row in router._exploration_view_rows()]

        assert rows[0][5] == "bacterium"
        assert rows[0][6] == 2
        assert rows[1][5] == "fungoida"
        assert rows[-1][0] == "Total"
        assert rows[-1][7] == "38,000,000"


# ---------------------------------------------------------------------------
# Exploration persistence
# ---------------------------------------------------------------------------

class TestExplorationPersistence:
    def test_riches_route_save_load_round_trip(self, router):
        router._apply_exploration_route_data("Road to Riches", RICHES_SYSTEMS)

        router2 = _reload_router(router)

        assert router2.exploration_plotter is True
        assert router2.exploration_mode == "Road to Riches"
        assert [row[0] for row in router2.route] == ["Sol", "Achenar"]
        assert router2.jumps_left == 5
        assert len(router2.exploration_route_data) == 2
        assert len(router2.exploration_route_data[0]["bodies"]) == 2

    def test_exobiology_route_preserves_landmarks_after_reload(self, router):
        router._apply_exploration_route_data("Exomastery", EXOBIOLOGY_SYSTEMS)

        router2 = _reload_router(router)

        assert router2.exploration_plotter is True
        assert router2.exploration_mode == "Exomastery"
        first_body = router2.exploration_route_data[0]["bodies"][0]
        assert len(first_body["landmarks"]) == 2
        assert first_body["landmarks"][0]["subtype"] == "bacterium"
        assert first_body["landmarks"][1]["subtype"] == "fungoida"

    def test_done_progress_restores_offset_after_reload(self, router):
        router._apply_exploration_route_data("Earth-like World Route", AMMONIA_SYSTEMS)
        router._store_plotter_settings("Earth-like World Route", {})
        router.offset = 1
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.plotter_settings_path = router.plotter_settings_path
        router2.open_last_route()

        assert router2.exploration_plotter is True
        assert router2.exploration_mode == "Earth-like World Route"
        assert router2.current_plotter_name == "Earth-like World Route"
        assert router2.offset == 1
        assert [row[0] for row in router2.route] == ["Sol", "Achenar"]

    def test_import_exploration_json_sets_correct_mode(self, router):
        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {
                "source": "Sol",
                "destination": "HIP 100000",
                "range": 87,
                "radius": 25,
                "max_results": 100,
                "max_distance": 50000,
                "body_types": ["Ammonia world"],
            },
            "result": AMMONIA_SYSTEMS,
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.exploration_plotter is True
        assert router.exploration_mode == "Ammonia World Route"
        assert router.route[0][0] == "Sol"
        assert router.route[1][0] == "Achenar"


# ---------------------------------------------------------------------------
# Fleet carrier plotter
# ---------------------------------------------------------------------------

class TestFleetCarrierPlotter:
    def test_fleet_carrier_payload_builds_thread_params(self, router):
        router._fc_source_ac = DummyAC("Sol", "Source System")
        router._fc_dest_ac = DummyAC("Achenar", "Destination System")
        router._fc_error_txt = MagicMock()
        router._fc_calc_btn = MagicMock()
        router._fc_destinations = ["Achenar", "Colonia"]
        router._fc_refuel_destinations = {"Colonia"}
        router._fc_used_capacity = DummyEntry("999999", minimum=0, maximum=60000)
        router._fc_determine_required_fuel = MagicMock(get=MagicMock(return_value=False))
        router._fc_tritium_tank = DummyEntry("800", minimum=0, maximum=1000)
        router._fc_tritium_market = DummyEntry("50000", minimum=0, maximum=60000)
        router._fc_carrier_type = MagicMock(get=MagicMock(return_value="squadron"))
        router._set_fleet_error = MagicMock()
        router._set_plot_running_state = MagicMock()
        router._next_plot_token = MagicMock(return_value=1)

        with patch("SpanshTools.plotters.threading.Thread") as thread_cls:
            router._plot_fleet_carrier_route()

        params = thread_cls.call_args.kwargs["args"][0]
        assert params["source"] == "Sol"
        assert params["destinations"] == ["Achenar", "Colonia"]
        assert params["refuel_destinations"] == ["Colonia"]
        assert params["carrier_type"] == "squadron"
        assert params["used_capacity"] == 60000
        assert params["determine_required_fuel"] is False
        assert params["tritium_fuel"] == 800
        assert params["tritium_market"] == 50000

    def test_fleet_waypoint_flags_mark_source_and_destinations(self, router):
        jumps = [
            {"name": "Sol"},
            {"name": "HIP 1234"},
            {"name": "Achenar"},
            {"name": "Colonia"},
        ]

        router._apply_fleet_waypoint_flags(
            jumps, source="Sol", destinations=["Achenar", "Colonia"],
        )

        assert jumps[0]["is_waypoint"] is True
        assert jumps[1]["is_waypoint"] is False
        assert jumps[2]["is_waypoint"] is True
        assert jumps[3]["is_waypoint"] is True


# ---------------------------------------------------------------------------
# Route viewer
# ---------------------------------------------------------------------------

class TestRouteViewer:
    def test_riches_viewer_headers_and_first_row(self, router):
        router._apply_exploration_route_data("Road to Riches", RICHES_SYSTEMS)

        sheet = _open_viewer(router)

        assert tuple(sheet.init_headers) == (
            "Done", "System Name", "Name", "Subtype", "Terra",
            "Distance (Ls)", "Scan Value", "Mapping Value", "Jumps",
        )
        assert sheet.init_data[0][1] == "Sol"
        assert sheet.init_data[0][3] == "Earth-like world"

    def test_exo_viewer_headers_and_first_row(self, router):
        router._apply_exploration_route_data("Exomastery", EXOBIOLOGY_SYSTEMS)

        sheet = _open_viewer(router)

        assert tuple(sheet.init_headers) == (
            "Done", "System Name", "Name", "Subtype", "Distance (Ls)",
            "Landmark Subtype", "Count", "Landmark Value", "Jumps",
        )
        assert sheet.init_data[0][1] == "Shinrarta Dezhra"
        assert sheet.init_data[0][5] == "bacterium"

    def test_viewer_singleton_reuses_window(self, router):
        """Opening the viewer twice must not create a second window."""
        router.route = [["Sol", "1"]]

        FakeTopLevel.created = []
        FakeSheet.last_instance = None
        ctx = _patch_viewer()
        for c in ctx:
            c.start()
        try:
            router.show_csv_viewer()
            first = FakeTopLevel.created[0]
            router.show_csv_viewer()

            assert len(FakeTopLevel.created) == 1
            assert first.focused >= 1
        finally:
            for c in reversed(ctx):
                c.stop()


