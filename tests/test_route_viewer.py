"""Tests for the route viewer window."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import SpanshTools.core as spans_mod


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeTopLevel:
    created = []

    def __init__(self, _parent):
        self.exists = True
        self._geometry = "800x600+10+10"
        FakeTopLevel.created.append(self)

    def title(self, *a, **kw): pass
    def resizable(self, *a, **kw): pass
    def minsize(self, *a, **kw): pass
    def protocol(self, *a, **kw): pass
    def config(self, *a, **kw): pass
    configure = config
    def grid_rowconfigure(self, *a, **kw): pass
    def grid_columnconfigure(self, *a, **kw): pass
    def destroy(self): self.exists = False
    def winfo_exists(self): return self.exists
    def state(self): return "normal"
    def deiconify(self): pass
    def update(self): pass
    def winfo_rootx(self): return 10
    def winfo_rooty(self): return 10
    def lift(self): pass
    def focus_force(self): pass
    def winfo_width(self): return 800
    def winfo_height(self): return 600
    def winfo_screenwidth(self): return 1920
    def winfo_x(self): return 10
    def winfo_y(self): return 10
    def winfo_children(self): return []
    def after(self, _d, func, *args): return func(*args)
    def after_cancel(self, *a, **kw): pass
    def after_idle(self, func): return func()
    def bind(self, *a, **kw): pass
    def update_idletasks(self): pass
    def geometry(self, value=None):
        if value is None: return self._geometry
        self._geometry = value


class FakeMenu:
    def __init__(self, *a, **kw):
        self.entry_states = {}
    def add_command(self, *a, **kw): pass
    def add_radiobutton(self, *a, **kw): pass
    def add_cascade(self, *a, **kw): pass
    def add_separator(self, *a, **kw): pass
    def add_checkbutton(self, *a, **kw): pass
    def entryconfigure(self, label, **kw):
        self.entry_states[label] = kw


class FakeBinder:
    def __init__(self):
        self.callbacks = {}
    def bind(self, event, callback, add=None):
        self.callbacks[event] = callback


class FakeSheet:
    last_instance = None
    fail_popup = False

    def __init__(self, *a, **kw):
        self.init_headers = kw.get("headers", [])
        self.init_data = kw.get("data", [])
        self.init_row_index = kw.get("row_index", [])
        self.set_sheet_data_calls = []
        self.row_index_calls = []
        self.popup_commands = {}
        self.current_selected = None
        self.current_yview = (0.0, 1.0)
        self.current_xview = (0.0, 1.0)
        self.set_yview_calls = []
        self.set_xview_calls = []
        self.see_calls = []
        self.region = ""
        self.row = None
        self.MT = FakeBinder()
        self.RI = FakeBinder()
        FakeSheet.last_instance = self

    def grid(self, *a, **kw): pass
    def enable_bindings(self, *a, **kw): pass
    def headers(self, *a, **kw): pass
    def row_index(self, values, **kw): self.row_index_calls.append(values)
    def display_columns(self, *a, **kw): pass
    def set_options(self, *a, **kw): pass
    def set_index_width(self, *a, **kw): pass
    def index_align(self, *a, **kw): pass
    def highlight_rows(self, *a, **kw): pass
    def highlight_cells(self, *a, **kw): pass
    def set_index_data(self, *a, **kw): pass
    def readonly_columns(self, *a, **kw): pass
    def column_width(self, *a, **kw): pass
    def popup_menu_add_command(self, label, command, **kw):
        if self.fail_popup: raise RuntimeError("popup failed")
        self.popup_commands[label] = command
    def see(self, *a, **kw): self.see_calls.append((a, kw))
    def refresh(self, *a, **kw): pass
    def winfo_width(self): return 800
    def identify_region(self, _e): return self.region
    def identify_row(self, _e): return self.row
    def get_currently_selected(self): return self.current_selected
    def set_currently_selected(self, **kw): self.current_selected = SimpleNamespace(**kw)
    def get_yview(self): return self.current_yview
    def set_yview(self, v):
        self.current_yview = (v, min(v + 0.5, 1.0))
        self.set_yview_calls.append(v)
    def get_xview(self): return self.current_xview
    def set_xview(self, v):
        self.current_xview = (v, min(v + 0.5, 1.0))
        self.set_xview_calls.append(v)
    def get_column_data(self, *a, **kw): return []
    def set_sheet_data(self, data, **kw): self.set_sheet_data_calls.append(data)
    def dehighlight_all(self, *a, **kw): pass
    def dehighlight_cells(self, *a, **kw): pass
    def extra_bindings(self, *a, **kw): pass
    def deselect(self, *a, **kw): pass
    def lock_column_width(self, *a, **kw): pass
    def align_columns(self, *a, **kw): pass
    def set_cell_data(self, *a, **kw): pass
    def get_cell_data(self, row, col, **kw): return ""
    def identify_column(self, _e): return 0


class FakeFrame:
    def __init__(self, *a, **kw): pass
    def grid(self, *a, **kw): pass
    def pack(self, *a, **kw): pass
    def configure(self, *a, **kw): pass
    config = configure
    def bind(self, *a, **kw): pass
    def columnconfigure(self, *a, **kw): pass
    def grid_columnconfigure(self, *a, **kw): pass
    def grid_rowconfigure(self, *a, **kw): pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _viewer_patches():
    FakeTopLevel.created = []
    FakeSheet.last_instance = None
    FakeSheet.fail_popup = False
    mock_widget = lambda *a, **kw: MagicMock()
    return patch.multiple(
        "SpanshTools.route_viewer",
        TkSheet=FakeSheet,
        tk=MagicMock(
            Toplevel=FakeTopLevel, Frame=FakeFrame, Label=mock_widget,
            Button=mock_widget, Menubutton=mock_widget, Entry=mock_widget,
            Menu=FakeMenu,
            BooleanVar=MagicMock(return_value=MagicMock(get=MagicMock(return_value=False))),
            IntVar=MagicMock(return_value=MagicMock(get=MagicMock(return_value=12))),
            StringVar=MagicMock(return_value=MagicMock(get=MagicMock(return_value=""))),
            BOTH="both", X="x", EW="ew", NSEW="nsew", LEFT="left", RIGHT="right",
            TOP="top", BOTTOM="bottom", END="end", NW="nw", NS="ns", VERTICAL="vertical",
            HORIZONTAL="horizontal", SINGLE="single", W="w", E="e", N="n", S="s",
            SEL="sel", INSERT="insert", NORMAL="normal", DISABLED="disabled",
        ),
    )


def _exact_route_setup(router):
    router.exact_plotter = True
    router.route = [["Sol", "0", "0", "22000.47"], ["Ugrashtim", "1", "85.92", "21975.62"]]
    router.exact_route_data = [
        {"name": "Sol", "distance": 0, "distance_to_destination": 22000.47,
         "fuel_in_tank": 32.00, "fuel_used": 0.00, "must_refuel": True, "has_neutron": False},
        {"name": "Ugrashtim", "distance": 85.92, "distance_to_destination": 21975.62,
         "fuel_in_tank": 26.84, "fuel_used": 5.16, "must_refuel": False, "has_neutron": False},
    ]


# ---------------------------------------------------------------------------
# show / refresh
# ---------------------------------------------------------------------------

def test_force_refresh_reuses_existing_sheet(router):
    _exact_route_setup(router)
    with _viewer_patches():
        viewer = spans_mod.CsvViewerWindow(router)
        viewer.show()
        first_sheet = FakeSheet.last_instance
        router.exact_route_data[0]["fuel_used"] = 7.25
        viewer.show(force_refresh=True)
        assert len(FakeTopLevel.created) == 1
        assert FakeSheet.last_instance is first_sheet
        assert first_sheet.set_sheet_data_calls[-1][0][6] == "7.25"


def test_refresh_preserves_scroll_position(router):
    _exact_route_setup(router)
    with _viewer_patches():
        viewer = spans_mod.CsvViewerWindow(router)
        viewer.show()
        sheet = FakeSheet.last_instance
        sheet.current_yview = (0.35, 0.85)
        sheet.current_xview = (0.25, 0.75)
        sheet.current_selected = SimpleNamespace(row=1, column=0)
        assert viewer._refresh_viewer_in_place(preserve_view=True) is True
        assert sheet.set_yview_calls[-1] == 0.35
        assert sheet.set_xview_calls[-1] == 0.25


# ---------------------------------------------------------------------------
# done toggle
# ---------------------------------------------------------------------------

def test_done_toggle_updates_exact_route_and_persists(router):
    _exact_route_setup(router)
    router.exact_route_data[0]["done"] = False
    router.save_all_route = MagicMock()
    with _viewer_patches():
        spans_mod.CsvViewerWindow(router).show()
        sheet = FakeSheet.last_instance
        sheet.region = "cell"
        sheet.row = 0
        sheet.current_selected = SimpleNamespace(row=0, column=0)
        sheet.MT.callbacks["<ButtonRelease-1>"](SimpleNamespace())
        assert router.exact_route_data[0]["done"] is True
        router.save_all_route.assert_called_once()


def test_fleet_done_toggle_updates_full_group(router):
    router.fleetcarrier = True
    router.route = [["Sol", "2", "0", "20", "No"], ["Sol", "1", "0", "20", "Yes"], ["Achenar", "0", "20", "0", "No"]]
    router.fleet_carrier_data = [
        {"name": "Sol", "done": False}, {"name": "Sol", "done": False}, {"name": "Achenar", "done": False},
    ]
    router.route_done = [False, False, False]
    viewer = spans_mod.CsvViewerWindow(router)
    assert viewer._toggle_done_for_meta({"mode": "fleet", "row_index": 1}) is True
    assert [j["done"] for j in router.fleet_carrier_data] == [True, True, False]


def test_clear_all_done_state(router):
    router.route = [["Sol", "0"], ["Achenar", "1"]]
    router.route_done = [True, False]
    router._update_overlay = MagicMock()
    router.save_all_route = MagicMock()
    viewer = spans_mod.CsvViewerWindow(router)
    assert viewer._clear_all_done_state() is True
    assert router.route_done == [False, False]
    router.save_all_route.assert_called_once()


# ---------------------------------------------------------------------------
# _build_viewer_model
# ---------------------------------------------------------------------------

def test_viewer_anchor_opens_before_waypoint(router):
    """All route types should anchor the viewer one row before the waypoint offset."""
    # Exact
    router.exact_plotter = True
    router.route = [["Sol", "0"], ["Achenar", "1"], ["Colonia", "1"]]
    router.exact_route_data = [
        {"name": "Sol", "distance": 0, "distance_to_destination": 20, "fuel_in_tank": 32, "fuel_used": 0, "must_refuel": False, "has_neutron": False},
        {"name": "Achenar", "distance": 10, "distance_to_destination": 10, "fuel_in_tank": 31, "fuel_used": 1, "must_refuel": False, "has_neutron": False},
        {"name": "Colonia", "distance": 10, "distance_to_destination": 0, "fuel_in_tank": 30, "fuel_used": 1, "must_refuel": False, "has_neutron": False},
    ]
    router.offset = 2
    model = spans_mod.CsvViewerWindow(router)._build_viewer_model(())
    assert model["current_index"] == 1
