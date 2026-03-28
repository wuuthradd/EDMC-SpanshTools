"""Tests for process_loadout() — FSD extraction from Loadout journal events."""

import sys
import os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from SpanshTools.core import SpanshTools
from conftest import PLUGIN_VERSION

# Minimal Loadout event with a 5A FSD, no engineering
LOADOUT_5A = {
    "event": "Loadout",
    "Ship": "anaconda",
    "Modules": [
        {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5"},
        {"Slot": "PowerPlant", "Item": "int_powerplant_size7_class5"},
    ],
    "FuelCapacity": {"Main": 32.0, "Reserve": 0.63},
    "UnladenMass": 850.5,
    "CargoCapacity": 468,
}

# Loadout with engineered FSD (modified optimal mass)
LOADOUT_6A_ENGINEERED = {
    "event": "Loadout",
    "Ship": "asp",
    "Modules": [
        {
            "Slot": "FrameShiftDrive",
            "Item": "int_hyperdrive_size6_class5",
            "Engineering": {
                "BlueprintName": "FSD_LongRange",
                "Level": 5,
                "Modifiers": [
                    {"Label": "FSDOptimalMass", "Value": 2700.0, "OriginalValue": 1800.0},
                    {"Label": "MaxFuelPerJump", "Value": 10.5, "OriginalValue": 8.0},
                ],
            },
        },
    ],
    "FuelCapacity": {"Main": 64.0, "Reserve": 1.0},
    "UnladenMass": 400.0,
    "CargoCapacity": 100,
}

# Loadout with Guardian FSD Booster
LOADOUT_WITH_BOOSTER = {
    "event": "Loadout",
    "Ship": "krait_mkii",
    "Modules": [
        {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5"},
        {"Slot": "Slot01_Size5", "Item": "int_fsdbooster_size5_class1"},
    ],
    "FuelCapacity": {"Main": 32.0, "Reserve": 0.63},
    "UnladenMass": 500.0,
    "CargoCapacity": 64,
}

# Loadout with journal-style wrapped item name
LOADOUT_WRAPPED = {
    "event": "Loadout",
    "Ship": "diamondback",
    "Modules": [{"Slot": "FrameShiftDrive", "Item": "$int_hyperdrive_size4_class5_name;"}],
    "FuelCapacity": {"Main": 16.0, "Reserve": 0.5},
    "UnladenMass": 200.0,
    "CargoCapacity": 30,
}


@pytest.mark.parametrize("loadout, expected_fsd_dict", [
    (
        LOADOUT_5A, 
        {
            "optimal_mass": 1050.0,
            "max_fuel_per_jump": 5.0,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "tank_size": 32.0,
            "reserve_size": 0.63,
            "unladen_mass": 850.5,
            "range_boost": 0.0,
        }
    ),
    (
        LOADOUT_6A_ENGINEERED,
        {
            "optimal_mass": 2700.0,
            "max_fuel_per_jump": 10.5,
            "fuel_power": 2.60,
            "fuel_multiplier": 0.012,
            "tank_size": 64.0,
        }
    ),
    (
        LOADOUT_WITH_BOOSTER,
        {"range_boost": 10.5}
    ),
    (
        LOADOUT_WRAPPED,
        {"optimal_mass": 525.0} # 4A FSD
    )
])
def test_process_valid_fsd_loadouts(router, loadout, expected_fsd_dict):
    router.process_loadout(loadout)
    fsd = router.ship_fsd_data
    assert fsd is not None
    
    # Assert only the overlapping keys provided in expected dictionary
    for key, expected_val in expected_fsd_dict.items():
        assert fsd[key] == expected_val


@pytest.mark.parametrize("invalid_loadout", [
    {
        "event": "Loadout",
        "Modules": [{"Slot": "PowerPlant", "Item": "int_powerplant_size5_class5"}],
        "FuelCapacity": {"Main": 16.0, "Reserve": 0.5},
        "UnladenMass": 200.0,
    },
    {
        "event": "Loadout",
        "Modules": [{"Slot": "FrameShiftDrive", "Item": "some_unknown_fsd"}],
        "FuelCapacity": {"Main": 16.0, "Reserve": 0.5},
        "UnladenMass": 200.0,
    }
], ids=["no_fsd_module", "unknown_fsd_module"])
def test_no_or_unknown_fsd_leaves_data_none(router, invalid_loadout):
    router.process_loadout(invalid_loadout)
    assert router.ship_fsd_data is None


def test_detect_fsd_from_state_preserves_slot_names_for_dict_modules(router):
    state = {
        "Modules": {
            "FrameShiftDrive": {"Item": "int_hyperdrive_size5_class5"},
            "PowerPlant": {"Item": "int_powerplant_size5_class5"},
        },
        "FuelCapacity": {"Main": 32.0, "Reserve": 0.63},
        "UnladenMass": 500.0,
        "CargoCapacity": 32,
    }

    router._detect_fsd_from_state(state)
    assert router.ship_fsd_data is not None
    assert router.ship_fsd_data["optimal_mass"] == 1050.0
