"""Tests for FSD data lookup and loadout processing."""

import sys
import os
import threading
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from conftest import STANDARD_5A_FSD_SPEC
import SpanshTools.ship_moduling as ship_moduling
from SpanshTools.ship_moduling import get_fsd_specs


@pytest.fixture(autouse=True)
def _pin_fsd_source(monkeypatch):
    monkeypatch.setattr(ship_moduling, "_all_specs", {})
    monkeypatch.setattr(ship_moduling, "_specs_loaded", False)


# ---------------------------------------------------------------------------
# get_fsd_specs
# ---------------------------------------------------------------------------

def test_standard_fsd_lookup():
    specs = get_fsd_specs("int_hyperdrive_size5_class5")
    assert specs["class"] == 5
    assert specs["rating"] == "A"
    assert specs["optimal_mass"] == 1050.0
    assert specs["max_fuel_per_jump"] == 5.0
    assert specs["supercharge_multiplier"] == 4


def test_sco_fsd_lookup():
    specs = get_fsd_specs("int_hyperdrive_overcharge_size5_class5")
    assert specs["optimal_mass"] == 1175.0
    assert specs["max_fuel_per_jump"] == 5.2
    assert specs["supercharge_multiplier"] == 4


def test_sco_mkii_has_multiplier_6():
    specs = get_fsd_specs("Int_Hyperdrive_Overcharge_Size8_Class5_Overchargebooster_MkII")
    assert specs["supercharge_multiplier"] == 6
    assert specs["class"] == 8


def test_journal_wrapped_name():
    specs = get_fsd_specs("$int_hyperdrive_size7_class5_name;")
    assert specs["class"] == 7
    assert specs["optimal_mass"] == 2700.0


def test_not_found_returns_none():
    assert get_fsd_specs(None) is None
    assert get_fsd_specs("") is None
    assert get_fsd_specs("int_engine_size5_class5") is None


# ---------------------------------------------------------------------------
# initialize_specs
# ---------------------------------------------------------------------------

def test_thread_safe_initialization(monkeypatch):
    calls = {"load": 0}

    def fake_load():
        calls["load"] += 1
        return {"int_hyperdrive_size5_class5": STANDARD_5A_FSD_SPEC}

    monkeypatch.setattr(ship_moduling, "load_specs_from_bundled_data", fake_load)
    threads = [threading.Thread(target=ship_moduling.initialize_specs) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert calls["load"] == 1


# ---------------------------------------------------------------------------
# process_loadout
# ---------------------------------------------------------------------------

def test_process_loadout_extracts_fsd(router):
    router.process_loadout({
        "event": "Loadout", "Ship": "anaconda",
        "Modules": [{"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5"}],
        "FuelCapacity": {"Main": 32.0, "Reserve": 0.63},
        "UnladenMass": 850.5, "CargoCapacity": 468,
    })
    fsd = router.ship_fsd_data
    assert fsd["optimal_mass"] == 1050.0
    assert fsd["tank_size"] == 32.0
    assert fsd["unladen_mass"] == 850.5


def test_process_loadout_applies_engineering_overrides(router):
    router.process_loadout({
        "event": "Loadout", "Ship": "asp",
        "Modules": [{
            "Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size6_class5",
            "Engineering": {"Modifiers": [
                {"Label": "FSDOptimalMass", "Value": 2700.0},
                {"Label": "MaxFuelPerJump", "Value": 10.5},
            ]},
        }],
        "FuelCapacity": {"Main": 64.0, "Reserve": 1.0},
        "UnladenMass": 400.0, "CargoCapacity": 100,
    })
    assert router.ship_fsd_data["optimal_mass"] == 2700.0
    assert router.ship_fsd_data["max_fuel_per_jump"] == 10.5


def test_guardian_fsd_booster_adds_range_boost(router):
    router.process_loadout({
        "event": "Loadout", "Ship": "anaconda",
        "Modules": [
            {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5"},
            {"Slot": "Slot06_Size5", "Item": "int_guardianfsdbooster_size5"},
        ],
        "FuelCapacity": {"Main": 32.0, "Reserve": 0.63},
        "UnladenMass": 850.5, "CargoCapacity": 468,
    })
    assert router.ship_fsd_data["range_boost"] == 10.5


# ---------------------------------------------------------------------------
# _suggest_jump_range
# ---------------------------------------------------------------------------

_RANGE_LOADOUT = {
    "event": "Loadout",
    "Ship": "python",
    "ShipID": 42,
    "Modules": [
        {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5"},
    ],
    "FuelCapacity": {"Main": 32.0, "Reserve": 0.63},
    "UnladenMass": 500.0,
    "CargoCapacity": 64,
}


def test_suggest_jump_range_from_monitor_ship(router, monkeypatch):
    """Live monitor.ship() loadout produces a plausible range."""
    import monitor as mon_mod
    monkeypatch.setattr(mon_mod.monitor, "live", True)
    monkeypatch.setattr(mon_mod.monitor, "ship", lambda: _RANGE_LOADOUT)
    mon_mod.monitor.state.update({"Cargo": {}, "FuelLevel": 32.0})
    router._range_prefill_ready = True

    result = router._suggest_jump_range()
    assert result is not None
    assert 10 < result < 100


def test_suggest_jump_range_from_ship_list(router, monkeypatch):
    """Falls back to _ship_list when monitor.ship() is None."""
    import monitor as mon_mod
    monkeypatch.setattr(mon_mod.monitor, "live", False)
    monkeypatch.setattr(mon_mod.monitor, "ship", lambda: None)
    mon_mod.monitor.state.update({"ShipID": 42, "Ship": "python", "Cargo": {}, "FuelLevel": None})
    router._range_prefill_ready = True
    router._ship_list = [{"loadout": _RANGE_LOADOUT}]

    result = router._suggest_jump_range()
    assert result is not None
    assert 10 < result < 100


def test_suggest_jump_range_not_ready_returns_none(router):
    """Returns None when _range_prefill_ready is False."""
    router._range_prefill_ready = False
    assert router._suggest_jump_range() is None


def test_suggest_jump_range_no_loadout_returns_none(router, monkeypatch):
    """Returns None when no loadout source is available."""
    import monitor as mon_mod
    monkeypatch.setattr(mon_mod.monitor, "live", False)
    monkeypatch.setattr(mon_mod.monitor, "ship", lambda: None)
    mon_mod.monitor.state.update({"ShipID": None, "Ship": None})
    router._range_prefill_ready = True
    router._ship_list = []

    assert router._suggest_jump_range() is None
