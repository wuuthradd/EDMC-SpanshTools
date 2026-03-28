"""Tests for the FSD data lookup table and parsing helpers."""

import sys
import os
import pytest
import threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import SpanshTools.fsd_data as fsd_data
from SpanshTools.fsd_data import (
    RATING_MAP, GUARDIAN_FSD_BOOSTS,
    parse_fsd_item_name, get_fsd_specs,
)


@pytest.fixture(autouse=True)
def _pin_fsd_source(monkeypatch):
    monkeypatch.setattr(fsd_data, "_all_specs", {})
    monkeypatch.setattr(fsd_data, "_specs_loaded", False)


class TestGetFsdSpecs:
    """Test get_fsd_specs() — looks up by journal item name / coriolis symbol."""

    def test_standard_fsd(self):
        specs = get_fsd_specs("int_hyperdrive_size5_class5")
        assert specs is not None
        assert specs["class"] == 5
        assert specs["rating"] == "A"
        assert specs["optimal_mass"] == 1050.0
        assert specs["max_fuel_per_jump"] == 5.0
        assert specs["fuel_power"] == 2.45
        assert specs["fuel_multiplier"] == 0.012

    def test_standard_6a(self):
        specs = get_fsd_specs("Int_Hyperdrive_Size6_Class5")
        assert specs is not None
        assert specs["optimal_mass"] == 1800.0
        assert specs["max_fuel_per_jump"] == 8.0
        assert specs["fuel_power"] == 2.60
        assert specs["fuel_multiplier"] == 0.012

    def test_sco_fsd(self):
        specs = get_fsd_specs("int_hyperdrive_overcharge_size5_class5")
        assert specs is not None
        assert specs["class"] == 5
        assert specs["rating"] == "A"
        assert specs["optimal_mass"] == 1175.0
        assert specs["max_fuel_per_jump"] == 5.2
        assert specs["fuel_multiplier"] == 0.013

    def test_sco_mkii(self):
        specs = get_fsd_specs(
            "Int_Hyperdrive_Overcharge_Size8_Class5_Overchargebooster_MkII"
        )
        assert specs is not None
        assert specs["class"] == 8
        assert specs["rating"] == "A"
        assert specs["optimal_mass"] == 4670.0
        assert specs["max_fuel_per_jump"] == 6.8
        assert specs["fuel_power"] == 2.5025
        assert specs["fuel_multiplier"] == 0.011

    def test_journal_wrapped_name(self):
        specs = get_fsd_specs("$int_hyperdrive_size7_class5_name;")
        assert specs is not None
        assert specs["class"] == 7
        assert specs["rating"] == "A"
        assert specs["optimal_mass"] == 2700.0

    def test_not_found(self):
        assert get_fsd_specs(None) is None
        assert get_fsd_specs("int_engine_size5_class5") is None
        assert get_fsd_specs("") is None
        assert get_fsd_specs("totally_bogus") is None

    def test_all_standard_classes_present(self):
        for cls in range(2, 8):
            for class_num, rating in RATING_MAP.items():
                name = f"int_hyperdrive_size{cls}_class{class_num}"
                specs = get_fsd_specs(name)
                assert specs is not None, f"Missing FSD spec for {name}"
                assert specs["optimal_mass"] > 0
                assert specs["max_fuel_per_jump"] > 0
                assert specs["fuel_power"] > 0
                assert specs["fuel_multiplier"] > 0

    def test_higher_class_has_higher_optimal_mass(self):
        for class_num in range(1, 6):
            for cls in range(2, 7):
                lower = get_fsd_specs(f"int_hyperdrive_size{cls}_class{class_num}")
                higher = get_fsd_specs(f"int_hyperdrive_size{cls+1}_class{class_num}")
                assert higher["optimal_mass"] > lower["optimal_mass"], (
                    f"Class {cls+1} should have higher opt mass than {cls}"
                )

    def test_supercharge_multiplier_standard(self):
        specs = get_fsd_specs("int_hyperdrive_size5_class5")
        assert specs["supercharge_multiplier"] == 4

    def test_supercharge_multiplier_sco(self):
        specs = get_fsd_specs("int_hyperdrive_overcharge_size5_class5")
        assert specs["supercharge_multiplier"] == 4

    def test_supercharge_multiplier_mkii(self):
        specs = get_fsd_specs(
            "Int_Hyperdrive_Overcharge_Size8_Class5_Overchargebooster_MkII"
        )
        assert specs["supercharge_multiplier"] == 6


class TestParseFsdItemName:
    """Test parse_fsd_item_name() — extracts (class, rating) for display."""

    def test_standard_name(self):
        assert parse_fsd_item_name("int_hyperdrive_size5_class5") == (5, "A")

    def test_size6_class3(self):
        assert parse_fsd_item_name("int_hyperdrive_size6_class3") == (6, "C")

    def test_size2_class1(self):
        assert parse_fsd_item_name("int_hyperdrive_size2_class1") == (2, "E")

    def test_journal_wrapped_name(self):
        assert parse_fsd_item_name("$int_hyperdrive_size7_class5_name;") == (7, "A")

    def test_uppercase(self):
        assert parse_fsd_item_name("Int_Hyperdrive_Size4_Class4") == (4, "B")

    def test_sco_fsd(self):
        assert parse_fsd_item_name("int_hyperdrive_overcharge_size5_class5") == (5, "A")

    def test_sco_mkii(self):
        assert parse_fsd_item_name(
            "Int_Hyperdrive_Overcharge_Size8_Class5_Overchargebooster_MkII"
        ) == (8, "A")

    def test_invalid_name(self):
        assert parse_fsd_item_name("int_engine_size5_class5") is None

    def test_empty_string(self):
        assert parse_fsd_item_name("") is None

    def test_invalid_rating_number(self):
        assert parse_fsd_item_name("int_hyperdrive_size5_class0") is None


class TestRatingMap:
    def test_all_ratings(self):
        assert RATING_MAP[1] == "E"
        assert RATING_MAP[2] == "D"
        assert RATING_MAP[3] == "C"
        assert RATING_MAP[4] == "B"
        assert RATING_MAP[5] == "A"


class TestGuardianBoosts:
    def test_all_sizes(self):
        assert GUARDIAN_FSD_BOOSTS[1] == 4.0
        assert GUARDIAN_FSD_BOOSTS[2] == 6.0
        assert GUARDIAN_FSD_BOOSTS[3] == 7.75
        assert GUARDIAN_FSD_BOOSTS[4] == 9.25
        assert GUARDIAN_FSD_BOOSTS[5] == 10.5


def test_ensure_specs_is_loaded_once_across_threads(monkeypatch):
    calls = {"load": 0}

    def fake_load():
        calls["load"] += 1
        return {
            "int_hyperdrive_size5_class5": {
                "class": 5,
                "rating": "A",
                "optimal_mass": 1050.0,
                "max_fuel_per_jump": 5.0,
                "fuel_power": 2.45,
                "fuel_multiplier": 0.012,
                "supercharge_multiplier": 4,
            }
        }

    monkeypatch.setattr(fsd_data, "load_specs_from_bundled_data", fake_load)

    threads = [threading.Thread(target=fsd_data.initialize_specs) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls["load"] == 1
    assert fsd_data._specs_loaded is True


def test_load_specs_from_bundled_data_reads_known_fsd():
    specs = fsd_data.load_specs_from_bundled_data()

    assert specs["int_hyperdrive_size5_class5"]["optimal_mass"] == 1050.0
    assert specs["int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii"]["supercharge_multiplier"] == 6


def test_save_specs_to_bundled_data_round_trip(tmp_path, monkeypatch):
    target = tmp_path / "fsd_specs.json"
    monkeypatch.setattr(fsd_data, "_data_file_path", lambda: str(target))

    fsd_data.save_specs_to_bundled_data({
        "INT_HYPERDRIVE_SIZE5_CLASS5": {
            "class": 5,
            "rating": "a",
            "optimal_mass": 1050,
            "max_fuel_per_jump": 5,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "supercharge_multiplier": 4,
        }
    })

    saved = fsd_data.load_specs_from_bundled_data()
    assert saved["int_hyperdrive_size5_class5"]["rating"] == "A"
    assert saved["int_hyperdrive_size5_class5"]["optimal_mass"] == 1050.0


def test_load_specs_from_bundled_data_reads_versioned_payload(tmp_path, monkeypatch):
    target = tmp_path / "fsd_specs.json"
    monkeypatch.setattr(fsd_data, "_data_file_path", lambda: str(target))
    target.write_text(
        '{"version": 3, "specs": {"int_hyperdrive_size5_class5": {"class": 5, "rating": "A", "optimal_mass": 1050.0, "max_fuel_per_jump": 5.0, "fuel_power": 2.45, "fuel_multiplier": 0.012, "supercharge_multiplier": 4}}}',
        encoding="utf-8",
    )

    saved = fsd_data.load_specs_from_bundled_data()
    assert saved["int_hyperdrive_size5_class5"]["optimal_mass"] == 1050.0


def test_reload_specs_from_bundled_data_refreshes_current_session(tmp_path, monkeypatch):
    target = tmp_path / "fsd_specs.json"
    monkeypatch.setattr(fsd_data, "_data_file_path", lambda: str(target))

    fsd_data.save_specs_to_bundled_data({
        "int_hyperdrive_size5_class5": {
            "class": 5,
            "rating": "A",
            "optimal_mass": 1000.0,
            "max_fuel_per_jump": 5.0,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "supercharge_multiplier": 4,
        }
    })
    assert get_fsd_specs("int_hyperdrive_size5_class5")["optimal_mass"] == 1000.0

    fsd_data.save_specs_to_bundled_data({
        "int_hyperdrive_size5_class5": {
            "class": 5,
            "rating": "A",
            "optimal_mass": 1050.0,
            "max_fuel_per_jump": 5.0,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "supercharge_multiplier": 4,
        }
    })

    assert fsd_data.reload_specs_from_bundled_data() is True
    assert get_fsd_specs("int_hyperdrive_size5_class5")["optimal_mass"] == 1050.0
