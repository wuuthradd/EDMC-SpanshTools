"""Tests for SpanshTools.route_io -- route persistence, import/export helpers, and pure logic."""

import json
import os

import pytest
from unittest.mock import MagicMock

from SpanshTools.core import SpanshTools
from conftest import create_router


# ---------------------------------------------------------------------------
# _write_json_atomic
# ---------------------------------------------------------------------------

class TestWriteJsonAtomic:
    def test_atomic_write_no_temp_residue(self, router, tmp_path):
        """Writes valid JSON via temp-then-replace; no temp file left."""
        outdir = tmp_path / "output"
        outdir.mkdir()
        target = outdir / "data.json"
        payload = {"key": "value", "count": 42}

        router._write_json_atomic(str(target), payload, prefix=".test.")

        assert json.loads(target.read_text(encoding="utf-8")) == payload
        assert [f.name for f in outdir.iterdir()] == ["data.json"]

    def test_cleanup_on_serialization_failure(self, router, tmp_path):
        """On failure the temp file is removed, not left behind."""
        outdir = tmp_path / "output"
        outdir.mkdir()
        target = outdir / "data.json"

        class Unserializable:
            pass

        with pytest.raises(TypeError):
            router._write_json_atomic(str(target), {"bad": Unserializable()}, prefix=".test.")

        assert list(outdir.iterdir()) == []


# ---------------------------------------------------------------------------
# _serialize_route_state / _apply_route_state round-trip
# ---------------------------------------------------------------------------

class TestRouteStateRoundTrip:
    def test_round_trip_preserves_all_route_data(self, router):
        """Serialize then apply preserves exact, fleet, and exploration data."""
        router.route = [["Sol", "0"], ["Colonia", "1"]]
        router.route_done = [True, False]
        router.route_type = "exact"
        router.current_plotter_name = "Exact Plotter"
        router.exploration_mode = None
        router.offset = 1
        router.jumps_left = 1
        router.exact_route_data = [
            {"name": "Sol", "done": True, "distance": 0, "distance_to_destination": 100},
            {"name": "Colonia", "done": False, "distance": 100, "distance_to_destination": 0},
        ]
        router.fleet_carrier_data = [{"name": "FC-1", "done": False}]
        router.exploration_route_data = [
            {"name": "Sys1", "bodies": [{"name": "B1", "done": False}]},
        ]

        payload = router._serialize_route_state()
        assert payload is not None
        assert payload["route_type"] == "exact"
        assert payload["planner"] == "Exact Plotter"
        assert len(payload["exact_route_data"]) == 2
        assert len(payload["fleet_carrier_data"]) == 1
        assert len(payload["exploration_route_data"]) == 1

        # Wipe state, then restore from payload
        router.route, router.route_done = [], []
        router.route_type = None
        router.exact_route_data = []
        router.fleet_carrier_data = []
        router.exploration_route_data = []

        router._apply_route_state(payload)

        assert router.route_type == "exact"
        assert router.current_plotter_name == "Exact Plotter"
        assert router.route == [["Sol", "0"], ["Colonia", "1"]]
        assert len(router.exact_route_data) == 2
        assert len(router.fleet_carrier_data) == 1
        assert len(router.exploration_route_data) == 1


# ---------------------------------------------------------------------------
# _load_plotter_settings
# ---------------------------------------------------------------------------

class TestLoadPlotterSettings:
    def test_corrupt_file_recovers_to_empty(self, router):
        """Corrupt JSON on disk resets _plotter_settings to empty dict."""
        os.makedirs(os.path.dirname(router.plotter_settings_path), exist_ok=True)
        with open(router.plotter_settings_path, "w") as f:
            f.write("{invalid json!!")

        router._load_plotter_settings()

        assert router._plotter_settings == {}

    def test_galaxy_plotter_migrated_to_exact_plotter(self, router):
        """Legacy 'Galaxy Plotter' key is renamed to 'Exact Plotter'."""
        os.makedirs(os.path.dirname(router.plotter_settings_path), exist_ok=True)
        payload = {
            "planners": {
                "Galaxy Plotter": {"source": "Sol", "destination": "Colonia"},
                "Neutron Plotter": {"source": "Beagle Point"},
            }
        }
        with open(router.plotter_settings_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        router._load_plotter_settings()

        planners = router._plotter_settings["planners"]
        assert "Galaxy Plotter" not in planners
        assert planners["Exact Plotter"] == {"source": "Sol", "destination": "Colonia"}
        assert planners["Neutron Plotter"] == {"source": "Beagle Point"}


# ---------------------------------------------------------------------------
# _store_plotter_settings / _settings_for_planner round-trip
# ---------------------------------------------------------------------------

class TestPlotterSettingsRoundTrip:
    def test_store_retrieve_and_preserve_others(self, router):
        """Store for one planner; retrieve it; other planners untouched."""
        router._plotter_settings = {"planners": {"Exact Plotter": {"source": "Sol"}}}
        router._save_plotter_settings = MagicMock()

        router._store_plotter_settings("Neutron Plotter", {"source": "Achenar", "range": "50"})

        assert router._settings_for_planner("Neutron Plotter") == {"source": "Achenar", "range": "50"}
        assert router._settings_for_planner("Exact Plotter") == {"source": "Sol"}
        assert router._settings_for_planner("Nonexistent") == {}

    def test_disk_round_trip_survives_reload(self, router):
        """Store, write to disk, reload from disk — values survive."""
        router._store_plotter_settings("Exact Plotter", {"source": "Sol", "destination": "Colonia"})
        router._save_plotter_settings()
        router._plotter_settings = {}

        router._load_plotter_settings()

        assert router._settings_for_planner("Exact Plotter") == {"source": "Sol", "destination": "Colonia"}


# ---------------------------------------------------------------------------
# _detect_json_route_type
# ---------------------------------------------------------------------------

class TestDetectJsonRouteType:
    @pytest.mark.parametrize("params, result, expected", [
        ({"efficiency": 60}, [], "neutron"),
        ({"algorithm": "optimistic"}, {}, "exact"),
        ({"calculate_starting_fuel": True}, {}, "fleet_carrier"),
        ({"body_types": ["Ammonia world"]}, [], "body_types"),
        ({}, [{"bodies": [{"landmarks": [{"subtype": "A"}]}]}], "exomastery"),
        ({"use_mapping_value": True}, [], "riches"),
        ({}, {}, None),
    ], ids=["neutron", "exact", "fleet", "body_types", "exomastery", "riches", "unrecognised"])
    def test_all_route_types(self, router, params, result, expected):
        assert router._detect_json_route_type(params, result) == expected


# ---------------------------------------------------------------------------
# _apply_fleet_waypoint_flags
# ---------------------------------------------------------------------------

class TestApplyFleetWaypointFlags:
    def test_source_and_destination_marking(self, router):
        """Explicit source/dest are waypoints; intermediate is not."""
        jumps = [{"name": "Sol"}, {"name": "Achenar"}, {"name": "Colonia"}]
        router._apply_fleet_waypoint_flags(jumps, source="Sol", destinations=["Colonia"])

        assert jumps[0]["is_waypoint"] is True
        assert jumps[1]["is_waypoint"] is False
        assert jumps[2]["is_waypoint"] is True

    def test_fallback_marks_first_last_and_duplicate_names(self, router):
        """Without explicit waypoints, first/last/duplicate names are flagged."""
        jumps = [
            {"name": "Sol"}, {"name": "Achenar"},
            {"name": "Sol"}, {"name": "Colonia"},
        ]
        router._apply_fleet_waypoint_flags(jumps)

        assert jumps[0]["is_waypoint"] is True   # first
        assert jumps[1]["is_waypoint"] is False   # unique middle
        assert jumps[2]["is_waypoint"] is True    # duplicate "Sol"
        assert jumps[3]["is_waypoint"] is True    # last


# ---------------------------------------------------------------------------
# _resolve_saved_route_type
# ---------------------------------------------------------------------------

class TestResolveSavedRouteType:
    @pytest.mark.parametrize("route_type", ["exact", "fleet_carrier", "exploration", "neutron", "simple"])
    def test_known_types_pass_through(self, router, route_type):
        assert router._resolve_saved_route_type({"route_type": route_type}) == route_type

    def test_unknown_falls_back_to_simple_or_none(self, router):
        assert router._resolve_saved_route_type({"route_type": "bogus", "route": [["Sol"]]}) == "simple"
        assert router._resolve_saved_route_type({"route_type": "bogus"}) is None


# ---------------------------------------------------------------------------
# _apply_exploration_route_data
# ---------------------------------------------------------------------------

class TestApplyExplorationRouteData:
    def test_populates_route_and_route_done(self, router):
        systems = [
            {"name": "Sys1", "jumps": 2, "bodies": [{"name": "B1"}]},
            {"name": "Sys2", "jumps": 1, "bodies": [{"name": "B2"}]},
        ]
        router._apply_exploration_route_data("Road to Riches", systems)

        assert router.route_type == "exploration"
        assert router.route == [["Sys1", "2"], ["Sys2", "1"]]
        assert router.route_done == [False, False]
        assert router.jumps_left == 3
        assert router.exploration_route_data is systems


# ---------------------------------------------------------------------------
# _exploration_view_rows -- riches totals
# ---------------------------------------------------------------------------

class TestExplorationViewRows:
    def test_riches_totals_row(self, router):
        """Totals row correctly sums scan/mapping values and system/body counts."""
        systems = [
            {
                "name": "Sys1", "jumps": 1,
                "bodies": [
                    {"name": "B1", "subtype": "ELW", "estimated_scan_value": 100,
                     "estimated_mapping_value": 200, "distance_to_arrival": 10},
                    {"name": "B2", "subtype": "WW", "estimated_scan_value": 50,
                     "estimated_mapping_value": 80, "distance_to_arrival": 20},
                ],
            },
            {
                "name": "Sys2", "jumps": 2,
                "bodies": [
                    {"name": "B3", "subtype": "HMC", "estimated_scan_value": 30,
                     "estimated_mapping_value": 40, "distance_to_arrival": 5},
                ],
            },
        ]
        router._apply_exploration_route_data("Road to Riches", systems)
        rows = router._exploration_view_rows()

        totals = rows[-1]
        assert totals["is_total"] is True
        vals = totals["values"]
        assert "2" in vals[1]       # 2 systems
        assert "3" in vals[2]       # 3 bodies
        assert vals[-3] == "180"    # scan: 100+50+30
        assert vals[-2] == "320"    # map:  200+80+40
        assert vals[-1] == 3        # jumps: 1+2


# ---------------------------------------------------------------------------
# _clear_plotter_settings (NEW)
# ---------------------------------------------------------------------------

class TestClearPlotterSettings:
    def test_resets_attributes_and_removes_file(self, router):
        """Nulls current_plotter_name, empties settings dict, deletes file."""
        os.makedirs(os.path.dirname(router.plotter_settings_path), exist_ok=True)
        with open(router.plotter_settings_path, "w") as f:
            json.dump({"planners": {"X": {"a": 1}}}, f)
        router.current_plotter_name = "Neutron Plotter"
        router._plotter_settings = {"planners": {"X": {"a": 1}}}

        router._clear_plotter_settings()

        assert router.current_plotter_name is None
        assert router._plotter_settings == {}
        assert not os.path.exists(router.plotter_settings_path)


# ---------------------------------------------------------------------------
# _resolve_system_id -- numeric ID to system name
# ---------------------------------------------------------------------------

class TestResolveSystemId:
    def test_numeric_id_resolved_from_jumps(self, router):
        result = {"jumps": [
            {"id64": 10477373803, "name": "Sol"},
            {"id64": 1178708478315, "name": "Alpha Centauri"},
        ]}
        assert router._resolve_system_id("10477373803", result) == "Sol"
        assert router._resolve_system_id("1178708478315", result) == "Alpha Centauri"

    def test_string_name_passes_through(self, router):
        assert router._resolve_system_id("Colonia", {}) == "Colonia"

    def test_empty_returns_empty(self, router):
        assert router._resolve_system_id("", {}) == ""
        assert router._resolve_system_id(None, {}) == ""

    def test_unmatched_numeric_returns_as_is(self, router):
        assert router._resolve_system_id("99999", {"jumps": []}) == "99999"


# ---------------------------------------------------------------------------
# _restore_offset_from_done_progress -- edge cases
# ---------------------------------------------------------------------------

class TestRestoreOffsetFromDoneProgress:
    def test_all_done_sets_final_position(self, router):
        """When every system is done, offset lands on the last row."""
        router.route = [["Sol", "0"], ["Achenar", "1"], ["Colonia", "1"]]
        router.route_type = "exact"
        router.exact_route_data = [
            {"name": "Sol", "done": True},
            {"name": "Achenar", "done": True},
            {"name": "Colonia", "done": True},
        ]
        router.route_done = [True, True, True]

        result = router._restore_offset_from_done_progress()

        assert result is True
        assert router.offset == 2
        assert router.next_stop == ""

    def test_none_done_returns_false(self, router):
        """When no system is done, offset restore declines."""
        router.route = [["Sol", "0"], ["Achenar", "1"]]
        router.route_type = "simple"
        router.route_done = [False, False]

        result = router._restore_offset_from_done_progress()

        assert result is False


# ---------------------------------------------------------------------------
# Neutron route save/load round-trip
# ---------------------------------------------------------------------------

class TestNeutronRouteRoundTrip:
    def test_neutron_route_persists_and_restores(self, router):
        rows = [
            {"system": "Sol", "jumps": 0, "distance_jumped": 0, "distance_left": 500,
             "neutron_star": False, "done": False},
            {"system": "PSR J0000", "jumps": 2, "distance_jumped": 300, "distance_left": 200,
             "neutron_star": True, "done": False},
            {"system": "Colonia", "jumps": 1, "distance_jumped": 200, "distance_left": 0,
             "neutron_star": False, "done": False},
        ]
        settings = {"source": "Sol", "destination": "Colonia", "range": "60", "efficiency": 0.6}
        router._apply_neutron_route_rows(rows, settings=settings)
        router.offset = 1
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.plotter_settings_path = router.plotter_settings_path
        router2.open_last_route()

        assert router2.route_type == "neutron"
        assert router2.current_plotter_name == "Neutron Plotter"
        assert len(router2.route) == 3
        assert router2.route[1][0] == "PSR J0000"
        assert router2.route[1][4] == "Yes"
        assert router2.offset == 1
        assert len(router2.neutron_route_data) == 3