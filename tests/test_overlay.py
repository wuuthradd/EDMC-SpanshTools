"""Tests for overlay detection, toggle, and update logic."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
from SpanshTools.constants import FUEL_OVERLAY_ID, NEUTRON_OVERLAY_ID


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOCK_ROUTE_DATA = {
    "status": "ok",
    "result": {
        "jumps": [
            {"name": "Sol", "distance": 0, "distance_to_destination": 10.0, "must_refuel": False, "is_scoopable": False},
            {"name": "Alpha Centauri", "distance": 4.38, "distance_to_destination": 5.62, "must_refuel": True, "is_scoopable": True},
            {"name": "Destination", "distance": 5.62, "distance_to_destination": 0, "must_refuel": False, "is_scoopable": False},
        ]
    },
}


# ---------------------------------------------------------------------------
# toggle_overlay
# ---------------------------------------------------------------------------

def test_toggle_on_shows_position_frame(router):
    router._exact_plot_success(MOCK_ROUTE_DATA)
    router.overlay = MagicMock()
    router.overlay_var.set(True)
    router.toggle_overlay()
    assert router.overlay_pos_frame.visible is True
    assert router.overlay.send_message.called


def test_toggle_off_hides_and_clears(router):
    router._exact_plot_success(MOCK_ROUTE_DATA)
    router.overlay = MagicMock()
    router.overlay_var.set(False)
    router.toggle_overlay()
    assert router.overlay_pos_frame.visible is False
    assert router.overlay.send_raw.called


def test_toggle_without_overlay_shows_error(router):
    router.overlay = None
    router._exact_plot_success(MOCK_ROUTE_DATA)
    router.show_error = MagicMock()
    router.overlay_var.set(True)
    router.toggle_overlay()
    router.show_error.assert_called_once()
    assert router.overlay_var.get() is False


# ---------------------------------------------------------------------------
# _update_overlay
# ---------------------------------------------------------------------------

def test_refuel_waypoint_shows_overlay_message(router):
    router._exact_plot_success(MOCK_ROUTE_DATA)
    router.overlay = MagicMock()
    router.overlay_var.set(True)
    router.offset = 2
    router.jumps_left = 1
    router._set_current_location(coords=[0, 0, 0], system="Alpha Centauri")
    router._update_overlay()
    args = router.overlay.send_message.call_args
    assert args[0][0] == FUEL_OVERLAY_ID
    assert "fuel" in args[0][1].lower()


def test_disabled_overlay_skips_send(router):
    router._exact_plot_success(MOCK_ROUTE_DATA)
    router.overlay = MagicMock()
    router.overlay_var.set(False)
    router.offset = 1
    router._update_overlay()
    router.overlay.send_message.assert_not_called()


def test_mixed_exact_row_shows_both_overlays(router):
    router.overlay = MagicMock()
    router.exact_plotter = True
    router.current_plotter_name = "Exact Plotter"
    router.overlay_var.set(True)
    router.neutron_overlay_var.set(True)
    router.overlay_y_var.set(650)
    router.neutron_y_var.set(650)
    router.route = [["Sol", "0", "0", "20"], ["PSR J0000", "1", "10", "10"], ["HIP 100000", "1", "10", "0"]]
    router.offset = 2
    router._set_current_location(coords=[0, 0, 0], system="PSR J0000")
    router.exact_route_data = [
        {"name": "Sol", "must_refuel": False, "has_neutron": False},
        {"name": "PSR J0000", "must_refuel": True, "has_neutron": True},
        {"name": "HIP 100000", "must_refuel": False, "has_neutron": False},
    ]
    router._update_overlay()
    calls = router.overlay.send_message.call_args_list
    fuel_call = next(c for c in calls if c.args[0] == FUEL_OVERLAY_ID)
    neutron_call = next(c for c in calls if c.args[0] == NEUTRON_OVERLAY_ID)
    assert fuel_call.args[1] == "SCOOP FUEL HERE"
    assert neutron_call.args[1] == "SUPERCHARGE"
    assert neutron_call.args[4] == 635  # collision offset


# ---------------------------------------------------------------------------
# Supercharge lifecycle
# ---------------------------------------------------------------------------

def test_jet_cone_boost_hides_neutron_overlay(router):
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
    router.overlay.send_raw.assert_any_call({"id": NEUTRON_OVERLAY_ID, "ttl": 0})


def test_fsdjump_after_supercharge_shows_next_neutron_overlay(router):
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
    assert router.offset == 2
    args = router.overlay.send_message.call_args
    assert args[0][0] == NEUTRON_OVERLAY_ID


# ---------------------------------------------------------------------------
# _save_overlay_settings
# ---------------------------------------------------------------------------

def test_save_overlay_settings(router):
    router.overlay_var.set(True)
    router.overlay_x_var.set(100)
    router.overlay_y_var.set(200)
    router.neutron_overlay_var.set(True)
    router.neutron_x_var.set(300)
    router.neutron_y_var.set(400)
    router._save_overlay_settings()
    from conftest import _config_store
    assert _config_store.get("spansh_overlay_enabled") == 1
    assert _config_store.get("spansh_overlay_x") == 100
    assert _config_store.get("spansh_supercharge_overlay_x") == 300
