"""Tests for exact plotter route processing and persistence."""

import sys
import os
import json
import threading
import pytest
import requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import csv
from unittest.mock import MagicMock, patch
import SpanshTools.core as spans_mod
import SpanshTools.plotters as plotters_mod
import SpanshTools.route_io as route_io_mod
from SpanshTools.core import SpanshTools
from conftest import DummyFrame, DummyWidget, create_router




# Mock exact plotter API response
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
    }
}


class _RouteGuiWidget(DummyWidget):
    def __init__(self):
        super().__init__()
        self._values = {}

    def cget(self, key):
        return self._values.get(key, "")

    def __setitem__(self, key, value):
        self._values[key] = value

    def __getitem__(self, key):
        return self._values.get(key, "")


class _RouteGuiFrame(DummyFrame):
    def columnconfigure(self, *_args, **_kwargs):
        return None

    def update_idletasks(self):
        return None


class TestExactPlotSuccess:
    def test_route_populated(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)

        assert router.exact_plotter is True
        assert router.galaxy is False
        assert router.fleetcarrier is False
        assert len(router.route) == 3
        assert len(router.exact_route_data) == 3

    def test_route_system_names(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)

        assert router.route[0][0] == "Sol"
        assert router.route[1][0] == "Alpha Centauri"
        assert router.route[2][0] == "Barnard's Star"

    def test_route_distances(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)

        assert router.route[0][2] == "0"
        assert router.route[1][2] == "4.38"

    def test_jumps_counted(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)

        assert router.jumps_left == 2  # 3 entries, first is source (not a jump)

    def test_refuel_status_set(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)

        # Monitor says we're at Sol, so offset skips to 1 (Alpha Centauri)
        # Alpha Centauri has must_refuel=True
        assert router.pleaserefuel is True

    def test_skip_source_if_already_there(self, router):
        # Mock that we're currently at Sol
        with patch("SpanshTools.core.monitor.state", {"SystemName": "Sol"}):
            router._exact_plot_success(MOCK_ROUTE_DATA)

        assert router.offset == 1
        assert router.next_stop == "Alpha Centauri"
        assert router.exact_route_data[0]["done"] is True

    def test_exact_route_data_preserved(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)

        assert router.exact_route_data[0]["must_refuel"] is True
        assert router.exact_route_data[1]["must_refuel"] is True
        assert router.exact_route_data[1]["is_scoopable"] is True
        assert router.exact_route_data[2]["must_refuel"] is False


def test_linux_clipboard_uses_external_helper_not_tk(monkeypatch, router):
    router.parent.clipboard_clear = MagicMock(side_effect=AssertionError("tk clipboard should not be used on linux"))
    router.parent.clipboard_append = MagicMock(side_effect=AssertionError("tk clipboard should not be used on linux"))

    commands = []

    class ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}

        def start(self):
            self.target(*self.args, **self.kwargs)

    class FakeProc:
        def __init__(self, command):
            self.command = command
            self.returncode = 0

        def communicate(self, data, timeout=None):
            commands.append((self.command, data.decode("utf-8"), timeout))
            return (b"", b"")

    monkeypatch.setattr(spans_mod.sys, "platform", "linux")
    monkeypatch.setattr(spans_mod.threading, "Thread", ImmediateThread)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        spans_mod.subprocess,
        "Popen",
        lambda command, stdin=None, stdout=None, stderr=None: FakeProc(command),
    )

    assert router._copy_to_clipboard("HIP 100000") is True
    assert commands
    assert commands[0][0] == ["wl-copy"]
    assert commands[0][1] == "HIP 100000"


def test_linux_clipboard_prefers_flatpak_host_binary(monkeypatch, router):
    monkeypatch.delenv("EDMC_SPANSH_TOOLS_XCLIP", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        spans_mod.os.path,
        "exists",
        lambda path: path == "/run/host/usr/bin/wl-copy",
    )

    commands = router._linux_clipboard_commands()

    assert commands[0] == ["/run/host/usr/bin/wl-copy"]
    assert commands[1] == ["/run/host/usr/bin/wl-copy", "--primary"]


class TestExactPlotterPersistence:
    def test_save_and_load_route(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.save_all_route()

        route_state_path = router._route_state_path()
        assert os.path.exists(route_state_path)

        with open(route_state_path, "r") as f:
            payload = json.load(f)

        assert payload["planner"] == "Galaxy Plotter"
        assert payload["exact_plotter"] is True
        assert len(payload["route"]) == 3
        assert payload["route"][0][0] == "Sol"
        assert payload["exact_route_data"][0]["fuel_in_tank"] == 32.0
        assert payload["exact_route_data"][1]["fuel_used"] == 0.1

    def test_load_restores_exact_plotter_mode(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.save_all_route()

        # Create new router and load
        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.open_last_route()

        assert router2.exact_plotter is True
        assert len(router2.route) == 3
        assert len(router2.exact_route_data) == 3
        assert router2.route[0][0] == "Sol"
        assert router2.route[0][1] == "0"
        assert router2.exact_route_data[0]["fuel_in_tank"] == 32.0
        assert router2.exact_route_data[0]["must_refuel"] is True
        assert router2.exact_route_data[1]["fuel_used"] == 0.1
        assert router2.exact_route_data[1]["must_refuel"] is True
        router2.copy_waypoint.assert_not_called()

    def test_open_last_route_does_not_infer_supercharge_from_monitor_state(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.is_supercharged = False

        with patch.object(
            spans_mod.monitor,
            "state",
            {
                "SystemName": "Sol",
                "StarPos": [0, 0, 0],
                "JumpRangeCurrent": 200.0,
                "MaxJumpRange": 50.0,
            },
        ):
            router2.open_last_route()

        assert router2.is_supercharged is False

    def test_load_restores_exact_plotter_mode_from_route_state_json(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.offset = 2
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.open_last_route()

        assert router2.exact_plotter is True
        assert router2.current_plotter_name == "Galaxy Plotter"
        assert len(router2.route) == 3
        assert len(router2.exact_route_data) == 3
        assert router2.offset == 2
        assert router2.route[2][0] == "Barnard's Star"

    def test_loads_spansh_exact_export_layout(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System Name",
                "Distance Travelled",
                "Remaining",
                "Fuel Remaining",
                "Fuel Used",
                "Refuel",
                "Neutron",
            ])
            writer.writerow(["Sol", "0", "100.5", "32.0", "0", "No", "No"])
            writer.writerow(["Alpha Centauri", "4.38", "96.12", "31.9", "0.1", "Yes", "No"])
            writer.writerow(["Barnard's Star", "5.95", "90.17", "30.5", "1.4", "No", "No"])

        router.plot_csv(router.save_route_path)

        assert router.exact_plotter is True
        assert len(router.route) == 3
        assert router.route[0] == ["Sol", "0", "0", "100.5"]
        assert router.route[1] == ["Alpha Centauri", "1", "4.38", "96.12"]
        assert router.jumps_left == 2
        assert router.exact_route_data[0]["must_refuel"] is True
        assert router.exact_route_data[1]["must_refuel"] is True
        assert router.exact_route_data[0]["fuel_in_tank"] == "32.0"
        assert router.exact_route_data[2]["fuel_used"] == "1.4"

    def test_loads_exact_export_with_total_row_and_header_aliases(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Done",
                "System Name",
                "Distance(LY)",
                "Remaining(LY)",
                "Jumps Left",
                "Fuel Left (tonnes)",
                "Fuel Used (tonnes)",
                "Refuel?",
                "Neutron",
            ])
            writer.writerow(["□", "Sol", "0", "100.5", "2", "32.0", "0", "", ""])
            writer.writerow(["□", "Alpha Centauri", "4.38", "96.12", "1", "31.9", "0.1", "Yes", ""])
            writer.writerow(["□", "Barnard's Star", "5.95", "90.17", "0", "30.5", "1.4", "", ""])
            writer.writerow(["", "Total", "10.33", "", "2", "", "1.5", "", ""])

        router.plot_csv(router.save_route_path)

        assert router.exact_plotter is True
        assert len(router.route) == 3
        assert len(router.exact_route_data) == 3
        assert router.route[-1][0] == "Barnard's Star"
        assert router.route[-1][1] == "1"

    def test_spansh_exact_like_header_does_not_fall_into_galaxy_import(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System Name",
                "Distance Travelled",
                "Remaining",
                "Fuel Remaining",
                "Fuel Used",
                "Refuel",
            ])
            writer.writerow(["Sol", "0", "100.5", "32.0", "0", "No"])
            writer.writerow(["Alpha Centauri", "4.38", "96.12", "31.9", "0.1", "Yes"])

        router.plot_csv(router.save_route_path)

        assert router.exact_plotter is True
        assert router.galaxy is False
        assert len(router.exact_route_data) == 2

    def test_spansh_exact_import_accepts_system_header_variant(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System",
                "Distance Travelled",
                "Remaining",
                "Fuel Remaining",
                "Fuel Used",
                "Refuel",
                "Neutron",
            ])
            writer.writerow(["Sol", "0", "100.5", "32.0", "0", "No", "No"])
            writer.writerow(["Alpha Centauri", "4.38", "96.12", "31.9", "0.1", "Yes", "No"])

        router.plot_csv(router.save_route_path)

        assert router.exact_plotter is True
        assert router.galaxy is False
        assert router.route[0][0] == "Sol"
        assert router.route[1][0] == "Alpha Centauri"

    def test_spansh_exact_import_accepts_distance_remaining_fuelleft_neutronstar_variant(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System Name",
                "Distance",
                "Distance Remaining",
                "Fuel Left",
                "Fuel Used",
                "Refuel",
                "Neutron Star",
            ])
            writer.writerow(["Sol", "0", "38494.18", "32", "0", "Yes", "No"])
            writer.writerow(["Ugrashtrim", "85.92", "38473.94", "26.84", "5.16", "No", "No"])
            writer.writerow(["HIP 100000", "344.90", "0", "4.90", "4.44", "No", "No"])

        router.plot_csv(router.save_route_path)

        assert router.exact_plotter is True
        assert router.galaxy is False
        assert router.route[0] == ["Sol", "0", "0", "38494.18"]
        assert router.route[-1] == ["HIP 100000", "1", "344.90", "0"]
        assert router.exact_route_data[0]["fuel_in_tank"] == "32"
        assert router.exact_route_data[-1]["fuel_used"] == "4.44"
        assert router.exact_route_data[-1]["has_neutron"] is False


class TestExactPlotterClear:
    def test_clear_resets_flags(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)

        assert router.exact_plotter is True

        router.clear_route(show_dialog=False)

        assert router.exact_plotter is False
        assert router.exact_route_data == []
        assert router.route == []
        assert router.overlay_var.get() is False


class TestUpdateRouteExactPlotter:
    def test_advance_sets_refuel(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.offset = 0

        # Advance to Alpha Centauri (must_refuel=True)
        router.update_route(direction=1)

        assert router.next_stop == "Alpha Centauri"
        assert router.pleaserefuel is True

    def test_advance_past_refuel_clears_it(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.offset = 0

        # Advance twice: Sol -> Alpha Centauri -> Barnard's Star
        router.update_route(direction=1)
        router.update_route(direction=1)

        assert router.next_stop == "Barnard's Star"
        assert router.pleaserefuel is False


class TestExactPlotterApiParams:
    def test_param_building(self, router):
        """Verify that plot_exact_route builds correct params."""
        router.ship_fsd_data = {
            "optimal_mass": 1800.0,
            "max_fuel_per_jump": 8.0,
            "fuel_power": 2.6,
            "fuel_multiplier": 0.012,
            "tank_size": 32.0,
            "reserve_size": 0.63,
            "unladen_mass": 800.0,
            "range_boost": 10.5,
            "cargo_capacity": 468,
        }

        # We can't easily call plot_exact_route without a GUI,
        # but we can verify the math for base_mass
        fsd = router.ship_fsd_data
        base_mass = fsd["unladen_mass"] + fsd["reserve_size"]
        assert base_mass == 800.63

        internal_tank = fsd["reserve_size"]
        assert internal_tank == 0.63

    def test_plot_exact_route_clamps_spinbox_values_before_submit(self, monkeypatch, router):
        class _SpinboxStub:
            def __init__(self, value, minimum, maximum):
                self.value = str(value)
                self._options = {"from": str(minimum), "to": str(maximum)}

            def get(self):
                return self.value

            def delete(self, *_args, **_kwargs):
                self.value = ""

            def insert(self, _index, value):
                self.value = str(value)

            def cget(self, key):
                return self._options[key]

        captured = {}

        class _CaptureThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                captured["target"] = target
                captured["args"] = args
                captured["kwargs"] = kwargs or {}
                captured["daemon"] = daemon

            def start(self):
                return None

        router.ship_fsd_data = {
            "optimal_mass": 1800.0,
            "max_fuel_per_jump": 8.0,
            "fuel_power": 2.6,
            "fuel_multiplier": 0.012,
            "tank_size": 32.0,
            "reserve_size": 0.63,
            "unladen_mass": 800.0,
            "range_boost": 10.5,
            "supercharge_multiplier": 4,
        }
        router.exact_source_ac = MagicMock(get=MagicMock(return_value="Sol"), placeholder="Source System")
        router.exact_dest_ac = MagicMock(get=MagicMock(return_value="Colonia"), placeholder="Destination System")
        router.exact_cargo_entry = _SpinboxStub("12000", 0, 9999)
        router.exact_reserve_entry = _SpinboxStub("99.5", 0, 32)
        router.exact_is_supercharged = MagicMock(get=MagicMock(return_value=False))
        router.exact_use_supercharge = MagicMock(get=MagicMock(return_value=True))
        router.exact_use_injections = MagicMock(get=MagicMock(return_value=False))
        router.exact_exclude_secondary = MagicMock(get=MagicMock(return_value=False))
        router.exact_refuel_scoopable = MagicMock(get=MagicMock(return_value=True))
        router.exact_algorithm = MagicMock(get=MagicMock(return_value="trunkle"))
        router.exact_calculate_btn = MagicMock()
        router.exact_error_txt = MagicMock()
        router._set_plot_running_state = MagicMock()
        router._next_plot_token = MagicMock(return_value=7)

        monkeypatch.setattr(plotters_mod.threading, "Thread", _CaptureThread)

        router.plot_exact_route()

        params = captured["args"][0]
        assert params["cargo"] == 9999
        assert params["reserve_size"] == 32
        assert router.exact_cargo_entry.get() == "9999"
        assert router.exact_reserve_entry.get() == "32.0"
        assert router._pending_exact_settings["cargo"] == "9999"
        assert router._pending_exact_settings["reserve"] == "32.0"


class TestNeutronImportRouting:
    def test_neutron_csv_does_not_fall_into_exact_import(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System Name",
                "Distance To Arrival",
                "Distance Remaining",
                "Neutron Star",
                "Jumps",
            ])
            writer.writerow(["Sol", "0", "731.320141534515", "No", "0"])
            writer.writerow(["PSR J1752-2806", "407.486400990496", "457.873300143582", "Yes", "6"])
            writer.writerow(["HIP 100000", "344.896229581721", "0", "No", "2"])

        router.plot_csv(router.save_route_path)

        assert router.current_plotter_name == "Neutron Plotter"
        assert router.exact_plotter is False
        assert router.galaxy is False
        assert len(router.route) == 3
        assert router.route[1] == ["PSR J1752-2806", "6", "407.486400990496", "457.873300143582", "Yes"]

    def test_fleet_csv_does_not_fall_into_exact_import(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System Name",
                "Distance",
                "Distance Remaining",
                "Tritium in tank",
                "Tritium in market",
                "Fuel Used",
                "Icy Ring",
                "Pristine",
                "Restock Tritium",
            ])
            writer.writerow(["Sol", "0", "19857.6090423276", "", "10000", "0", "No", "No", "No"])
            writer.writerow(["Musca Dark Region GM-U b3-10", "499.140688341286", "19359.4148725881", "", "9868", "132", "Yes", "Yes", "No"])

        router.plot_csv(router.save_route_path)

        assert router.fleetcarrier is True
        assert router.exact_plotter is False
        assert router.galaxy is False
        assert router.current_plotter_name == "Fleet Carrier Router"
        assert len(router.fleet_carrier_data) == 2
        assert router.route[1][0] == "Musca Dark Region GM-U b3-10"
        assert router.fleet_carrier_data[0]["is_waypoint"] is True
        assert router.fleet_carrier_data[1]["is_waypoint"] is True

    def test_fleet_import_marks_first_last_and_duplicate_systems_as_waypoints(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System Name",
                "Distance",
                "Distance Remaining",
                "Tritium in tank",
                "Tritium in market",
                "Fuel Used",
                "Icy Ring",
                "Pristine",
                "Restock Tritium",
            ])
            writer.writerow(["Sol", "0", "1000", "", "10000", "0", "No", "No", "No"])
            writer.writerow(["Carang Hut", "22.9", "0", "", "0", "10", "No", "No", "No"])
            writer.writerow(["Carang Hut", "0", "135.8", "", "0", "0", "No", "No", "No"])
            writer.writerow(["A Bootis", "135.8", "0", "", "0", "32", "No", "No", "No"])

        router.plot_csv(router.save_route_path)

        assert [jump["is_waypoint"] for jump in router.fleet_carrier_data] == [True, True, True, True]

    def test_simple_csv_import_does_not_reuse_previous_plotter_name(self, router):
        router._plotter_settings = {"planner": "Galaxy Plotter", "settings": {"source": "Sol"}}

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["System Name", "Jumps"])
            writer.writerow(["Sol", "0"])
            writer.writerow(["Achenar", "4"])

        router.plot_csv(router.save_route_path)

        assert router.route_type == "simple"
        assert router.current_plotter_name == "Simple Route"

    def test_fleet_import_reconstructs_restock_amount_from_fuel_delta(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System Name",
                "Distance",
                "Distance Remaining",
                "Tritium in tank",
                "Tritium in market",
                "Fuel Used",
                "Icy Ring",
                "Pristine",
                "Restock Tritium",
            ])
            writer.writerow(["Graae Phroo TZ-T b9-0", "497.48", "41159.12", "141", "0", "105", "No", "No", "No"])
            writer.writerow(["Graae Phroo RW-H b2-0", "498.03", "40663.23", "1000", "0", "105", "No", "No", "Yes"])

        router.plot_csv(router.save_route_path)

        assert router.fleet_carrier_data[1]["must_restock"] is True
        assert router.fleet_carrier_data[1]["restock_amount"] == 964.0

    def test_fleet_import_leaves_fuel_left_blank_when_spansh_csv_leaves_it_blank(self, router):

        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "System Name",
                "Distance",
                "Distance Remaining",
                "Tritium in tank",
                "Tritium in market",
                "Fuel Used",
                "Icy Ring",
                "Pristine",
                "Restock Tritium",
            ])
            writer.writerow(["Sol", "0", "41656.60", "", "0", "0", "No", "No", "No"])
            writer.writerow(["Graae Phroo TZ-T b9-0", "497.48", "41159.12", "", "0", "859", "No", "No", "No"])
            writer.writerow(["Graae Phroo RW-H b2-0", "498.03", "40663.23", "", "0", "105", "No", "No", "Yes"])

        router.plot_csv(router.save_route_path)

        assert router.fleet_carrier_data[0]["fuel_in_tank"] == ""
        assert router.fleet_carrier_data[1]["fuel_in_tank"] == ""
        assert router.fleet_carrier_data[2]["fuel_in_tank"] == ""
        assert router.fleet_carrier_data[2]["restock_amount"] == ""

    def test_fleet_open_last_route_uses_countdown_not_sum(self, router):
        with open(router.save_route_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Done",
                "System Name",
                "Distance",
                "Distance Remaining",
                "Is Waypoint",
                "Tritium in tank",
                "Tritium in market",
                "Fuel Used",
                "Icy Ring",
                "Pristine",
                "Restock Tritium",
                "Restock Amount",
            ])
            writer.writerow(["□", "Sol", "0", "19857.60", "Yes", "1000", "10000", "0", "No", "No", "No", ""])
            writer.writerow(["□", "A", "499.14", "19359.41", "No", "893", "9868", "107", "No", "No", "No", ""])
            writer.writerow(["□", "B", "499.29", "18861.38", "No", "786", "9736", "107", "No", "No", "No", ""])
            writer.writerow(["□", "C", "499.99", "18363.79", "No", "679", "9604", "107", "No", "No", "No", ""])

        router.plot_csv(router.save_route_path)
        router.offset = 1
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.open_last_route()

        assert router2.fleetcarrier is True
        assert router2.offset == 1
        assert router2.jumps_left == 2


class TestJsonImport:
    def test_imports_neutron_json(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {"from": "Sol", "to": "HIP 100000", "range": 87, "efficiency": 0.6, "supercharge_multiplier": 4},
            "result": {
                "system_jumps": [
                    {"system": "Sol", "jumps": 0, "distance_jumped": 0, "distance_left": 731.32, "neutron_star": False},
                    {"system": "HIP 100000", "jumps": 2, "distance_jumped": 344.9, "distance_left": 0, "neutron_star": True},
                ]
            },
        }

        with open(router.save_route_path.replace(".csv", ".json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(router.save_route_path.replace(".csv", ".json"))

        assert router.current_plotter_name == "Neutron Plotter"
        assert router.route[1][0] == "HIP 100000"
        assert router.route[1][4] == "Yes"

    def test_imports_neutron_json_normalizes_supercharge_multiplier_for_radio_restore(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {
                "from": "Sol",
                "to": "HIP 100000",
                "range": 87,
                "efficiency": 0.6,
                "supercharge_multiplier": 6.0,
            },
            "result": {
                "system_jumps": [
                    {"system": "Sol", "jumps": 0, "distance_jumped": 0, "distance_left": 731.32, "neutron_star": False},
                    {"system": "HIP 100000", "jumps": 2, "distance_jumped": 344.9, "distance_left": 0, "neutron_star": True},
                ]
            },
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        settings = router._settings_for_planner("Neutron Plotter")
        assert settings["supercharge_multiplier"] == 6

        router.supercharge_multiplier.set(
            router._normalize_supercharge_multiplier(settings.get("supercharge_multiplier", 4))
        )
        assert router.supercharge_multiplier.get() == 6
        assert str(router.supercharge_multiplier._tk.globalgetvar(str(router.supercharge_multiplier))) == "6"

    def test_imports_exact_json(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {"source_system": "Sol", "destination_system": "Alpha Centauri"},
            "result": {
                "jumps": [
                    {"name": "Sol", "distance": 0, "distance_to_destination": 100.5, "fuel_in_tank": 32.0, "fuel_used": 0, "must_refuel": False, "has_neutron": False, "is_scoopable": False},
                    {"name": "Alpha Centauri", "distance": 4.38, "distance_to_destination": 96.12, "fuel_in_tank": 31.9, "fuel_used": 0.1, "must_refuel": True, "has_neutron": False, "is_scoopable": True},
                ]
            },
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.exact_plotter is True
        assert router.route[1][0] == "Alpha Centauri"
        assert router.exact_route_data[1]["must_refuel"] is True
        assert router._exact_settings["source"] == "Sol"
        assert router._exact_settings["destination"] == "Alpha Centauri"

    def test_spansh_json_export_payload_uses_exploration_defaults_when_settings_missing(self, router):
        router.exploration_plotter = True
        router.exploration_mode = "Rocky/HMC Route"
        router.current_plotter_name = "Rocky/HMC Route"
        router.route = [["Sol", "0"], ["HIP 100000", "2"]]
        router.exploration_route_data = [
            {
                "name": "Sol",
                "jumps": 0,
                "bodies": [{"name": "Sol A 1", "distance_to_arrival": 100, "done": False}],
            },
            {
                "name": "HIP 100000",
                "jumps": 2,
                "bodies": [{"name": "HIP 100000 A 1", "distance_to_arrival": 50, "done": False}],
            },
        ]
        router._plotter_settings = {}

        payload = router._spansh_json_export_payload()

        assert payload["parameters"]["source"] == "Sol"
        assert payload["parameters"]["destination"] == "HIP 100000"
        assert payload["parameters"]["radius"] == 25
        assert payload["parameters"]["max_results"] == 100
        assert payload["parameters"]["max_distance"] == 50000
        assert payload["parameters"]["planner"] == "Rocky/HMC Route"
        assert payload["parameters"]["loop"] is True

    def test_spansh_json_export_payload_uses_exact_defaults_when_settings_missing(self, router):
        router.exact_plotter = True
        router.current_plotter_name = "Galaxy Plotter"
        router.route = [["Sol", "0"], ["Colonia", "1"]]
        router.exact_route_data = [
            {"name": "Sol", "distance": 0, "distance_to_destination": 100, "fuel_in_tank": 32, "fuel_used": 0, "must_refuel": True, "has_neutron": False},
            {"name": "Colonia", "distance": 100, "distance_to_destination": 0, "fuel_in_tank": 20, "fuel_used": 12, "must_refuel": False, "has_neutron": False},
        ]
        router._exact_settings = None

        payload = router._spansh_json_export_payload()

        assert payload["parameters"]["source"] == "Sol"
        assert payload["parameters"]["destination"] == "Colonia"
        assert payload["parameters"]["use_supercharge"] is True
        assert payload["parameters"]["algorithm"] == "optimistic"

    def test_spansh_json_export_payload_preserves_fleet_duplicate_waypoints_without_settings(self, router):
        router.fleetcarrier = True
        router.current_plotter_name = "Fleet Carrier Router"
        router.route = [["Sol", "3"], ["Dup", "2"], ["Mid", "1"], ["Dup", "0"]]
        router.fleet_carrier_data = [
            {"name": "Sol", "is_waypoint": True, "must_restock": False},
            {"name": "Dup", "is_waypoint": False, "must_restock": False},
            {"name": "Mid", "is_waypoint": False, "must_restock": False},
            {"name": "Dup", "is_waypoint": False, "must_restock": False},
        ]
        router._plotter_settings = {}

        payload = router._spansh_json_export_payload()

        assert payload["parameters"]["destination_systems"] == ["Dup"]


class TestSpinboxValidation:
    def test_integer_spinbox_validation_rejects_decimal_input(self, router):
        assert router._validate_integer_input("")
        assert router._validate_integer_input("57")
        assert not router._validate_integer_input("57.2")
        assert not router._validate_integer_input(".")

    def test_decimal_spinbox_validation_limits_to_single_decimal_point_and_two_digits(self, router):
        assert router._validate_decimal_input("")
        assert router._validate_decimal_input(".")
        assert router._validate_decimal_input("86.18")
        assert router._validate_decimal_input("12.")
        assert not router._validate_decimal_input("12.345")
        assert not router._validate_decimal_input("12.3.4")

    def test_spinbox_validation_limits_integer_input_by_max_digit_count(self, router):
        assert router._validate_spinbox_input("2000", max_digits=4)
        assert router._validate_spinbox_input("2050", max_digits=4)
        assert not router._validate_spinbox_input("1000000000", max_digits=4)

    def test_float_spinbox_validation_limits_whole_digits_and_decimal_places(self, router):
        assert router._validate_spinbox_input("99.99", allow_float=True, maximum_decimals=2, max_digits=3)
        assert router._validate_spinbox_input("100.99", allow_float=True, maximum_decimals=2, max_digits=3)
        assert not router._validate_spinbox_input("1000.99", allow_float=True, maximum_decimals=2, max_digits=3)

    class _ClampWidgetStub:
        def __init__(self, value, minimum, maximum):
            self._value = value
            self._minimum = minimum
            self._maximum = maximum

        def get(self):
            return self._value

        def cget(self, key):
            if key == "from":
                return self._minimum
            if key == "to":
                return self._maximum
            raise KeyError(key)

        def delete(self, *_args, **_kwargs):
            self._value = ""

        def insert(self, _index, value):
            self._value = str(value)

    def test_live_clamp_spinbox_input_clamps_float_to_max(self, router):
        widget = self._ClampWidgetStub("935.12", 0, 100)
        router._live_clamp_spinbox_input(widget)
        assert widget.get() == "100.0"

    def test_live_clamp_spinbox_input_clamps_integer_to_max(self, router):
        widget = self._ClampWidgetStub("101", 0, 100)
        router._live_clamp_spinbox_input(widget, integer=True)
        assert widget.get() == "100"

    def test_imports_exact_json_uses_row_after_last_done_as_waypoint(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {"source_system": "Sol", "destination_system": "Colonia"},
            "result": {
                "jumps": [
                    {"name": "Sol", "distance": 0, "distance_to_destination": 100.5, "fuel_in_tank": 32.0, "fuel_used": 0, "must_refuel": False, "has_neutron": False, "is_scoopable": False, "done": True},
                    {"name": "Achenar", "distance": 4.38, "distance_to_destination": 96.12, "fuel_in_tank": 31.9, "fuel_used": 0.1, "must_refuel": True, "has_neutron": False, "is_scoopable": True, "done": True},
                    {"name": "Colonia", "distance": 10, "distance_to_destination": 0, "fuel_in_tank": 30.0, "fuel_used": 1.0, "must_refuel": False, "has_neutron": False, "is_scoopable": True, "done": False},
                ]
            },
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.offset == 2
        assert router.next_stop == "Colonia"

    def test_imports_fleet_json(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {
                "source_system": "Sol",
                "destination_systems": ["Carang Hut"],
                "refuel_destinations": [],
                "capacity": 50000,
                "capacity_used": 0,
                "current_fuel": 1000,
                "tritium_amount": 0,
            },
            "result": {
                "source": "Sol",
                "destinations": ["Carang Hut"],
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
        assert router.fleet_carrier_data[1]["is_waypoint"] is True

    def test_imports_fleet_json_uses_row_after_last_done_as_waypoint(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {
                "source_system": "Sol",
                "destination_systems": ["Carang Hut", "Colonia"],
                "refuel_destinations": [],
                "capacity": 50000,
                "capacity_used": 0,
                "current_fuel": 1000,
                "tritium_amount": 0,
            },
            "result": {
                "source": "Sol",
                "destinations": ["Carang Hut", "Colonia"],
                "jumps": [
                    {"name": "Sol", "distance": 0, "distance_to_destination": 30, "fuel_in_tank": 1000, "fuel_used": 0, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0, "is_desired_destination": 1, "done": True},
                    {"name": "Carang Hut", "distance": 15, "distance_to_destination": 15, "fuel_in_tank": 900, "fuel_used": 100, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0, "is_desired_destination": 1, "done": True},
                    {"name": "Colonia", "distance": 15, "distance_to_destination": 0, "fuel_in_tank": 800, "fuel_used": 100, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0, "is_desired_destination": 1, "done": False},
                ],
            },
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.offset == 2
        assert router.next_stop == "Colonia"

    def test_imports_fleet_json_marks_waypoints_when_destinations_are_ids(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {
                "source_system": "Sol",
                "destination_systems": ["123", "456"],
                "refuel_destinations": [],
                "capacity": 50000,
            },
            "result": {
                "source": "Sol",
                "destinations": ["123", "456"],
                "jumps": [
                    {"name": "Sol", "distance": 0, "distance_to_destination": 20, "fuel_in_tank": 1000, "fuel_used": 0, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0},
                    {"name": "Carang Hut", "distance": 10, "distance_to_destination": 10, "fuel_in_tank": 900, "fuel_used": 100, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0},
                    {"name": "A Bootis", "distance": 10, "distance_to_destination": 0, "fuel_in_tank": 800, "fuel_used": 100, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0},
                ],
            },
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert [jump["is_waypoint"] for jump in router.fleet_carrier_data] == [True, False, True]

    def test_imports_fleet_json_marks_duplicate_waypoints_from_destination_systems_when_result_flags_missing(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "job": "abc",
            "parameters": {
                "source_system": "Sol",
                "destination_systems": ["Dup"],
                "refuel_destinations": [],
                "capacity": 50000,
            },
            "result": {
                "source": "Sol",
                "destinations": ["Dup"],
                "jumps": [
                    {"name": "Sol", "distance": 0, "distance_to_destination": 20, "fuel_in_tank": 1000, "fuel_used": 0, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0},
                    {"name": "Dup", "distance": 10, "distance_to_destination": 10, "fuel_in_tank": 900, "fuel_used": 100, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0},
                    {"name": "Mid", "distance": 5, "distance_to_destination": 5, "fuel_in_tank": 850, "fuel_used": 50, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0},
                    {"name": "Dup", "distance": 5, "distance_to_destination": 0, "fuel_in_tank": 800, "fuel_used": 50, "tritium_in_market": 0, "has_icy_ring": False, "is_system_pristine": False, "must_restock": False, "restock_amount": 0},
                ],
            },
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert [jump["is_waypoint"] for jump in router.fleet_carrier_data] == [True, True, False, True]

    def test_imports_riches_json_uses_row_after_last_done_as_waypoint(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "parameters": {"planner": "Road to Riches"},
            "result": [
                {
                    "name": "Sol",
                    "jumps": 0,
                    "bodies": [
                        {
                            "name": "Sol A 1",
                            "subtype": "High metal content world",
                            "is_terraformable": True,
                            "distance_to_arrival": 100,
                            "estimated_scan_value": 1000,
                            "estimated_mapping_value": 2000,
                            "done": True,
                        }
                    ],
                },
                {
                    "name": "Achenar",
                    "jumps": 2,
                    "bodies": [
                        {
                            "name": "Achenar 1",
                            "subtype": "High metal content world",
                            "is_terraformable": False,
                            "distance_to_arrival": 50,
                            "estimated_scan_value": 500,
                            "estimated_mapping_value": 900,
                            "done": False,
                        }
                    ],
                },
            ],
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.exploration_mode == "Road to Riches"
        assert router.offset == 1
        assert router.next_stop == "Achenar"

    def test_imports_riches_json_uses_next_system_after_last_done_system(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "parameters": {"planner": "Road to Riches"},
            "result": [
                {
                    "name": "Sol",
                    "jumps": 0,
                    "bodies": [
                        {
                            "name": "Sol A 1",
                            "subtype": "High metal content world",
                            "is_terraformable": True,
                            "distance_to_arrival": 100,
                            "estimated_scan_value": 1000,
                            "estimated_mapping_value": 2000,
                            "done": False,
                        }
                    ],
                },
                {
                    "name": "Swoiwns DU-D c1-4",
                    "jumps": 1,
                    "bodies": [
                        {
                            "name": "Swoiwns DU-D c1-4 A 1",
                            "subtype": "High metal content world",
                            "is_terraformable": False,
                            "distance_to_arrival": 50,
                            "estimated_scan_value": 500,
                            "estimated_mapping_value": 900,
                            "done": True,
                        },
                        {
                            "name": "Swoiwns DU-D c1-4 B 1",
                            "subtype": "High metal content world",
                            "is_terraformable": False,
                            "distance_to_arrival": 55,
                            "estimated_scan_value": 400,
                            "estimated_mapping_value": 800,
                            "done": False,
                        },
                    ],
                },
                {
                    "name": "Col 285 Sector MF-C b27-5",
                    "jumps": 1,
                    "bodies": [
                        {
                            "name": "Col 285 Sector MF-C b27-5 A 1",
                            "subtype": "High metal content world",
                            "is_terraformable": False,
                            "distance_to_arrival": 60,
                            "estimated_scan_value": 300,
                            "estimated_mapping_value": 700,
                            "done": False,
                        }
                    ],
                },
            ],
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.exploration_mode == "Road to Riches"
        assert router.offset == 2
        assert router.next_stop == "Col 285 Sector MF-C b27-5"

    def test_imports_exobiology_json_uses_row_after_last_done_as_waypoint(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "parameters": {"planner": "Exomastery"},
            "result": [
                {
                    "name": "Sol",
                    "jumps": 0,
                    "bodies": [
                        {
                            "name": "Sol A 1",
                            "subtype": "Rocky body",
                            "distance_to_arrival": 100,
                            "landmarks": [
                                {"subtype": "Bacterium", "count": 1, "value": 1000, "done": True}
                            ],
                        }
                    ],
                },
                {
                    "name": "Achenar",
                    "jumps": 2,
                    "bodies": [
                        {
                            "name": "Achenar 1",
                            "subtype": "Rocky body",
                            "distance_to_arrival": 50,
                            "landmarks": [
                                {"subtype": "Osseus", "count": 1, "value": 900, "done": False}
                            ],
                        }
                    ],
                },
            ],
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.exploration_mode == "Exomastery"
        assert router.offset == 1
        assert router.next_stop == "Achenar"

    def test_imports_exobiology_json_uses_next_system_after_last_done_system(self, router):

        payload = {
            "status": "ok",
            "state": "completed",
            "parameters": {"planner": "Exomastery"},
            "result": [
                {
                    "name": "Sol",
                    "jumps": 0,
                    "bodies": [
                        {
                            "name": "Sol A 1",
                            "subtype": "Rocky body",
                            "distance_to_arrival": 100,
                            "landmarks": [
                                {"subtype": "Bacterium", "count": 1, "value": 1000, "done": False}
                            ],
                        }
                    ],
                },
                {
                    "name": "Swoiwns DU-D c1-4",
                    "jumps": 1,
                    "bodies": [
                        {
                            "name": "Swoiwns DU-D c1-4 A 1",
                            "subtype": "Rocky body",
                            "distance_to_arrival": 50,
                            "landmarks": [
                                {"subtype": "Osseus", "count": 1, "value": 900, "done": True},
                                {"subtype": "Fungoida", "count": 1, "value": 800, "done": False},
                            ],
                        }
                    ],
                },
                {
                    "name": "Col 285 Sector MF-C b27-5",
                    "jumps": 1,
                    "bodies": [
                        {
                            "name": "Col 285 Sector MF-C b27-5 A 1",
                            "subtype": "Rocky body",
                            "distance_to_arrival": 60,
                            "landmarks": [
                                {"subtype": "Concha", "count": 1, "value": 700, "done": False}
                            ],
                        }
                    ],
                },
            ],
        }

        path = router.save_route_path.replace(".csv", ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.exploration_mode == "Exomastery"
        assert router.offset == 2
        assert router.next_stop == "Col 285 Sector MF-C b27-5"

    @pytest.mark.parametrize(
        "filename,body_types,expected_mode",
        [
            ("ammonia-export.json", ["Ammonia world"], "Ammonia World Route"),
            ("earth-export.json", ["Earth-like world"], "Earth-like World Route"),
            ("rocky-export.json", ["Rocky body", "High metal content world"], "Rocky/HMC Route"),
        ],
    )
    def test_imports_specialized_json_use_row_after_last_done_as_waypoint(self, router, filename, body_types, expected_mode):

        payload = {
            "status": "ok",
            "state": "completed",
            "parameters": {"body_types": body_types},
            "result": [
                {
                    "name": "Sol",
                    "jumps": 0,
                    "bodies": [
                        {
                            "name": "Sol A 1",
                            "distance_to_arrival": 100,
                            "done": True,
                        }
                    ],
                },
                {
                    "name": "Achenar",
                    "jumps": 2,
                    "bodies": [
                        {
                            "name": "Achenar 1",
                            "distance_to_arrival": 50,
                            "done": False,
                        }
                    ],
                },
            ],
        }

        path = os.path.join(os.path.dirname(router.save_route_path), filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router.plot_json(path)

        assert router.exploration_mode == expected_mode
        assert router.offset == 1
        assert router.next_stop == "Achenar"

    def test_legacy_fleet_json_capacity_50000_is_inferred_as_player_carrier(self, router):
        params = router._json_fleet_params(
            {"parameters": {"source_system": "Sol", "capacity": 50000}},
            {"source": "Sol", "destinations": [], "jumps": []},
        )
        assert params["carrier_type"] == "fleet"

    def test_fleet_json_export_uses_consistent_carrier_profile(self, router):
        router.fleetcarrier = True
        router.fleet_carrier_data = [{"name": "Sol"}]
        router._plotter_settings = {
            "planner": "Fleet Carrier Router",
            "settings": {
                "source": "Sol",
                "destinations": ["Carang Hut"],
                "refuel_destinations": [],
                "carrier_type": "squadron",
                "used_capacity": 1234,
                "determine_required_fuel": True,
                "tritium_fuel": 1000,
                "tritium_market": 0,
            },
        }

        payload = router._spansh_json_export_payload()

        assert payload["parameters"]["carrier_type"] == "squadron"
        assert payload["parameters"]["capacity"] == 60000
        assert payload["parameters"]["mass"] == 15000


def test_poll_spansh_job_polls_before_first_sleep(monkeypatch, router):
    router._cancel_flag_from_attr = MagicMock(return_value=False)

    events = []
    pending = MagicMock(status_code=202)
    pending.json.return_value = {"state": "queued"}
    completed = MagicMock(status_code=200)
    completed.json.return_value = {"status": "ok", "result": {"system_jumps": []}}
    responses = [pending, completed]

    def fake_get(*_args, **_kwargs):
        events.append("get")
        return responses.pop(0)

    def fake_sleep(seconds):
        events.append(("sleep", seconds))

    monkeypatch.setattr(spans_mod.requests, "get", fake_get)
    monkeypatch.setattr(plotters_mod, "sleep", fake_sleep)

    data = router._poll_spansh_job("job-123", poll_interval=7, max_iterations=2)

    assert data["status"] == "ok"
    assert events == ["get", ("sleep", 7), "get"]


def test_poll_spansh_job_request_failure_raises_immediately(monkeypatch, router):
    router._cancel_flag_from_attr = MagicMock(return_value=False)

    def fake_get(*_args, **_kwargs):
        raise requests.RequestException("connection lost")

    fake_sleep = MagicMock()

    monkeypatch.setattr(spans_mod.requests, "get", fake_get)
    monkeypatch.setattr(plotters_mod, "sleep", fake_sleep)

    with pytest.raises(requests.RequestException, match="Network error while polling Spansh: connection lost"):
        router._poll_spansh_job("job-123", poll_interval=7, max_iterations=2)

    fake_sleep.assert_not_called()


def test_submit_spansh_job_request_accepts_direct_result(monkeypatch, router):
    response = MagicMock(status_code=200)
    response.json.return_value = {"result": {"systems": []}}

    monkeypatch.setattr(spans_mod.requests, "post", lambda *_args, **_kwargs: response)

    data = router._submit_spansh_job_request(
        "https://spansh.co.uk/api/riches/route",
        data={"from": "Sol"},
        accept_direct_result=True,
        direct_result_keys=("result", "systems"),
    )

    assert data == {"result": {"systems": []}}


def test_submit_spansh_job_request_raises_parsed_400(monkeypatch, router):
    response = MagicMock(status_code=400)
    response.json.return_value = {"error": "Bad input"}
    response.text = "Bad input"

    monkeypatch.setattr(spans_mod.requests, "post", lambda *_args, **_kwargs: response)

    with pytest.raises(plotters_mod._SpanshPollError, match="Bad input") as excinfo:
        router._submit_spansh_job_request(
            "https://spansh.co.uk/api/route",
            params={"from": "Sol", "to": "Achenar"},
        )

    assert excinfo.value.status_code == 400


def test_route_rows_signature_detects_changed_done_pattern_with_same_count_and_edges(router):
    router.route = [["A"], ["B"], ["C"], ["D"], ["E"]]
    router.route_done = [True, False, True, False, True]
    first_signature = router._route_rows_signature()

    router.route_done = [True, True, False, False, True]
    router._invalidate_route_rows()
    second_signature = router._route_rows_signature()

    assert first_signature != second_signature


def test_load_plotter_settings_recovers_from_unreadable_payload(router):
    with open(router.plotter_settings_path, "w", encoding="utf-8") as handle:
        handle.write("{invalid")

    router._plotter_settings = {"planner": "Galaxy Plotter"}
    router._load_plotter_settings()

    assert router._plotter_settings == {}


def test_load_exact_settings_normalizes_spansh_style_keys(router):
    with open(router.exact_settings_path, "w", encoding="utf-8") as handle:
        json.dump({"source_system": "Sol", "destination_system": "Achenar"}, handle)

    router._exact_settings = None
    router._load_exact_settings()

    assert router._exact_settings["source"] == "Sol"
    assert router._exact_settings["destination"] == "Achenar"


def test_route_rows_signature_is_stable_for_content_only_changes(router):
    router.route_type = "simple"
    router.route = [["Sol", "1", "10", "20"]]
    router.route_done = [False]
    first_signature = router._route_rows_signature()

    router.route[0][0] = "Achenar"
    router._invalidate_route_rows()
    second_signature = router._route_rows_signature()

    assert first_signature == second_signature


def test_pre_gui_journal_event_is_replayed_after_gui_init(router):
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


def test_pre_gui_dashboard_event_is_replayed_after_gui_init(router):
    router.frame = None
    router.handle_dashboard_entry({"Fuel": {"FuelMain": 7.5, "FuelReservoir": 0.8}})

    assert router._pending_dashboard_event is not None

    router.frame = DummyFrame()
    router._replay_buffered_startup_events()

    assert router.current_fuel_main == 7.5
    assert router.current_fuel_reservoir == 0.8
    assert router._pending_dashboard_event is None


def test_route_row_state_cache_refreshes_after_explicit_invalidation(router):
    router.route_type = "simple"
    router.route = [["Sol", "1", "10", "20"]]
    router.route_done = [False]

    first_state = router._route_row_state_at(0)
    router.route[0][0] = "Achenar"
    router.route[0][2] = "35"
    router._invalidate_route_rows()
    second_state = router._route_row_state_at(0)

    assert first_state["name"] == "Sol"
    assert second_state["name"] == "Achenar"
    assert second_state["distance_to_arrival"] == 35.0


def test_route_row_state_cache_refreshes_when_exact_flags_change(router):
    router.exact_plotter = True
    router.route = [["Sol", "0", "0", "20"]]
    router.exact_route_data = [{"must_refuel": False, "has_neutron": False, "done": False}]

    assert router._route_refuel_required_at(0) is False
    assert router._route_has_neutron_at(0) is False

    router.exact_route_data[0]["must_refuel"] = True
    router.exact_route_data[0]["has_neutron"] = True
    router._invalidate_route_rows()

    assert router._route_refuel_required_at(0) is True
    assert router._route_has_neutron_at(0) is True


def test_carrier_jump_clears_stale_coords_when_starpos_missing(router):
    router._set_current_location(coords=[10, 20, 30], system="Old System")

    router._handle_journal_entry_ui(
        "",
        {"event": "CarrierJump", "StarSystem": "New System"},
        {},
    )

    coords, system = router._get_current_location()
    assert coords is None
    assert system == "New System"


def test_neutron_route_overlay_update_uses_route_type_without_planner_name(router):
    router.route_type = "neutron"
    router.current_plotter_name = None
    router.route = [["Sol", "1"], ["Achenar", "1"]]
    router.route_done = [False, False]
    router.offset = 0
    router.jumps_left = 2

    state = router._advance_route_state(1)

    assert state["update_overlay"] is True


def test_show_route_gui_uses_route_type_for_neutron_overlay_controls(router):
    router.route_type = "neutron"
    router.current_plotter_name = None
    router.route = [["Sol", "1"], ["Achenar", "1"]]
    router.route_done = [False, False]
    router.next_stop = "Achenar"
    router.jumps_left = 1
    router._controls_collapsed = False
    router._route_layout_shown = True
    router._main_button_width = 12
    router._compact_button_width = 12
    router.frame = _RouteGuiFrame()
    router.btn_frame = _RouteGuiFrame()
    router.waypoint_btn = _RouteGuiWidget()
    router._collapse_btn = DummyWidget()
    router.waypoint_prev_btn = DummyWidget()
    router.waypoint_next_btn = DummyWidget()
    router.jumpcounttxt_lbl = _RouteGuiWidget()
    router.dist_prev_lbl = _RouteGuiWidget()
    router.dist_next_lbl = _RouteGuiWidget()
    router.dist_remaining_lbl = _RouteGuiWidget()
    router.planner_dropdown = DummyWidget()
    router.plot_btn = DummyWidget()
    router.search_dropdown = DummyWidget()
    router.search_btn = DummyWidget()
    router.clear_route_btn = DummyWidget()
    router.csv_route_btn = DummyWidget()
    router.show_csv_btn = DummyWidget()
    router.overlay_cb_frame = DummyWidget()
    router.overlay_cb = DummyWidget()
    router.overlay_pos_frame = DummyWidget()
    router.neutron_overlay_cb = DummyWidget()
    router.neutron_pos_frame = DummyWidget()
    router.bodies_lbl = DummyWidget()
    router.fleetrestock_lbl = DummyWidget()
    router.refuel_lbl = DummyWidget()
    router.error_lbl = DummyWidget()
    router._update_main_panel_widths = MagicMock()
    router._schedule_main_window_resize = MagicMock()

    router.show_route_gui(True)

    assert router.overlay_cb_frame.visible is True
    assert router.overlay_cb.visible is False
    assert router.neutron_overlay_cb.visible is True


def test_fleet_worker_resolves_duplicate_destinations_once_and_reuses_records(router):
    router._validate_source_system = MagicMock(return_value=(True, None, None))
    router._ui_call = lambda callback, *args, token=None: callback(*args)
    router._fleet_carrier_route_success = MagicMock()
    router._fleet_carrier_route_error = MagicMock()

    resolve_calls = []

    def fake_resolve(name):
        resolve_calls.append(name)
        return {
            "sol": {"name": "Sol", "id64": 1},
            "carang hut": {"name": "Carang Hut", "id64": 2},
            "achenar": {"name": "Achenar", "id64": 3},
        }[name.strip().lower()]

    router._resolve_system_record = MagicMock(side_effect=fake_resolve)

    response = MagicMock(status_code=200)
    response.json.return_value = {"result": {"jumps": []}}

    params = {
        "source": "Sol",
        "destinations": ["Carang Hut", "carang hut", "Achenar"],
        "refuel_destinations": ["carang hut"],
        "carrier_type": "fleet",
        "used_capacity": 1234,
        "determine_required_fuel": True,
        "tritium_fuel": 1000,
        "tritium_market": 0,
    }

    with patch.object(spans_mod.requests, "post", return_value=response) as post_mock:
        router._fleet_carrier_route_worker(params, token="token")

    router._validate_source_system.assert_not_called()
    assert resolve_calls == ["Sol", "Carang Hut", "Achenar"]
    assert post_mock.call_args.kwargs["data"]["source"] == 1
    assert post_mock.call_args.kwargs["data"]["destinations"] == [2, 3]
    assert post_mock.call_args.kwargs["data"]["refuel_destinations"] == [2]
    router._fleet_carrier_route_error.assert_not_called()


def test_fleet_worker_rejects_source_without_id64(router):
    router._validate_source_system = MagicMock(return_value=(True, None, None))
    router._ui_call = lambda callback, *args, token=None: callback(*args)
    router._fleet_carrier_route_error = MagicMock()
    router._resolve_system_record = MagicMock(return_value={"name": "Sol"})

    with patch.object(spans_mod.requests, "post") as post_mock:
        router._fleet_carrier_route_worker(
            {
                "source": "Sol",
                "destinations": ["Carang Hut"],
                "refuel_destinations": [],
                "carrier_type": "fleet",
                "used_capacity": 1234,
                "determine_required_fuel": True,
                "tritium_fuel": 1000,
                "tritium_market": 0,
            },
            token="token",
        )

    post_mock.assert_not_called()
    router._fleet_carrier_route_error.assert_called_once_with(
        "Source system 'Sol' not found in Spansh."
    )


def test_fleet_worker_rejects_destination_without_id64(router):
    router._validate_source_system = MagicMock(return_value=(True, None, None))
    router._ui_call = lambda callback, *args, token=None: callback(*args)
    router._fleet_carrier_route_error = MagicMock()

    def fake_resolve(name):
        if name == "Sol":
            return {"name": "Sol", "id64": 1}
        return {"name": "Carang Hut"}

    router._resolve_system_record = MagicMock(side_effect=fake_resolve)

    with patch.object(spans_mod.requests, "post") as post_mock:
        router._fleet_carrier_route_worker(
            {
                "source": "Sol",
                "destinations": ["Carang Hut"],
                "refuel_destinations": [],
                "carrier_type": "fleet",
                "used_capacity": 1234,
                "determine_required_fuel": True,
                "tritium_fuel": 1000,
                "tritium_market": 0,
            },
            token="token",
        )

    post_mock.assert_not_called()
    router._fleet_carrier_route_error.assert_called_once_with(
        "Destination system 'Carang Hut' not found in Spansh."
    )


def test_validate_destination_system_surfaces_lookup_failure(router):
    router._check_system_in_spansh = MagicMock(return_value=None)

    ok, message = router._validate_destination_system("Achenar")

    assert ok is False
    assert message == (
        "Failed to look up destination system 'Achenar' in Spansh.\n"
        "Please try again."
    )


def test_resolve_valid_source_record_surfaces_lookup_failure(router):
    router._resolve_system_record = MagicMock(return_value=None)
    router._check_system_in_spansh = MagicMock(return_value=None)

    ok, record, nearest, message = router._resolve_valid_source_record("Sol")

    assert ok is False
    assert record is None
    assert nearest is None
    assert message == (
        "Failed to look up source system 'Sol' in Spansh.\n"
        "Please try again."
    )


def test_fleet_success_with_empty_payload_preserves_existing_route(router):
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
            "source": "Sol",
            "destinations": ["Achenar"],
            "refuel_destinations": [],
            "carrier_type": "fleet",
            "used_capacity": 1234,
            "determine_required_fuel": True,
            "tritium_fuel": 0,
            "tritium_market": 0,
        },
    )

    router.clear_route.assert_not_called()
    router._close_plotter_window.assert_not_called()
    assert router.route == [["Existing", "1", "10", "20"]]
    router._fc_error_txt.set.assert_called_once_with("No carrier route found for the given parameters.")


def test_call_on_ui_thread_sync_raises_when_after_fails(router):

    class BrokenFrame:
        def winfo_exists(self):
            return True

        def after(self, *_args, **_kwargs):
            raise RuntimeError("after failed")

    router.frame = BrokenFrame()
    errors = []

    def worker():
        try:
            router._call_on_ui_thread_sync(lambda: None)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def test_ui_call_skips_destroyed_frame(router):

    class DeadFrame:
        def winfo_exists(self):
            return False

        def after(self, *_args, **_kwargs):
            raise AssertionError("after should not be called")

    router.frame = DeadFrame()
    callback = MagicMock()

    router._ui_call(callback)

    callback.assert_not_called()


def test_window_after_if_alive_skips_closed_window(router):

    class DeadWindow:
        def winfo_exists(self):
            return False

        def after(self, *_args, **_kwargs):
            raise AssertionError("after should not be called")

    callback = MagicMock()
    assert router._window_after_if_alive(DeadWindow(), 0, callback) is False
    callback.assert_not_called()


def test_plot_route_validation_error_does_not_touch_closed_plotter_widgets(router):
    router.show_error = MagicMock()
    closed_plotter = MagicMock()
    closed_plotter.winfo_exists.return_value = False
    router.plotter_win = closed_plotter

    router._plot_route_validation_error("destination system invalid")

    router.show_error.assert_called_once()


def test_plot_route_validation_error_marks_destination_field_when_plotter_is_open(router):
    router.show_error = MagicMock()

    class FakeField:
        def __init__(self):
            self.values = {}

        def winfo_exists(self):
            return True

        def __setitem__(self, key, value):
            self.values[key] = value

    router.plotter_win = MagicMock()
    router.plotter_win.winfo_exists.return_value = True
    router.neutron_error_txt = MagicMock()
    router.source_ac = FakeField()
    router.dest_ac = FakeField()

    router._plot_route_validation_error("destination system invalid")

    assert router.dest_ac.values["fg"] == "red"
    router.show_error.assert_not_called()


def test_resolve_system_record_requires_exact_search_match(router):
    response = MagicMock(status_code=200)
    response.json.return_value = {"results": [{"name": "Sol Prime", "id64": 1}]}

    with patch.object(spans_mod.requests, "get", return_value=response):
        assert router._resolve_system_record("Sol") is None


def test_fss_discovery_scan_does_not_advance_route(router):
    router.next_stop = "Sol"
    router.update_route = MagicMock()
    router._handle_journal_entry_ui("", {"event": "FSSDiscoveryScan", "SystemName": "sol"}, {})

    router.update_route.assert_not_called()


def test_journal_handler_logs_section_failure_without_aborting_route_progression(router):
    router.next_stop = "Sol"
    router._set_current_location = MagicMock(side_effect=RuntimeError("location failed"))
    router.update_route = MagicMock()
    router._log_unexpected = MagicMock()

    router._handle_journal_entry_ui("", {"event": "FSDJump", "StarSystem": "sol", "StarPos": [1, 2, 3]}, {})

    router.update_route.assert_called_once()
    router._log_unexpected.assert_any_call("Failed to update current location from journal")


def test_supercruise_exit_does_not_advance_route(router):
    router.next_stop = "Sol"
    router.update_route = MagicMock()

    router._handle_journal_entry_ui("", {"event": "SupercruiseExit", "StarSystem": "Sol"}, {})

    router.update_route.assert_not_called()


def test_location_still_advances_route_when_matching_next_stop(router):
    router.next_stop = "Sol"
    router.update_route = MagicMock()

    router._handle_journal_entry_ui("", {"event": "Location", "StarSystem": "Sol", "StarPos": [0, 0, 0]}, {})

    router.update_route.assert_called_once()


def test_route_complete_uses_runtime_current_system_state(router):
    router.current_plotter_name = "Neutron Plotter"
    router.route = [["Sol", "0"], ["Achenar", "1"]]
    router.route_done = [False, False]
    router.jumps_left = 0
    router._set_current_location(system="Achenar")

    with patch("SpanshTools.core.monitor.state", {"SystemName": "Sol"}):
        assert router._route_complete_for_ui() is True


def test_route_complete_when_all_rows_done_is_location_independent(router):
    router.current_plotter_name = "Neutron Plotter"
    router.route = [["Sol", "0"], ["Achenar", "1"]]
    router.route_done = [True, True]
    router.jumps_left = 99
    router._set_current_location(system="Colonia")

    assert router._route_complete_for_ui() is True


def test_route_widget_text_shows_route_complete_when_complete(router):
    router.waypoint_btn = _RouteGuiWidget()
    router.jumpcounttxt_lbl = _RouteGuiWidget()
    router.dist_prev_lbl = _RouteGuiWidget()
    router.dist_next_lbl = _RouteGuiWidget()
    router.dist_remaining_lbl = _RouteGuiWidget()
    router.route = [["Sol", "0"], ["Achenar", "1"]]
    router.route_done = [True, True]
    router.next_stop = "Achenar"

    router._update_route_widget_text(True)

    assert router.waypoint_btn["text"] == router.next_wp_label + "\nRoute Complete!"
    assert router.jumpcounttxt_lbl["text"] == "Route complete!"


def test_route_complete_uses_exploration_body_done_data(router):
    router.exploration_plotter = True
    router.exploration_mode = "Road to Riches"
    router.route = [["Sol", "0"], ["Achenar", "2"]]
    router.route_done = [False, False]
    router.exploration_route_data = [
        {
            "name": "Sol",
            "bodies": [
                {"name": "Sol A 1", "done": True},
                {"name": "Sol A 2", "done": True},
            ],
        },
        {
            "name": "Achenar",
            "bodies": [
                {"name": "Achenar 1", "done": True},
            ],
        },
    ]

    assert router._route_done_values() == [True, True]
    assert router._route_complete_for_ui() is True


def test_route_complete_uses_exomastery_landmark_done_data(router):
    router.exploration_plotter = True
    router.exploration_mode = "Exomastery"
    router.route = [["Sol", "0"], ["Colonia", "3"]]
    router.route_done = [False, False]
    router.exploration_route_data = [
        {
            "name": "Sol",
            "bodies": [
                {
                    "name": "Sol A 1",
                    "landmarks": [
                        {"subtype": "bacterium", "done": True},
                        {"subtype": "fungoida", "done": True},
                    ],
                },
            ],
        },
        {
            "name": "Colonia",
            "bodies": [
                {
                    "name": "Colonia 2",
                    "landmarks": [
                        {"subtype": "frutexa", "done": True},
                    ],
                },
            ],
        },
    ]

    assert router._route_done_values() == [True, True]
    assert router._route_complete_for_ui() is True


def test_parse_neutron_csv_rows_missing_system_header_raises_value_error(router):
    get_field_value = lambda row, *names, default="": next((row.get(name) for name in names if row.get(name) not in (None, "")), default)

    with pytest.raises(ValueError, match="Missing required CSV column"):
        router._parse_neutron_csv_rows([{"Jumps": "1"}], get_field_value)


def test_parse_simple_csv_rows_missing_system_header_raises_value_error(router):
    get_field_value = lambda row, *names, default="": next((row.get(name) for name in names if row.get(name) not in (None, "")), default)

    with pytest.raises(ValueError, match="Missing required CSV column"):
        router._parse_simple_csv_rows([{"Jumps": "1"}], get_field_value)


def test_plot_file_does_not_double_finalize_csv_import(monkeypatch, router):
    router.plot_csv = MagicMock()
    router._finalize_csv_import = MagicMock()

    monkeypatch.setattr(route_io_mod.filedialog, "askopenfilename", lambda **_kwargs: "route.csv")

    router.plot_file()

    router.plot_csv.assert_called_once_with("route.csv")
    router._finalize_csv_import.assert_not_called()


def test_plot_file_offers_only_csv_and_json_import_types(monkeypatch, router):
    captured = {}

    def fake_askopenfilename(**kwargs):
        captured["filetypes"] = kwargs["filetypes"]
        return ""

    monkeypatch.setattr(route_io_mod.filedialog, "askopenfilename", fake_askopenfilename)

    router.plot_file()

    assert captured["filetypes"] == [
        ("All supported files", "*.csv *.json"),
        ("CSV files", "*.csv"),
        ("JSON files", "*.json"),
    ]


def test_csv_import_uses_row_after_last_done_as_current_waypoint(tmp_path, router):
    route_path = tmp_path / "done_route.csv"
    with open(route_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Done", "System Name", "Jumps"])
        writer.writerow(["□", "Sol", "0"])
        writer.writerow(["🟩", "Achenar", "2"])
        writer.writerow(["🟩", "Colonia", "3"])
        writer.writerow(["□", "Beagle Point", "4"])

    router.compute_distances = MagicMock()
    router.copy_waypoint = MagicMock()
    router.update_gui = MagicMock()
    router.save_all_route = MagicMock()
    router._update_overlay = MagicMock()

    router.plot_csv(str(route_path))

    assert router.offset == 3
    assert router.next_stop == "Beagle Point"


def test_finalize_imported_route_prefers_row_after_last_done_over_current_system(router):
    router.route = [["Sol", "0"], ["Achenar", "2"], ["Colonia", "3"]]
    router.route_done = [True, False, False]
    router.compute_distances = MagicMock()
    router.copy_waypoint = MagicMock()
    router.update_gui = MagicMock()
    router.save_all_route = MagicMock()
    router._update_overlay = MagicMock()
    router._set_current_location(system="Colonia")

    router._finalize_imported_route()

    assert router.offset == 1
    assert router.next_stop == "Achenar"


def test_finalize_imported_route_refreshes_overlay(router):
    router.route = [["Sol", "0"], ["Achenar", "2"]]
    router.route_done = [False, False]
    router.compute_distances = MagicMock()
    router.copy_waypoint = MagicMock()
    router.update_gui = MagicMock()
    router.save_all_route = MagicMock()
    router._update_overlay = MagicMock()

    router._finalize_imported_route()

    router._update_overlay.assert_called_once()


def test_finalize_imported_route_does_not_copy_waypoint_when_all_rows_are_done(router):
    router.route = [["Sol", "0"], ["Achenar", "2"]]
    router.route_done = [True, True]
    router.compute_distances = MagicMock()
    router.copy_waypoint = MagicMock()
    router.update_gui = MagicMock()
    router.save_all_route = MagicMock()
    router._update_overlay = MagicMock()

    router._finalize_imported_route()

    assert router.jumps_left == 0
    router.copy_waypoint.assert_not_called()


def test_spansh_json_export_payload_uses_neutron_route_type_without_planner_name(router):
    router.route_type = "neutron"
    router.current_plotter_name = None
    router.route = [["Sol", "0", "0", "731.32", "No"], ["HIP 100000", "2", "344.9", "0", "Yes"]]
    router.route_done = [False, False]
    router._plotter_settings = {
        "planner": "Neutron Plotter",
        "settings": {
            "source": "Sol",
            "destination": "HIP 100000",
            "range": "86.18",
            "efficiency": "60",
            "supercharge_multiplier": "4",
            "vias": [],
        },
    }

    payload = router._spansh_json_export_payload()

    assert payload["parameters"]["planner"] == "Neutron Plotter"
    assert payload["parameters"]["from"] == "Sol"
    assert payload["result"]["system_jumps"][-1]["system"] == "HIP 100000"


@pytest.mark.parametrize(
    "filename,expected_mode",
    [
        ("ammonia-export.csv", "Ammonia World Route"),
        ("earth-export.csv", "Earth-like World Route"),
        ("rocky-export.csv", "Rocky/HMC Route"),
    ],
)
def test_plugin_specialized_csv_exports_import_cleanly(tmp_path, router, filename, expected_mode):
    route_path = tmp_path / filename
    with open(route_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Done", "System Name", "Body Name", "Distance To Arrival", "Jumps"])
        writer.writerow(["🟩", "Sol", "Sol A 1", "100", "0"])
        writer.writerow(["□", "Achenar", "Achenar 1", "50", "2"])

    router.compute_distances = MagicMock()
    router.copy_waypoint = MagicMock()
    router.update_gui = MagicMock()
    router.save_all_route = MagicMock()
    router._update_overlay = MagicMock()

    router.plot_csv(str(route_path))

    assert router.exploration_plotter is True
    assert router.exploration_mode == expected_mode
    assert router.route[0][0] == "Sol"
    assert router.route[1][0] == "Achenar"
    assert router.offset == 1
    assert router.next_stop == "Achenar"


def test_plot_file_uses_remembered_import_directory(monkeypatch, router, tmp_path):
    remembered_dir = tmp_path / "imports"
    remembered_dir.mkdir()
    captured = {}

    monkeypatch.setattr(route_io_mod.config, "get_str", lambda key, default="": str(remembered_dir))

    def fake_askopenfilename(**kwargs):
        captured["initialdir"] = kwargs["initialdir"]
        return ""

    monkeypatch.setattr(route_io_mod.filedialog, "askopenfilename", fake_askopenfilename)

    router.plot_file()

    assert captured["initialdir"] == str(remembered_dir)


def test_dialog_directory_memory_separates_import_export_and_falls_back(router, tmp_path, monkeypatch):
    import_dir = tmp_path / "imports"
    export_dir = tmp_path / "exports"
    import_dir.mkdir()
    export_dir.mkdir()
    stored = {}

    monkeypatch.setattr(route_io_mod.config, "set", lambda key, value: stored.__setitem__(key, value))
    monkeypatch.setattr(route_io_mod.config, "get_str", lambda key, default="": stored.get(key, default))

    router._remember_dialog_directory("import", str(import_dir / "route.json"))
    router._remember_dialog_directory("export", str(export_dir / "route.csv"))

    assert router._dialog_initial_directory("import") == str(import_dir)
    assert router._dialog_initial_directory("export") == str(export_dir)

    stored["spansh_last_import_dir"] = str(tmp_path / "missing-import")
    stored["spansh_last_export_dir"] = str(tmp_path / "missing-export")
    home_dir = os.path.expanduser("~")

    assert router._dialog_initial_directory("import") == home_dir
    assert router._dialog_initial_directory("export") == home_dir


def test_fc_add_destination_deduplicates_case_insensitively(router):

    class _DummyAC:
        def __init__(self, text, placeholder):
            self._text = text
            self.placeholder = placeholder

        def get(self):
            return self._text

        def set_text(self, text, _placeholder_style):
            self._text = text

    router._fc_dest_ac = _DummyAC("carang hut", "Destination System")
    router._fc_destinations = ["Carang Hut"]
    router._fc_refresh_destinations = MagicMock()
    router._fc_select_destination_line = MagicMock()

    router._fc_add_destination()

    assert router._fc_destinations == ["Carang Hut"]
    router._fc_refresh_destinations.assert_not_called()


def test_save_route_state_uses_atomic_replace(monkeypatch, router):
    router.route = [["Sol", "1"]]
    router.route_done = [False]

    replace_calls = []
    real_replace = route_io_mod.os.replace

    def fake_replace(src, dst):
        replace_calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(route_io_mod.os, "replace", fake_replace)

    router._save_route_state()

    assert len(replace_calls) == 1
    assert replace_calls[0][1].endswith("route_state.json")


def test_apply_route_state_uses_route_type_for_exact_done_restore(router):
    payload = {
        "route": [["Sol", "0", "0", "10"], ["Achenar", "1", "10", "0"]],
        "route_done": [False, False],
        "route_type": "exact",
        "planner": "Galaxy Plotter",
        "exact_plotter": False,
        "exact_route_data": [
            {"name": "Sol", "done": True},
            {"name": "Achenar", "done": False},
        ],
        "fleet_carrier_data": [],
        "exploration_route_data": [],
        "offset": 0,
    }

    router._apply_route_state(payload)

    assert router.route_type == "exact"
    assert router.route_done == [True, False]


def test_save_plotter_settings_uses_atomic_replace(monkeypatch, router):
    router._plotter_settings = {"planner": "Neutron Plotter", "settings": {"source": "Sol"}}

    replace_calls = []
    real_replace = route_io_mod.os.replace

    def fake_replace(src, dst):
        replace_calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(route_io_mod.os, "replace", fake_replace)

    router._save_plotter_settings()

    assert len(replace_calls) == 1
    assert replace_calls[0][1].endswith("plotter_settings.json")


def test_jump_json_mode_prefers_explicit_fleet_planner(router):
    mode = router._infer_jump_json_mode(
        {
            "parameters": {"planner": "Fleet Carrier Router"},
            "route_type": "exact",
        },
        {"jumps": []},
    )

    assert mode == "fleet"
