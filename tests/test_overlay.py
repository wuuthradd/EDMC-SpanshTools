"""Tests for overlay detection, toggle, and update logic."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from monitor import monitor
from SpanshTools.constants import FUEL_OVERLAY_ID, NEUTRON_OVERLAY_ID
from SpanshTools.core import SpanshTools
from conftest import create_router




MOCK_ROUTE_DATA = {
    "status": "ok",
    "result": {
        "jumps": [
            {
                "name": "Sol",
                "distance": 0,
                "distance_to_destination": 10.0,
                "must_refuel": False,
                "is_scoopable": False,
            },
            {
                "name": "Alpha Centauri",
                "distance": 4.38,
                "distance_to_destination": 5.62,
                "must_refuel": True,
                "is_scoopable": True,
            },
            {
                "name": "Destination",
                "distance": 5.62,
                "distance_to_destination": 0,
                "must_refuel": False,
                "is_scoopable": False,
            },
        ]
    }
}


class TestOverlayDetection:
    def test_overlay_detected(self, router):
        # conftest.py mocks EDMCOverlay, so overlay should be available
        assert router.overlay is not None

    def test_overlay_initially_disabled(self, router):
        assert router.overlay_var.get() is False


class TestOverlayToggle:
    def test_toggle_on_off(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)

        # Mock the overlay's send_message
        router.overlay = MagicMock()

        # Simulate checkbox checked
        router.overlay_var.set(True)
        router.toggle_overlay()
        assert router.overlay_var.get() is True

        # Simulate checkbox unchecked
        router.overlay_var.set(False)
        router.toggle_overlay()
        assert router.overlay_var.get() is False

    def test_toggle_without_overlay_shows_error(self, router):
        router.overlay = None
        router._exact_plot_success(MOCK_ROUTE_DATA)

        # Should not crash, just show error
        # (show_error needs GUI, so we mock it)
        router.show_error = MagicMock()
        router.overlay_var.set(True)
        router.toggle_overlay()
        router.show_error.assert_called_once()
        assert "EDMCModernOverlay" in router.show_error.call_args[0][0]
        # Checkbox should be reset to unchecked
        assert router.overlay_var.get() is False


class TestOverlayUpdate:
    def test_shows_message_on_refuel_waypoint(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.overlay = MagicMock()
        router.overlay_var.set(True)

        # Offset=2 means player just arrived at index 1 (Alpha Centauri, must_refuel=True)
        router.offset = 2
        router.jumps_left = 1
        router._set_current_location(coords=[0, 0, 0], system="Alpha Centauri")
        router._update_overlay()

        router.overlay.send_message.assert_called_once()
        args = router.overlay.send_message.call_args
        assert args[0][0] == FUEL_OVERLAY_ID
        assert "fuel" in args[0][1].lower()

    def test_shows_message_on_source_refuel_waypoint(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.overlay = MagicMock()
        router.overlay_var.set(True)

        # Source is always treated as a refuel row for exact/galaxy routes.
        # Offset=1 means player just arrived at index 0 (Sol).
        router.offset = 1
        router.jumps_left = 2
        router._set_current_location(coords=[0, 0, 0], system="Sol")
        router._update_overlay()

        router.overlay.send_message.assert_called_once()
        args = router.overlay.send_message.call_args
        assert args[0][0] == FUEL_OVERLAY_ID
        assert "fuel" in args[0][1].lower()

    def test_shows_message_on_galaxy_refuel_waypoint(self, router):
        router.overlay = MagicMock()
        router.overlay_var.set(True)
        router.galaxy = True
        router.current_plotter_name = "Galaxy Plotter"
        router.route = [
            ["Sol", "No", "0", "20"],
            ["Alpha Centauri", "Yes", "4.38", "5.62"],
            ["Destination", "No", "5.62", "0"],
        ]
        router.offset = 2
        router.jumps_left = 1
        router._set_current_location(coords=[0, 0, 0], system="Alpha Centauri")

        router._update_overlay()

        router.overlay.send_message.assert_called_once()
        args = router.overlay.send_message.call_args
        assert args[0][0] == FUEL_OVERLAY_ID
        assert "fuel" in args[0][1].lower()

    def test_journal_progression_updates_galaxy_fuel_overlay(self, router):
        router.overlay = MagicMock()
        router.overlay_var.set(True)
        router.galaxy = True
        router.current_plotter_name = "Galaxy Plotter"
        router.route = [
            ["Sol", "No", "0", "20"],
            ["Alpha Centauri", "Yes", "4.38", "5.62"],
            ["Destination", "No", "5.62", "0"],
        ]
        router.offset = 1
        router.next_stop = "Alpha Centauri"
        router.jumps_left = 2

        router._handle_journal_entry_ui(
            "Alpha Centauri",
            {"event": "FSDJump", "StarSystem": "Alpha Centauri", "StarPos": [0, 0, 0]},
            {},
        )

        calls = router.overlay.send_message.call_args_list
        fuel_call = next(call for call in calls if call.args[0] == FUEL_OVERLAY_ID)
        assert fuel_call.args[1] == "SCOOP FUEL HERE"

    def test_no_action_when_disabled(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.overlay = MagicMock()
        router.overlay_var.set(False)

        router.offset = 1
        router._update_overlay()

        router.overlay.send_message.assert_not_called()

    def test_no_action_without_exact_plotter(self, router):
        router.overlay = MagicMock()
        router.overlay_var.set(True)
        router.exact_plotter = False

        router._update_overlay()

        router.overlay.send_message.assert_not_called()
        router.overlay.send_raw.assert_any_call({"id": FUEL_OVERLAY_ID, "ttl": 0})
        router.overlay.send_raw.assert_any_call({"id": NEUTRON_OVERLAY_ID, "ttl": 0})

    def test_disabling_both_overlays_clears_stale_messages(self, router):
        router.overlay = MagicMock()
        router.exact_plotter = True
        router.overlay_var.set(False)
        router.neutron_overlay_var.set(False)
        router.route = [["Sol", "0", "0", "0"]]

        router._update_overlay()

        router.overlay.send_raw.assert_any_call({"id": FUEL_OVERLAY_ID, "ttl": 0})
        router.overlay.send_raw.assert_any_call({"id": NEUTRON_OVERLAY_ID, "ttl": 0})

    def test_hides_neutron_overlay_when_live_supercharge_state_is_known(self, router):
        router.current_plotter_name = "Neutron Plotter"
        router.overlay = MagicMock()
        router.neutron_overlay_var.set(True)
        router._apply_neutron_route_rows([
            {"system": "Sol", "jumps": 0, "distance_to_arrival": 0, "distance_remaining": 10, "neutron": "No", "done": False},
            {"system": "PSR J0000", "jumps": 1, "distance_to_arrival": 10, "distance_remaining": 0, "neutron": "Yes", "done": False},
        ])
        router.offset = 1
        router._supercharge_state_known = True
        router.is_supercharged = True
        router._set_current_location(coords=[0, 0, 0], system="PSR J0000")

        router._update_overlay()

        router.overlay.send_message.assert_not_called()
        router.overlay.send_raw.assert_any_call({"id": NEUTRON_OVERLAY_ID, "ttl": 0})

    def test_jet_cone_boost_hides_neutron_overlay_when_charge_is_known(self, router):
        router.current_plotter_name = "Neutron Plotter"
        router.overlay = MagicMock()
        router.neutron_overlay_var.set(True)
        router._apply_neutron_route_rows([
            {"system": "Sol", "jumps": 0, "distance_to_arrival": 0, "distance_remaining": 10, "neutron": "No", "done": False},
            {"system": "PSR J0000", "jumps": 1, "distance_to_arrival": 10, "distance_remaining": 0, "neutron": "Yes", "done": False},
        ])
        router.offset = 1
        router.is_supercharged = False
        router._set_current_location(coords=[0, 0, 0], system="PSR J0000")

        router._handle_journal_entry_ui("Sol", {"event": "JetConeBoost"}, {})

        assert router.is_supercharged is True
        assert router._supercharge_state_known is True
        router.overlay.send_raw.assert_any_call({"id": NEUTRON_OVERLAY_ID, "ttl": 0})

    def test_fsdjump_after_supercharge_shows_next_neutron_overlay(self, router):
        router.current_plotter_name = "Neutron Plotter"
        router.overlay = MagicMock()
        router.neutron_overlay_var.set(True)
        router._apply_neutron_route_rows([
            {"system": "Sol", "jumps": 0, "distance_to_arrival": 0, "distance_remaining": 20, "neutron": "No", "done": False},
            {"system": "PSR J0000", "jumps": 1, "distance_to_arrival": 10, "distance_remaining": 10, "neutron": "Yes", "done": False},
            {"system": "HIP 100000", "jumps": 1, "distance_to_arrival": 10, "distance_remaining": 0, "neutron": "No", "done": False},
        ])
        router.offset = 1
        router.next_stop = "PSR J0000"
        router.is_supercharged = True

        router._handle_journal_entry_ui(
            "PSR J0000",
            {"event": "FSDJump", "StarSystem": "PSR J0000", "StarPos": [0, 0, 0]},
            {},
        )

        assert router.is_supercharged is False
        assert router._supercharge_state_known is True
        assert router.offset == 2
        args = router.overlay.send_message.call_args
        assert args[0][0] == NEUTRON_OVERLAY_ID
        assert args[0][1] == "SUPERCHARGE"

    def test_overlay_prefers_current_system_over_offset_anchor(self, router):
        router.current_plotter_name = "Neutron Plotter"
        router.overlay = MagicMock()
        router.neutron_overlay_var.set(True)
        router._apply_neutron_route_rows([
            {"system": "Sol", "jumps": 0, "distance_to_arrival": 0, "distance_remaining": 20, "neutron": "No", "done": False},
            {"system": "PSR J0000", "jumps": 1, "distance_to_arrival": 10, "distance_remaining": 10, "neutron": "Yes", "done": False},
            {"system": "HIP 100000", "jumps": 1, "distance_to_arrival": 10, "distance_remaining": 0, "neutron": "No", "done": False},
        ])
        router.offset = 1
        router._set_current_location(coords=[0, 0, 0], system="PSR J0000")

        router._update_overlay()

        router.overlay.send_message.assert_called_once()
        args = router.overlay.send_message.call_args
        assert args[0][0] == NEUTRON_OVERLAY_ID
        assert args[0][1] == "SUPERCHARGE"

    def test_neutron_overlay_uses_configured_y_without_hidden_offset(self, router):
        router.current_plotter_name = "Neutron Plotter"
        router.overlay = MagicMock()
        router.neutron_overlay_var.set(True)
        router.neutron_y_var.set(650)
        router._apply_neutron_route_rows([
            {"system": "PSR J0000", "jumps": 1, "distance_to_arrival": 10, "distance_remaining": 0, "neutron": "Yes", "done": False},
        ])
        router.offset = 1
        router._set_current_location(coords=[0, 0, 0], system="PSR J0000")

        router._update_overlay()

        args = router.overlay.send_message.call_args
        assert args[0][0] == NEUTRON_OVERLAY_ID
        assert args[0][4] == 650

    def test_mixed_exact_row_shows_fuel_and_neutron_overlays(self, router):
        router.overlay = MagicMock()
        router.exact_plotter = True
        router.current_plotter_name = "Galaxy Plotter"
        router.overlay_var.set(True)
        router.neutron_overlay_var.set(True)
        router.overlay_y_var.set(650)
        router.neutron_y_var.set(650)
        router.route = [
            ["Sol", "0", "0", "20"],
            ["PSR J0000", "1", "10", "10"],
            ["HIP 100000", "1", "10", "0"],
        ]
        router.offset = 2
        router._set_current_location(coords=[0, 0, 0], system="PSR J0000")
        router.exact_route_data = [
            {"name": "Sol", "must_refuel": False, "has_neutron": False},
            {"name": "PSR J0000", "must_refuel": True, "has_neutron": True},
        ]

        router._update_overlay()

        calls = router.overlay.send_message.call_args_list
        fuel_call = next(call for call in calls if call.args[0] == FUEL_OVERLAY_ID)
        neutron_call = next(call for call in calls if call.args[0] == NEUTRON_OVERLAY_ID)
        assert fuel_call.args[1] == "SCOOP FUEL HERE"
        assert neutron_call.args[1] == "SUPERCHARGE"
        assert neutron_call.args[4] == 635

    def test_open_last_route_reconciles_mixed_exact_overlays_from_current_system(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.exact_route_data[1]["has_neutron"] = True
        router.offset = 2
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.overlay = MagicMock()
        router2.overlay_var.set(True)
        router2.neutron_overlay_var.set(True)

        with patch.object(monitor, "state", {"SystemName": "Alpha Centauri", "StarPos": [0, 0, 0]}):
            router2.open_last_route()

        calls = router2.overlay.send_message.call_args_list
        fuel_call = next(call for call in calls if call.args[0] == FUEL_OVERLAY_ID)
        neutron_call = next(call for call in calls if call.args[0] == NEUTRON_OVERLAY_ID)
        assert fuel_call.args[1] == "SCOOP FUEL HERE"
        assert neutron_call.args[1] == "SUPERCHARGE"

    def test_startup_replay_jet_cone_boost_hides_neutron_on_mixed_exact_row(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.exact_route_data[1]["has_neutron"] = True
        router.offset = 2
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.overlay = MagicMock()
        router2.overlay_var.set(True)
        router2.neutron_overlay_var.set(True)

        with patch.object(monitor, "state", {"SystemName": "Alpha Centauri", "StarPos": [0, 0, 0]}):
            router2.open_last_route()

        router2.overlay.reset_mock()
        router2._handle_journal_entry_ui(
            "Alpha Centauri",
            {"event": "JetConeBoost"},
            {"SystemName": "Alpha Centauri", "StarPos": [0, 0, 0]},
        )

        fuel_call = next(call for call in router2.overlay.send_message.call_args_list if call.args[0] == FUEL_OVERLAY_ID)
        assert router2.is_supercharged is True
        assert router2._supercharge_state_known is True
        assert fuel_call.args[1] == "SCOOP FUEL HERE"
        router2.overlay.send_raw.assert_any_call({"id": NEUTRON_OVERLAY_ID, "ttl": 0})

    def test_startup_restore_keeps_neutron_overlay_visible(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.exact_route_data[1]["has_neutron"] = True
        router.offset = 2
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.overlay = MagicMock()
        router2.overlay_var.set(True)
        router2.neutron_overlay_var.set(True)

        with patch.object(
            monitor,
            "state",
            {
                "SystemName": "Alpha Centauri",
                "StarPos": [0, 0, 0],
                "JumpRangeCurrent": 200.0,
                "MaxJumpRange": 50.0,
            },
        ):
            router2.open_last_route()

        fuel_call = next(call for call in router2.overlay.send_message.call_args_list if call.args[0] == FUEL_OVERLAY_ID)
        neutron_call = next(call for call in router2.overlay.send_message.call_args_list if call.args[0] == NEUTRON_OVERLAY_ID)
        assert fuel_call.args[1] == "SCOOP FUEL HERE"
        assert neutron_call.args[1] == "SUPERCHARGE"

    def test_startup_replay_fsdjump_reenables_neutron_after_supercharge_on_mixed_exact_row(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.exact_route_data[1]["has_neutron"] = True
        router.offset = 2
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.overlay = MagicMock()
        router2.overlay_var.set(True)
        router2.neutron_overlay_var.set(True)
        router2._supercharge_state_known = True
        router2.is_supercharged = True

        with patch.object(monitor, "state", {"SystemName": "Alpha Centauri", "StarPos": [0, 0, 0]}):
            router2.open_last_route()

        router2.overlay.reset_mock()
        router2._handle_journal_entry_ui(
            "Alpha Centauri",
            {"event": "FSDJump", "StarSystem": "Alpha Centauri", "StarPos": [0, 0, 0]},
            {"SystemName": "Alpha Centauri", "StarPos": [0, 0, 0]},
        )

        calls = router2.overlay.send_message.call_args_list
        fuel_call = next(call for call in calls if call.args[0] == FUEL_OVERLAY_ID)
        neutron_call = next(call for call in calls if call.args[0] == NEUTRON_OVERLAY_ID)
        assert router2.is_supercharged is False
        assert router2._supercharge_state_known is True
        assert fuel_call.args[1] == "SCOOP FUEL HERE"
        assert neutron_call.args[1] == "SUPERCHARGE"

    def test_fss_discovery_scan_keeps_neutron_overlay_visible(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.exact_route_data[1]["has_neutron"] = True
        router.offset = 2
        router.overlay = MagicMock()
        router.overlay_var.set(True)
        router.neutron_overlay_var.set(True)
        router._set_current_location(coords=[0, 0, 0], system="Alpha Centauri")
        router.overlay.reset_mock()

        with patch.object(
            monitor,
            "state",
            {
                "SystemName": "Alpha Centauri",
                "StarPos": [0, 0, 0],
                "JumpRangeCurrent": 200.0,
                "MaxJumpRange": 50.0,
            },
        ):
            router._handle_journal_entry_ui(
                "Alpha Centauri",
                {"event": "FSSDiscoveryScan", "SystemName": "Alpha Centauri"},
                {},
            )

        fuel_call = next(call for call in router.overlay.send_message.call_args_list if call.args[0] == FUEL_OVERLAY_ID)
        neutron_call = next(call for call in router.overlay.send_message.call_args_list if call.args[0] == NEUTRON_OVERLAY_ID)
        assert fuel_call.args[1] == "SCOOP FUEL HERE"
        assert neutron_call.args[1] == "SUPERCHARGE"

    def test_dashboard_guifocus_wakes_overlay_using_current_route_row(self, router):
        router._exact_plot_success(MOCK_ROUTE_DATA)
        router.exact_route_data[1]["has_neutron"] = True
        router.offset = 2
        router.overlay = MagicMock()
        router.overlay_var.set(True)
        router.neutron_overlay_var.set(True)
        router._set_current_location(coords=[0, 0, 0], system="Alpha Centauri")

        router._handle_dashboard_entry_ui({"GuiFocus": 8})

        fuel_call = next(call for call in router.overlay.send_message.call_args_list if call.args[0] == FUEL_OVERLAY_ID)
        neutron_call = next(call for call in router.overlay.send_message.call_args_list if call.args[0] == NEUTRON_OVERLAY_ID)
        assert fuel_call.args[1] == "SCOOP FUEL HERE"
        assert neutron_call.args[1] == "SUPERCHARGE"


class TestOverlayClear:
    def test_clear_prefers_raw_legacy_clear_payload(self, router):
        router.overlay = MagicMock()
        router._clear_overlay()

        router.overlay.send_raw.assert_called_once_with({"id": FUEL_OVERLAY_ID, "ttl": 0})
        router.overlay.send_message.assert_not_called()


    def test_clear_with_no_overlay(self, router):
        router.overlay = None
        # Should not crash
        router._clear_overlay()
