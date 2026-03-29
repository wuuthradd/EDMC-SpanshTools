"""Focused regression tests for the route viewer."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import SpanshTools.core as spans_mod


class FakeTopLevel:
    created = []

    def __init__(self, _parent):
        self.exists = True
        self._geometry = "800x600+10+10"
        FakeTopLevel.created.append(self)

    def title(self, *_args, **_kwargs):
        pass

    def resizable(self, *_args, **_kwargs):
        pass

    def minsize(self, *_args, **_kwargs):
        pass

    def protocol(self, *_args, **_kwargs):
        pass

    def config(self, *_args, **_kwargs):
        pass

    configure = config

    def grid_rowconfigure(self, *_args, **_kwargs):
        pass

    def grid_columnconfigure(self, *_args, **_kwargs):
        pass

    def destroy(self):
        self.exists = False

    def winfo_exists(self):
        return self.exists

    def lift(self):
        pass

    def focus_force(self):
        pass

    def winfo_width(self):
        return 800

    def winfo_height(self):
        return 600

    def winfo_screenwidth(self):
        return 1920

    def winfo_x(self):
        return 10

    def winfo_y(self):
        return 10

    def winfo_children(self):
        return []

    def after(self, _delay, func, *args):
        return func(*args)

    def after_cancel(self, *_args, **_kwargs):
        pass

    def after_idle(self, func):
        return func()

    def bind(self, *_args, **_kwargs):
        pass

    def update_idletasks(self):
        pass

    def geometry(self, value=None):
        if value is None:
            return self._geometry
        self._geometry = value


class FakeMenu:
    def __init__(self, *_args, **_kwargs):
        self.entry_states = {}

    def add_command(self, *_args, **_kwargs):
        pass

    def add_radiobutton(self, *_args, **_kwargs):
        pass

    def add_cascade(self, *_args, **_kwargs):
        pass

    def add_separator(self, *_args, **_kwargs):
        pass

    def add_checkbutton(self, *_args, **_kwargs):
        pass

    def entryconfigure(self, label, **kwargs):
        self.entry_states[label] = kwargs


class FakeBinder:
    def __init__(self):
        self.callbacks = {}

    def bind(self, event, callback, add=None):
        self.callbacks[event] = callback


class FakeSheet:
    last_instance = None
    fail_popup = False

    def __init__(self, *_args, **kwargs):
        self.init_headers = kwargs.get("headers", [])
        self.init_data = kwargs.get("data", [])
        self.init_row_index = kwargs.get("row_index", [])
        self.set_sheet_data_calls = []
        self.row_index_calls = []
        self.popup_commands = {}
        self.current_selected = None
        self.current_yview = (0.0, 1.0)
        self.current_xview = (0.0, 1.0)
        self.set_yview_calls = []
        self.set_xview_calls = []
        self.set_currently_selected_calls = []
        self.see_calls = []
        self.region = ""
        self.row = None
        self.MT = FakeBinder()
        self.RI = FakeBinder()
        FakeSheet.last_instance = self

    def grid(self, *_args, **_kwargs):
        pass

    def enable_bindings(self, *_args, **_kwargs):
        pass

    def headers(self, *_args, **_kwargs):
        pass

    def row_index(self, values, **_kwargs):
        self.row_index_calls.append(values)

    def display_columns(self, *_args, **_kwargs):
        pass

    def set_options(self, *_args, **_kwargs):
        pass

    def set_index_width(self, *_args, **_kwargs):
        pass

    def index_align(self, *_args, **_kwargs):
        pass

    def highlight_rows(self, *_args, **_kwargs):
        pass

    def highlight_cells(self, *_args, **_kwargs):
        pass

    def set_index_data(self, *_args, **_kwargs):
        pass

    def readonly_columns(self, *_args, **_kwargs):
        pass

    def column_width(self, *_args, **_kwargs):
        pass

    def popup_menu_add_command(self, label, command, **_kwargs):
        if self.fail_popup:
            raise RuntimeError("popup failed")
        self.popup_commands[label] = command

    def see(self, *_args, **_kwargs):
        self.see_calls.append((_args, _kwargs))

    def refresh(self, *_args, **_kwargs):
        pass

    def winfo_width(self):
        return 800

    def identify_region(self, _event):
        return self.region

    def identify_row(self, _event):
        return self.row

    def get_currently_selected(self):
        return self.current_selected

    def set_currently_selected(self, **kwargs):
        self.current_selected = SimpleNamespace(**kwargs)
        self.set_currently_selected_calls.append(kwargs)

    def get_yview(self):
        return self.current_yview

    def set_yview(self, value):
        self.current_yview = (value, min(value + 0.5, 1.0))
        self.set_yview_calls.append(value)

    def get_xview(self):
        return self.current_xview

    def set_xview(self, value):
        self.current_xview = (value, min(value + 0.5, 1.0))
        self.set_xview_calls.append(value)

    def get_column_data(self, *_args, **_kwargs):
        return []

    def set_sheet_data(self, data, **_kwargs):
        self.set_sheet_data_calls.append(data)

    def dehighlight_all(self, *_args, **_kwargs):
        pass


def _viewer_patches():
    FakeTopLevel.created = []
    FakeSheet.last_instance = None
    FakeSheet.fail_popup = False
    return patch.multiple(
        "SpanshTools.route_viewer",
        TkSheet=FakeSheet,
    )


def test_viewer_force_refresh_reuses_existing_sheet(router):
    router.exact_plotter = True
    router.route = [["Sol", "0", "0", "22000.47"], ["Ugrashtim", "1", "85.92", "21975.62"]]
    router.exact_route_data = [
        {
            "name": "Sol",
            "distance": 0,
            "distance_to_destination": 22000.47,
            "fuel_in_tank": 32.00,
            "fuel_used": 0.00,
            "must_refuel": True,
            "has_neutron": False,
        },
        {
            "name": "Ugrashtim",
            "distance": 85.92,
            "distance_to_destination": 21975.62,
            "fuel_in_tank": 26.84,
            "fuel_used": 5.16,
            "must_refuel": False,
            "has_neutron": False,
        },
    ]

    with patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel), \
         patch("SpanshTools.route_viewer.tk.Label", lambda *_args, **_kwargs: MagicMock()), \
         patch("SpanshTools.route_viewer.tk.Menu", FakeMenu), \
         _viewer_patches():
        viewer = spans_mod.CsvViewerWindow(router)
        viewer.show()
        first_sheet = FakeSheet.last_instance

        router.exact_route_data[0]["fuel_used"] = 7.25
        viewer.show(force_refresh=True)

        assert len(FakeTopLevel.created) == 1
        assert FakeSheet.last_instance is first_sheet
        assert first_sheet.set_sheet_data_calls
        assert first_sheet.set_sheet_data_calls[-1][0][5] == "7.25"


def test_refresh_viewer_in_place_preserves_scroll_and_selection(router):
    router.exact_plotter = True
    router.route = [["Sol", "0", "0", "22000.47"], ["Ugrashtim", "1", "85.92", "21975.62"]]
    router.exact_route_data = [
        {
            "name": "Sol",
            "distance": 0,
            "distance_to_destination": 22000.47,
            "fuel_in_tank": 32.00,
            "fuel_used": 0.00,
            "must_refuel": True,
            "has_neutron": False,
        },
        {
            "name": "Ugrashtim",
            "distance": 85.92,
            "distance_to_destination": 21975.62,
            "fuel_in_tank": 26.84,
            "fuel_used": 5.16,
            "must_refuel": False,
            "has_neutron": False,
        },
    ]

    with patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel), \
         patch("SpanshTools.route_viewer.tk.Label", lambda *_args, **_kwargs: MagicMock()), \
         patch("SpanshTools.route_viewer.tk.Menu", FakeMenu), \
         _viewer_patches():
        viewer = spans_mod.CsvViewerWindow(router)
        viewer.show()
        sheet = FakeSheet.last_instance
        sheet.current_yview = (0.35, 0.85)
        sheet.current_selected = SimpleNamespace(row=1, column=0)
        sheet.see_calls.clear()

        assert viewer._refresh_viewer_in_place(preserve_view=True) is True
        assert sheet.set_yview_calls[-1] == 0.35
        assert sheet.set_currently_selected_calls[-1] == {"row": 1, "column": 0}
        assert sheet.see_calls == []


def test_refresh_viewer_in_place_preserves_horizontal_scroll(router):
    router.exact_plotter = True
    router.route = [["Sol", "0", "0", "22000.47"], ["Ugrashtim", "1", "85.92", "21975.62"]]
    router.exact_route_data = [
        {"name": "Sol", "distance": 0, "distance_to_destination": 22000.47, "fuel_in_tank": 32.0, "fuel_used": 0.0, "must_refuel": True, "has_neutron": False},
        {"name": "Ugrashtim", "distance": 85.92, "distance_to_destination": 21975.62, "fuel_in_tank": 26.84, "fuel_used": 5.16, "must_refuel": False, "has_neutron": False},
    ]

    with patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel), \
         patch("SpanshTools.route_viewer.tk.Label", lambda *_args, **_kwargs: MagicMock()), \
         patch("SpanshTools.route_viewer.tk.Menu", FakeMenu), \
         _viewer_patches():
        viewer = spans_mod.CsvViewerWindow(router)
        viewer.show()
        sheet = FakeSheet.last_instance
        sheet.current_xview = (0.25, 0.75)

        assert viewer._refresh_viewer_in_place(preserve_view=True) is True
        assert sheet.set_xview_calls[-1] == 0.25


def test_set_current_waypoint_from_exploration_meta_uses_route_index(router):
    router.route = [["Sol", "0"], ["Achenar", "5"]]
    router.exploration_plotter = True
    router.exploration_mode = "Road to Riches"
    router.compute_distances = MagicMock()
    router.save_all_route = MagicMock()

    viewer = spans_mod.CsvViewerWindow(router)

    result = viewer._set_current_waypoint_from_meta(
        {"mode": "exploration", "row_index": 99, "route_index": 1, "is_total": False}
    )

    assert result is True
    assert router.offset == 1
    assert router.next_stop == "Achenar"
    router.compute_distances.assert_called_once()
    router.copy_waypoint.assert_called_once()
    router.update_gui.assert_called_once()
    router.save_all_route.assert_called_once()


def test_exact_viewer_opens_from_row_before_waypoint(router):
    router.exact_plotter = True
    router.route = [["Sol", "0"], ["Achenar", "1"], ["Colonia", "1"]]
    router.exact_route_data = [
        {"name": "Sol", "distance": 0, "distance_to_destination": 20, "fuel_in_tank": 32, "fuel_used": 0, "must_refuel": False, "has_neutron": False},
        {"name": "Achenar", "distance": 10, "distance_to_destination": 10, "fuel_in_tank": 31, "fuel_used": 1, "must_refuel": False, "has_neutron": False},
        {"name": "Colonia", "distance": 10, "distance_to_destination": 0, "fuel_in_tank": 30, "fuel_used": 1, "must_refuel": False, "has_neutron": False},
    ]
    router.offset = 2

    viewer_model = spans_mod.CsvViewerWindow(router)._build_viewer_model(())

    assert viewer_model["current_index"] == 1


def test_neutron_viewer_opens_from_row_before_waypoint(router):
    router.route_type = "neutron"
    router.current_plotter_name = "Neutron Plotter"
    router.route = [["Sol", "0"], ["Achenar", "2"], ["Colonia", "3"]]
    router.route_done = [False, False, False]
    router.offset = 2

    viewer_model = spans_mod.CsvViewerWindow(router)._build_viewer_model(())

    assert viewer_model["current_index"] == 1


def test_fleet_viewer_opens_from_previous_visible_group(router):
    router.fleetcarrier = True
    router.route = [
        ["Sol", "2", "0", "20", "No"],
        ["Sol", "1", "0", "20", "Yes"],
        ["Achenar", "1", "20", "10", "No"],
        ["Colonia", "0", "10", "0", "No"],
    ]
    router.fleet_carrier_data = [
        {"name": "Sol", "is_waypoint": True},
        {"name": "Sol", "is_waypoint": True},
        {"name": "Achenar", "is_waypoint": True},
        {"name": "Colonia", "is_waypoint": True},
    ]
    router.offset = 3

    viewer_model = spans_mod.CsvViewerWindow(router)._build_viewer_model(())

    assert viewer_model["current_index"] == 2


def test_exploration_viewer_opens_from_row_before_waypoint_system(router):
    router.exploration_plotter = True
    router.exploration_mode = "Road to Riches"
    router.route = [["Sol", "0"], ["Achenar", "2"], ["Colonia", "3"]]
    router.offset = 2
    router.exploration_route_data = [
        {"name": "Sol", "jumps": 0, "bodies": [{"name": "Sol A 1", "subtype": "Rocky body", "is_terraformable": False, "distance_to_arrival": 100, "estimated_scan_value": 0, "estimated_mapping_value": 0, "done": False}]},
        {"name": "Achenar", "jumps": 2, "bodies": [{"name": "Achenar 1", "subtype": "Rocky body", "is_terraformable": False, "distance_to_arrival": 50, "estimated_scan_value": 0, "estimated_mapping_value": 0, "done": False}]},
        {"name": "Colonia", "jumps": 3, "bodies": [{"name": "Colonia 1", "subtype": "Rocky body", "is_terraformable": False, "distance_to_arrival": 25, "estimated_scan_value": 0, "estimated_mapping_value": 0, "done": False}]},
    ]

    viewer_model = spans_mod.CsvViewerWindow(router)._build_viewer_model(())

    assert viewer_model["current_index"] == 1


def test_viewer_zebra_row_style_matches_light_mode_sheet_parity(router):
    viewer = spans_mod.CsvViewerWindow(router)
    viewer._csv_viewer_dark_mode = False

    even_bg, even_fg = viewer._viewer_zebra_row_style(0)
    odd_bg, odd_fg = viewer._viewer_zebra_row_style(1)

    assert even_bg == "#ffffff"
    assert even_fg == "black"
    assert odd_bg == "#e5edf7"
    assert odd_fg == "black"


def test_exploration_done_meta_maps_to_landmark_rows(router):
    router.exploration_plotter = True
    router.exploration_mode = "Exomastery"
    router.exploration_route_data = [
        {
            "name": "Sol",
            "bodies": [
                {
                    "name": "Sol A 1",
                    "landmarks": [
                        {"subtype": "A", "done": False},
                        {"subtype": "B", "done": False},
                    ],
                }
            ],
        }
    ]

    viewer = spans_mod.CsvViewerWindow(router)
    meta = {"mode": "exploration", "row_index": 1}

    assert viewer._done_value_for_meta(meta) is False
    assert viewer._toggle_done_for_meta(meta) is True
    assert viewer._done_value_for_meta(meta) is True
    assert router.exploration_route_data[0]["bodies"][0]["landmarks"][1]["done"] is True


def test_sheet_index_click_toggles_done_and_persists(router):
    router.exact_plotter = True
    router.route = [["Sol", "0", "0", "22000.47"]]
    router.exact_route_data = [
        {
            "name": "Sol",
            "distance": 0,
            "distance_to_destination": 22000.47,
            "fuel_in_tank": 32.00,
            "fuel_used": 0.00,
            "must_refuel": True,
            "has_neutron": False,
            "done": False,
        }
    ]
    router.save_all_route = MagicMock()

    with patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel), \
         patch("SpanshTools.route_viewer.tk.Label", lambda *_args, **_kwargs: MagicMock()), \
         patch("SpanshTools.route_viewer.tk.Menu", FakeMenu), \
         _viewer_patches():
        spans_mod.CsvViewerWindow(router).show()
        sheet = FakeSheet.last_instance
        sheet.region = "index"
        sheet.row = 0

        sheet.RI.callbacks["<ButtonRelease-1>"](SimpleNamespace())

        assert router.exact_route_data[0]["done"] is True
        router.save_all_route.assert_called_once()


def test_fleet_done_toggle_updates_full_group(router):
    router.fleetcarrier = True
    router.route = [
        ["Sol", "2", "0", "20", "No"],
        ["Sol", "1", "0", "20", "Yes"],
        ["Achenar", "0", "20", "0", "No"],
    ]
    router.fleet_carrier_data = [
        {"name": "Sol", "done": False},
        {"name": "Sol", "done": False},
        {"name": "Achenar", "done": False},
    ]
    router.route_done = [False, False, False]

    viewer = spans_mod.CsvViewerWindow(router)

    assert viewer._toggle_done_for_meta({"mode": "fleet", "row_index": 1}) is True
    assert [jump["done"] for jump in router.fleet_carrier_data] == [True, True, False]
    assert router.route_done == [True, True, False]


def test_clear_all_done_state_resets_route_done_and_persists(router):
    router.route = [["Sol", "0"], ["Achenar", "1"]]
    router.route_done = [True, False]
    router.update_gui = MagicMock()
    router._update_overlay = MagicMock()
    router.save_all_route = MagicMock()

    viewer = spans_mod.CsvViewerWindow(router)

    assert viewer._clear_all_done_state() is True
    assert router.route_done == [False, False]
    router.update_gui.assert_called_once()
    router._update_overlay.assert_called_once()
    router.save_all_route.assert_called_once()


def test_viewer_setup_failure_cleans_runtime_state(router):
    router.route = [["Sol", "1", "10", "10"]]
    router.route_done = [False]
    router._log_unexpected = MagicMock()
    FakeSheet.fail_popup = True

    with patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel), \
         patch("SpanshTools.route_viewer.tk.Label", lambda *_args, **_kwargs: MagicMock()), \
         patch("SpanshTools.route_viewer.tk.Menu", FakeMenu), \
         patch("SpanshTools.route_viewer.TkSheet", FakeSheet):
        spans_mod.CsvViewerWindow(router).show()

    assert router.csv_viewer_win is None
    assert router._csv_viewer_runtime is None
    router._log_unexpected.assert_any_call("Failed to initialize route viewer")


def test_exact_viewer_export_helpers_use_consistent_flag_strings(router):
    router.exact_plotter = True
    router.exact_route_data = [
        {
            "name": "Sol",
            "distance": 0,
            "distance_to_destination": 22000.47,
            "fuel_in_tank": 32.00,
            "fuel_used": 0.00,
            "must_refuel": True,
            "has_neutron": True,
            "done": True,
        }
    ]

    viewer = spans_mod.CsvViewerWindow(router)
    export_row = viewer._viewer_export_rows()[0]
    export_header, export_rows = viewer._spansh_export_payload()

    assert export_row[0] == router._done_cell_value(True)
    assert export_row[7] == "Yes"
    assert export_row[8] == "Yes"
    assert export_header[-2:] == ["Refuel", "Neutron Star"]
    assert export_rows[0][0] == "1"
    assert export_rows[0][-2:] == ["Yes", "Yes"]


def test_fleet_viewer_export_helpers_use_pristine_and_yes_no_values(router):
    router.fleetcarrier = True
    router.fleet_carrier_data = [
        {
            "name": "Sol",
            "distance": 0,
            "distance_to_destination": 10,
            "fuel_in_tank": 1000,
            "tritium_in_market": 500,
            "fuel_used": 0,
            "has_icy_ring": True,
            "is_system_pristine": True,
            "must_restock": True,
            "restock_amount": 25,
            "is_waypoint": True,
            "done": True,
        }
    ]

    viewer = spans_mod.CsvViewerWindow(router)
    export_row = viewer._viewer_export_rows()[0]
    export_header, export_rows = viewer._spansh_export_payload()

    assert export_row[0] == router._done_cell_value(True)
    assert export_row[8] == "Pristine"
    assert export_row[9] == "Yes"
    assert export_header[4] == "Is Waypoint"
    assert export_rows[0][4] == "Yes"
    assert export_header[-3:] == ["Icy Ring", "Pristine", "Restock Tritium"]
    assert export_rows[0][0] == "1"
    assert export_rows[0][-3:] == ["Yes", "Yes", "Yes"]


def test_default_export_filename_uses_exobiology_prefix(router):
    router.route_type = "exploration"
    router.route = [["Sol", "0"], ["Colonia", "1"]]
    router.exploration_mode = "Exomastery"
    router._plotter_settings = {
        "planner": "Exomastery",
        "settings": {
            "source": "Sol",
            "destination": "Colonia",
        },
    }

    filename = router._default_export_filename(".json")

    assert filename == "exobiology-Sol-Colonia.json"


def test_default_export_filename_uses_fleet_undefined_destination(router):
    router.route_type = "fleet_carrier"
    router.route = [["Sol", "0"], ["Achenar", "1"]]
    router._plotter_settings = {
        "planner": "Fleet Carrier Router",
        "settings": {
            "source": "Sol",
            "destinations": ["Achenar", "Colonia"],
        },
    }

    filename = router._default_export_filename(".csv")

    assert filename == "fleet-carrier-Sol-Colonia.csv"
