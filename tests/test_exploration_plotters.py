"""Tests for plotter payloads, grouped route persistence, and route viewer UX."""

import csv
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from SpanshTools.core import SpanshTools
from conftest import DummyWidget, create_router


class DummyAC:
    def __init__(self, text, placeholder):
        self._text = text
        self.placeholder = placeholder

    def get(self):
        return self._text

    def hide_list(self):
        pass

    def set_text(self, text, _placeholder_style):
        self._text = text


class DummyEntry:
    def __init__(self, value, minimum=0, maximum=100):
        self._value = value
        self._minimum = minimum
        self._maximum = maximum

    def get(self):
        return self._value

    def delete(self, *_args, **_kwargs):
        self._value = ""

    def insert(self, _index, value):
        self._value = str(value)

    def cget(self, key):
        if key == "from":
            return self._minimum
        if key == "to":
            return self._maximum
        raise KeyError(key)




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
            {
                "name": "Sol A 2",
                "subtype": "Ammonia world",
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
                "subtype": "Ammonia world",
                "is_terraformable": False,
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


class TestExplorationPayloads:
    def test_traditional_form_data_repeats_array_keys(self, router):

        encoded = router._traditional_form_data({
            "from": "Sol",
            "body_types": ["Rocky body", "High metal content world"],
            "max_results": 100,
        })

        assert encoded == [
            ("from", "Sol"),
            ("body_types", "Rocky body"),
            ("body_types", "High metal content world"),
            ("max_results", 100),
        ]

    def _prepare_form(self, router):
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

    def test_riches_payload_matches_spansh_fields(self, router):
        self._prepare_form(router)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_exploration_route("Road to Riches")

        kwargs = thread_cls.call_args.kwargs
        api_url, params, planner = kwargs["args"][:3]
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
        assert params["avoid_thargoids"] == 1
        assert params["loop"] == 1

    def test_exomastery_payload_matches_spansh_fields(self, router):
        self._prepare_form(router)
        router._exp_min_value = DummyEntry("10000000", minimum=0, maximum=10000000)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_exploration_route("Exomastery")

        kwargs = thread_cls.call_args.kwargs
        api_url, params, planner = kwargs["args"][:3]
        assert api_url == "https://spansh.co.uk/api/exobiology/route"
        assert planner == "Exomastery"
        assert params["from"] == "Sol"
        assert params["to"] == "Achenar"
        assert params["range"] == 87.0
        assert params["radius"] == 25
        assert params["max_results"] == 100
        assert params["max_distance"] == 1000000
        assert params["min_value"] == 10000000
        assert params["avoid_thargoids"] == 1
        assert params["loop"] == 1

    def test_specialized_riches_route_uses_body_types(self, router):
        self._prepare_form(router)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_exploration_route("Rocky/HMC Route")

        _, params, planner = thread_cls.call_args.kwargs["args"][:3]
        assert planner == "Rocky/HMC Route"
        assert params["body_types"] == ["Rocky body", "High metal content world"]
        assert params["min_value"] == 1
        assert "use_mapping_value" not in params

    def test_exploration_payload_values_are_clamped_to_spansh_limits(self, router):
        self._prepare_form(router)
        router._exp_range = DummyEntry("500", minimum=0, maximum=100)
        router._exp_radius = DummyEntry("5000", minimum=1, maximum=1000)
        router._exp_max_results = DummyEntry("9999", minimum=1, maximum=2000)
        router._exp_max_distance = DummyEntry("1500000000", minimum=1, maximum=1000000)
        router._exp_min_value = DummyEntry("2000000000", minimum=0, maximum=1000000)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_exploration_route("Road to Riches")

        _, params, _planner = thread_cls.call_args.kwargs["args"][:3]
        assert params["range"] == 100.0
        assert params["radius"] == 1000
        assert params["max_results"] == 2000
        assert params["max_distance"] == 1000000
        assert params["min_value"] == 1000000


class TestExplorationPersistence:
    def test_riches_csv_rows_are_formatted_grouped_and_include_total(self, router):
        router._apply_exploration_route_data("Road to Riches", RICHES_SYSTEMS)

        rows = [row["values"] for row in router._exploration_view_rows()]

        assert rows[0] == [
            "□",
            "Sol",
            "Sol A 1",
            "Earth-like world",
            "✓",
            "523",
            "1,200,000",
            "3,200,000",
            0,
        ]
        assert rows[1] == [
            "□",
            "",
            "Sol A 2",
            "Water world",
            "✕",
            "1,100",
            "400,000",
            "900,000",
            "",
        ]
        assert rows[-1] == [
            "Total",
            "2 systems",
            "3 bodies",
            "",
            "",
            "",
            "2,100,000",
            "5,600,000",
            5,
        ]

    def test_exobiology_csv_rows_are_formatted_grouped_and_include_total(self, router):
        router._apply_exploration_route_data("Exomastery", EXOBIOLOGY_SYSTEMS)

        rows = [row["values"] for row in router._exploration_view_rows()]

        assert rows[0] == [
            "□",
            "Shinrarta Dezhra",
            "Shinrarta Dezhra A 1",
            "Rocky body",
            "200",
            "bacterium",
            2,
            "19,000,000",
            0,
        ]
        assert rows[1] == [
            "□",
            "",
            "",
            "",
            "",
            "fungoida",
            1,
            "7,000,000",
            "",
        ]
        assert rows[-1] == [
            "Total",
            "2 systems",
            "2 bodies",
            "",
            "",
            "3 landmarks",
            "",
            "38,000,000",
            3,
        ]

    def test_saved_riches_csv_uses_new_headers_and_formatted_rows(self, router):
        router._apply_exploration_route_data("Road to Riches", RICHES_SYSTEMS)
        router.save_all_route()

        with open(router._route_state_path(), "r") as handle:
            payload = json.load(handle)

        assert payload["planner"] == "Road to Riches"
        assert payload["exploration_plotter"] is True
        assert payload["exploration_mode"] == "Road to Riches"
        assert len(payload["route"]) == 2
        assert payload["exploration_route_data"][0]["bodies"][1]["name"] == "Sol A 2"

    def test_saved_specialized_csv_omits_subtype_and_terraformable_columns(self, router):
        router._apply_exploration_route_data("Ammonia World Route", AMMONIA_SYSTEMS)
        router.save_all_route()

        with open(router._route_state_path(), "r") as handle:
            payload = json.load(handle)

        assert payload["planner"] == "Ammonia World Route"
        assert payload["exploration_mode"] == "Ammonia World Route"
        assert payload["exploration_route_data"][0]["bodies"][0]["name"] == "Sol A 1"
        assert payload["exploration_route_data"][0]["bodies"][0]["distance_to_arrival"] == 523
        assert payload["route"][0][0] == "Sol"
        assert payload["route"][1][0] == "Achenar"

    def test_bodyless_specialized_system_rows_do_not_emit_done_checkbox(self, router):
        systems = [
            {"name": "Sol", "jumps": 0, "bodies": []},
            {
                "name": "Achenar",
                "jumps": 5,
                "bodies": [{"name": "Achenar 3", "distance_to_arrival": 300}],
            },
            {"name": "Colonia", "jumps": 2, "bodies": []},
        ]

        router._apply_exploration_route_data("Ammonia World Route", systems)

        rows = [row["values"] for row in router._exploration_view_rows()]

        assert rows[0] == ["", "Sol", "", "", 0]
        assert rows[2] == ["", "Colonia", "", "", 2]
        assert rows[-1] == ["Total", "3 systems", "1 bodies", "", 7]

    def test_imports_exploration_json(self, router):

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

    def test_exploration_route_success_accepts_full_spansh_payload_shape(self, router):

        router._exp_source_ac = DummyAC("Sol", "Source System")
        router._exp_dest_ac = DummyAC("HIP 100000", "Destination System")
        router._exp_range = DummyEntry("87")
        router._exp_radius = DummyEntry("25")
        router._exp_max_results = DummyEntry("100")
        router._exp_max_distance = DummyEntry("50000")
        router._exp_use_mapping_var = MagicMock(get=MagicMock(return_value=False))
        router._exp_avoid_thargoids_var = MagicMock(get=MagicMock(return_value=True))
        router._exp_loop = MagicMock(get=MagicMock(return_value=True))
        router._set_main_controls_enabled = MagicMock()
        router._set_plotter_windows_enabled = MagicMock()
        router._close_plotter_window = MagicMock()

        payload = {
            "job": "abc",
            "status": "ok",
            "state": "completed",
            "result": AMMONIA_SYSTEMS,
        }

        router._exploration_route_success(payload, "Ammonia World Route")

        assert router.exploration_plotter is True
        assert router.exploration_mode == "Ammonia World Route"
        assert [row[0] for row in router.route] == ["Sol", "Achenar"]
        assert router._close_plotter_window.call_count >= 1

    def test_riches_routes_navigate_by_unique_system_after_reload(self, router):
        router._apply_exploration_route_data("Road to Riches", RICHES_SYSTEMS)
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.open_last_route()

        assert router2.exploration_plotter is True
        assert router2.exploration_mode == "Road to Riches"
        assert [row[0] for row in router2.route] == ["Sol", "Achenar"]
        assert router2.jumps_left == 5
        assert len(router2.exploration_route_data) == 2
        assert len(router2.exploration_route_data[0]["bodies"]) == 2

    def test_specialized_routes_preserve_mode_after_reload(self, router):
        router._apply_exploration_route_data("Ammonia World Route", AMMONIA_SYSTEMS)
        router._store_plotter_settings("Ammonia World Route", {})
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.plotter_settings_path = router.plotter_settings_path
        router2.open_last_route()

        assert router2.exploration_plotter is True
        assert router2.exploration_mode == "Ammonia World Route"
        assert [row[0] for row in router2.route] == ["Sol", "Achenar"]
        assert router2.jumps_left == 5
        assert router2.exploration_route_data[0]["bodies"][0]["distance_to_arrival"] == 523.0

    def test_specialized_routes_restore_from_route_state_json(self, router):
        router._apply_exploration_route_data("Earth-like World Route", AMMONIA_SYSTEMS)
        router._store_plotter_settings("Earth-like World Route", {})
        router.offset = 1
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.plotter_settings_path = router.plotter_settings_path
        router2.open_last_route()

        assert router2.exploration_plotter is True
        assert router2.exploration_mode == "Earth-like World Route"
        assert router2.current_plotter_name == "Earth-like World Route"
        assert router2.offset == 1
        assert [row[0] for row in router2.route] == ["Sol", "Achenar"]

    def test_import_spansh_style_specialized_csv_uses_filename_for_mode(self, router):
        filename = os.path.join(router._tmpdir, "ammonia-sol.csv")
        with open(filename, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["System Name", "Body Name", "Distance To Arrival", "Jumps"])
            writer.writerow(["Sol", "Sol A 1", "523", "0"])
            writer.writerow(["", "Sol A 2", "1100", ""])
            writer.writerow(["Achenar", "Achenar 3", "300", "5"])

        router.plot_csv(filename)

        assert router.exploration_plotter is True
        assert router.exploration_mode == "Ammonia World Route"
        assert [row[0] for row in router.route] == ["Sol", "Achenar"]
        assert router.jumps_left == 5
        assert router.exploration_route_data[0]["bodies"][1]["distance_to_arrival"] == 1100.0
        assert router.exploration_route_data[0]["bodies"][0]["subtype"] == ""
        assert router.exploration_route_data[0]["bodies"][0]["estimated_scan_value"] == 0

    def test_import_spansh_style_specialized_csv_uses_earth_filename_for_mode(self, router):
        filename = os.path.join(router._tmpdir, "earth-sol.csv")
        with open(filename, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["System Name", "Body Name", "Distance To Arrival", "Jumps"])
            writer.writerow(["Sol", "Sol A 1", "523", "0"])
            writer.writerow(["HIP 100000", "HIP 100000 A 1", "300", "5"])

        router.plot_csv(filename)

        assert router.exploration_plotter is True
        assert router.exploration_mode == "Earth-like World Route"
        assert [row[0] for row in router.route] == ["Sol", "HIP 100000"]

    def test_import_spansh_style_specialized_csv_uses_rocky_filename_for_mode(self, router):
        filename = os.path.join(router._tmpdir, "rocky-metal-sol.csv")
        with open(filename, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["System Name", "Body Name", "Distance To Arrival", "Jumps"])
            writer.writerow(["Sol", "Sol A 1", "523", "0"])
            writer.writerow(["HIP 100000", "HIP 100000 A 1", "300", "5"])

        router.plot_csv(filename)

        assert router.exploration_plotter is True
        assert router.exploration_mode == "Rocky/HMC Route"
        assert [row[0] for row in router.route] == ["Sol", "HIP 100000"]

    def test_specialized_four_column_import_works_without_filename_hint(self, router):
        filename = os.path.join(router._tmpdir, "route.csv")
        with open(filename, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["System Name", "Body Name", "Distance To Arrival", "Jumps"])
            writer.writerow(["HIP 117776", "HIP 117776 A 1", "443.004189", "4"])
            writer.writerow(["", "HIP 117776 A 2", "563.998099", "0"])
            writer.writerow(["HIP 114072", "HIP 114072 6", "2529.728949", "3"])

        router.plot_csv(filename)

        assert router.exploration_plotter is True
        assert [row[0] for row in router.route] == ["HIP 117776", "HIP 114072"]
        assert router.jumps_left == 7
        assert router.exploration_route_data[0]["bodies"][0]["name"] == "HIP 117776 A 1"
        assert router.exploration_route_data[0]["bodies"][0]["distance_to_arrival"] == 443.004189

    def test_spansh_duplicate_zero_rows_do_not_overwrite_system_jump(self, router):
        filename = os.path.join(router._tmpdir, "riches-sol-hip.csv")
        with open(filename, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "System Name",
                "Body Name",
                "Body Subtype",
                "Is Terraformable",
                "Distance To Arrival",
                "Estimated Scan Value",
                "Estimated Mapping Value",
                "Jumps",
            ])
            writer.writerow(["HR 7658", "HR 7658 C 2", "High metal content world", "Yes", "38680.54003", "174545", "634179", "1"])
            writer.writerow(["HR 7658", "HR 7658 C 3", "High metal content world", "Yes", "39412.956128", "160182", "581993", "0"])
            writer.writerow(["HR 7658", "HR 7658 C 4", "High metal content world", "Yes", "39413.268078", "158903", "577346", "0"])

        router.plot_csv(filename)

        assert router.exploration_plotter is True
        assert router.exploration_mode == "Road to Riches"
        assert router.route == [["HR 7658", "1"]]
        assert router.jumps_left == 1

    def test_import_supports_viewer_headers_with_units(self, router):
        filename = os.path.join(router._tmpdir, "viewer-export.csv")
        with open(filename, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "System Name",
                "Body Name",
                "Body Subtype",
                "Is Terraformable",
                "Distance (Ls)",
                "Scan Value (Cr)",
                "Mapping Value (Cr)",
                "Jumps",
            ])
            writer.writerow(["Sol", "Sol A 1", "Earth-like world", "Yes", "523", "1,200,000", "3,200,000", "0"])
            writer.writerow(["Achenar", "Achenar 3", "High metal content world", "Yes", "300", "500,000", "1,500,000", "5"])

        router.plot_csv(filename)

        assert router.exploration_mode == "Road to Riches"
        assert router.exploration_route_data[0]["bodies"][0]["estimated_scan_value"] == 1200000
        assert router.exploration_route_data[0]["bodies"][0]["estimated_mapping_value"] == 3200000

    def test_exobiology_routes_preserve_landmarks_after_reload(self, router):
        router._apply_exploration_route_data("Exomastery", EXOBIOLOGY_SYSTEMS)
        router.save_all_route()

        router2 = create_router(SpanshTools)
        router2._tmpdir = router._tmpdir
        router2.plugin_dir = router._tmpdir
        router2.save_route_path = router.save_route_path
        router2.offset_file_path = router.offset_file_path
        router2.open_last_route()

        assert router2.exploration_plotter is True
        assert router2.exploration_mode == "Exomastery"
        assert [row[0] for row in router2.route] == ["Shinrarta Dezhra", "Colonia"]
        assert router2.jumps_left == 3
        first_body = router2.exploration_route_data[0]["bodies"][0]
        assert len(first_body["landmarks"]) == 2
        assert first_body["landmarks"][0]["subtype"] == "bacterium"

    def test_imports_spansh_exobiology_csv_with_value_header(self, router):
        filename = os.path.join(router._tmpdir, "spansh-exobiology.csv")
        with open(filename, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "System Name",
                "Body Name",
                "Body Subtype",
                "Distance To Arrival",
                "Landmark Subtype",
                "Value",
                "Count",
                "Jumps",
            ])
            writer.writerow([
                "LHS 3746",
                "LHS 3746 3",
                "Icy body",
                "62.378501",
                "Recepta Umbrux",
                "12934900",
                "154",
                "1",
            ])
            writer.writerow([
                "LHS 3746",
                "LHS 3746 3",
                "Icy body",
                "62.378501",
                "Stratum Tectonicas",
                "19010800",
                "45",
                "0",
            ])

        router.plot_csv(filename)

        assert router.exploration_mode == "Exomastery"
        assert [row[0] for row in router.route] == ["LHS 3746"]
        assert router.route[0][1] == "1"
        body = router.exploration_route_data[0]["bodies"][0]
        assert len(body["landmarks"]) == 2
        assert body["landmarks"][0]["subtype"] == "Recepta Umbrux"
        assert body["landmarks"][0]["value"] == 12934900


class TestRouteDisplayAndViewer:
    def test_jump_display_uses_current_waypoint_jump_count(self, router):
        router.route = [["Sol", "1"], ["HIP 8887", "3"], ["Achenar", "4"]]
        router.offset = 1

        router.compute_distances()

        assert router.dist_prev == "Number of Jumps: 3"
        assert router.dist_next == "Next waypoint jumps: 4"

    def test_csv_viewer_is_single_instance_for_same_route(self, router):
        router.route = [["Sol", "1"]]

        class FakeTopLevel:
            created = []

            def __init__(self, _parent):
                self.exists = True
                self.destroyed = False
                self.lifted = 0
                self.focused = 0
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
                self.destroyed = True
                self.exists = False

            def winfo_exists(self):
                return self.exists

            def lift(self):
                self.lifted += 1

            def focus_force(self):
                self.focused += 1

            def winfo_width(self):
                return 800

            def winfo_height(self):
                return 600

            def winfo_screenwidth(self):
                return 1920

            def after(self, *_args, **_kwargs):
                pass

            def after_cancel(self, *_args, **_kwargs):
                pass

            def bind(self, *_args, **_kwargs):
                pass

            def update_idletasks(self):
                pass

            def winfo_ismapped(self):
                return True

            def geometry(self, *_args, **_kwargs):
                pass

        class FakeSheet:
            last_instance = None

            def __init__(self, *_args, **kwargs):
                self.init_headers = kwargs.get("headers", [])
                self.init_data = kwargs.get("data", [])
                self.init_row_index = kwargs.get("row_index", [])
                FakeSheet.last_instance = self

            def grid(self, *_args, **_kwargs): pass
            def enable_bindings(self, *_args, **_kwargs): pass
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

            class RI:
                @staticmethod
                def bind(*_args, **_kwargs): pass

        class FakeMenu:
            def __init__(self, *_args, **_kwargs):
                pass

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

            def tk_popup(self, *_args, **_kwargs):
                pass

            def add_separator(self, *_args, **_kwargs):
                pass

            def add_checkbutton(self, *_args, **_kwargs):
                pass

            def tk_popup(self, *_args, **_kwargs):
                pass

        with patch("SpanshTools.core.tk.Toplevel", FakeTopLevel), \
             patch("SpanshTools.core.tk.Frame", lambda *_args, **_kwargs: DummyWidget()), \
             patch("SpanshTools.core.tk.Button", lambda *_args, **_kwargs: DummyWidget()), \
             patch("SpanshTools.core.tk.Label", lambda *_args, **_kwargs: DummyWidget()), \
             patch("SpanshTools.core.tk.Menu", FakeMenu), \
             patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel), \
             patch("SpanshTools.route_viewer.tk.Label", lambda *_args, **_kwargs: DummyWidget()), \
             patch("SpanshTools.route_viewer.tk.Menu", FakeMenu), \
             patch("SpanshTools.route_viewer.TkSheet", FakeSheet):
            router.show_csv_viewer()
            first = FakeTopLevel.created[0]
            router.show_csv_viewer()

            assert len(FakeTopLevel.created) == 1
        assert first.focused == 1

    def test_exact_viewer_uses_spansh_style_columns(self, router):
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

        class FakeTopLevel:
            created = []

            def __init__(self, _parent):
                self.exists = True
                FakeTopLevel.created.append(self)

            def title(self, *_args, **_kwargs): pass
            def resizable(self, *_args, **_kwargs): pass
            def minsize(self, *_args, **_kwargs): pass
            def protocol(self, *_args, **_kwargs): pass
            def config(self, *_args, **_kwargs): pass
            configure = config
            def grid_rowconfigure(self, *_args, **_kwargs): pass
            def grid_columnconfigure(self, *_args, **_kwargs): pass
            def destroy(self): self.exists = False
            def winfo_exists(self): return self.exists
            def lift(self): pass
            def focus_force(self): pass
            def winfo_width(self): return 800
            def winfo_height(self): return 600
            def winfo_screenwidth(self): return 1920
            def after(self, *_args, **_kwargs): pass
            def after_cancel(self, *_args, **_kwargs): pass
            def bind(self, *_args, **_kwargs): pass
            def update_idletasks(self): pass
            def winfo_ismapped(self): return True
            def geometry(self, *_args, **_kwargs): pass

        class FakeSheet:
            last_instance = None

            def __init__(self, *_args, **kwargs):
                self.init_headers = kwargs.get("headers", [])
                self.init_data = kwargs.get("data", [])
                self.init_row_index = kwargs.get("row_index", [])
                FakeSheet.last_instance = self

            def grid(self, *_args, **_kwargs): pass
            def enable_bindings(self, *_args, **_kwargs): pass
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
            def identify_region(self, *_args, **_kwargs): return ""
            def identify_row(self, *_args, **_kwargs): return None
            class RI:
                @staticmethod
                def bind(*_args, **_kwargs): pass

        class FakeMenu:
            def __init__(self, *_args, **_kwargs): pass
            def add_command(self, *_args, **_kwargs): pass
            def add_radiobutton(self, *_args, **_kwargs): pass
            def add_cascade(self, *_args, **_kwargs): pass
            def add_separator(self, *_args, **_kwargs): pass
            def add_checkbutton(self, *_args, **_kwargs): pass
            def tk_popup(self, *_args, **_kwargs): pass

        with patch("SpanshTools.core.tk.Toplevel", FakeTopLevel), \
             patch("SpanshTools.core.tk.Label", lambda *_args, **_kwargs: DummyWidget()), \
             patch("SpanshTools.core.tk.Menu", FakeMenu), \
             patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel), \
             patch("SpanshTools.route_viewer.tk.Label", lambda *_args, **_kwargs: DummyWidget()), \
             patch("SpanshTools.route_viewer.tk.Menu", FakeMenu), \
             patch("SpanshTools.route_viewer.TkSheet", FakeSheet):
            router.show_csv_viewer()

        sheet = FakeSheet.last_instance
        # headers excludes "Done" column (shown in row_index)
        assert tuple(["Done"] + sheet.init_headers) == (
            "Done",
            "System Name",
            "Distance (Ly)",
            "Remaining (Ly)",
            "Jumps Left",
            "Fuel Left (tonnes)",
            "Fuel Used (tonnes)",
            "Refuel?",
            "Neutron",
        )
        # row_index holds the Done column, init_data holds the rest
        assert [sheet.init_row_index[0]] + sheet.init_data[0] == ["□", "Sol", "0.00", "22,000.47", 1, "32.00", "0.00", "Yes", ""]
        assert [sheet.init_row_index[1]] + sheet.init_data[1] == ["□", "Ugrashtim", "85.92", "21,975.62", 0, "26.84", "5.16", "", ""]

    def test_riches_viewer_uses_short_body_headers(self, router):
        router._apply_exploration_route_data("Road to Riches", RICHES_SYSTEMS)

        class FakeTopLevel:
            created = []

            def __init__(self, _parent):
                self.exists = True
                FakeTopLevel.created.append(self)

            def title(self, *_args, **_kwargs): pass
            def resizable(self, *_args, **_kwargs): pass
            def minsize(self, *_args, **_kwargs): pass
            def protocol(self, *_args, **_kwargs): pass
            def config(self, *_args, **_kwargs): pass
            configure = config
            def grid_rowconfigure(self, *_args, **_kwargs): pass
            def grid_columnconfigure(self, *_args, **_kwargs): pass
            def destroy(self): self.exists = False
            def winfo_exists(self): return self.exists
            def lift(self): pass
            def focus_force(self): pass
            def winfo_width(self): return 800
            def winfo_height(self): return 600
            def winfo_screenwidth(self): return 1920
            def after(self, *_args, **_kwargs): pass
            def after_cancel(self, *_args, **_kwargs): pass
            def bind(self, *_args, **_kwargs): pass
            def update_idletasks(self): pass
            def winfo_ismapped(self): return True
            def geometry(self, *_args, **_kwargs): pass

        class FakeSheet:
            last_instance = None

            def __init__(self, *_args, **kwargs):
                self.init_headers = kwargs.get("headers", [])
                self.init_data = kwargs.get("data", [])
                self.init_row_index = kwargs.get("row_index", [])
                FakeSheet.last_instance = self

            def grid(self, *_args, **_kwargs): pass
            def enable_bindings(self, *_args, **_kwargs): pass
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
            def identify_region(self, *_args, **_kwargs): return ""
            def identify_row(self, *_args, **_kwargs): return None
            class RI:
                @staticmethod
                def bind(*_args, **_kwargs): pass

        class FakeMenu:
            def __init__(self, *_args, **_kwargs): pass
            def add_command(self, *_args, **_kwargs): pass
            def add_radiobutton(self, *_args, **_kwargs): pass
            def add_cascade(self, *_args, **_kwargs): pass
            def add_separator(self, *_args, **_kwargs): pass
            def add_checkbutton(self, *_args, **_kwargs): pass
            def tk_popup(self, *_args, **_kwargs): pass

        with patch("SpanshTools.core.tk.Toplevel", FakeTopLevel), \
             patch("SpanshTools.core.tk.Label", lambda *_args, **_kwargs: DummyWidget()), \
             patch("SpanshTools.core.tk.Menu", FakeMenu), \
             patch("SpanshTools.route_viewer.tk.Toplevel", FakeTopLevel), \
             patch("SpanshTools.route_viewer.tk.Label", lambda *_args, **_kwargs: DummyWidget()), \
             patch("SpanshTools.route_viewer.tk.Menu", FakeMenu), \
             patch("SpanshTools.route_viewer.TkSheet", FakeSheet):
            router.show_csv_viewer()

        sheet = FakeSheet.last_instance
        assert tuple(["Done"] + sheet.init_headers) == (
            "Done",
            "System Name",
            "Name",
            "Subtype",
            "Terra",
            "Distance (Ls)",
            "Scan Value",
            "Mapping Value",
            "Jumps",
        )


class TestNeutronPlotter:
    def test_neutron_payload_uses_clamped_range_and_selected_multiplier(self, router):
        router.hide_error = MagicMock()
        router.show_error = MagicMock()
        router.enable_plot_gui = MagicMock()
        router.source_ac = DummyAC("Sol", "Source System")
        router.dest_ac = DummyAC("Achenar", "Destination System")
        router.range_entry = DummyEntry("250", 0, 100)
        router.range_entry.placeholder = "Range (LY)"
        router.efficiency_entry = DummyEntry("60", 0, 100)
        router.efficiency_slider = MagicMock(get=MagicMock(return_value=60))
        router.neutron_efficiency_var = MagicMock(set=MagicMock())
        router.supercharge_multiplier.set(6)

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router.plot_route()

        params = thread_cls.call_args.kwargs["args"][0]
        assert params["range"] == 100.0
        assert params["supercharge_multiplier"] == 6

    def test_suggest_jump_range_uses_ship_data(self, router):
        router.ship_fsd_data = {
            "optimal_mass": 1050.0,
            "max_fuel_per_jump": 5.0,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "unladen_mass": 400.0,
            "tank_size": 32.0,
            "reserve_size": 0.63,
            "range_boost": 10.5,
        }

        with patch("SpanshTools.core.monitor.state", {"SystemName": "Sol"}):
            value = router._suggest_jump_range()

        assert round(value, 2) == 39.01

    def test_suggest_jump_range_prefers_dashboard_fuel(self, router):
        router.ship_fsd_data = {
            "optimal_mass": 1050.0,
            "max_fuel_per_jump": 5.0,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "unladen_mass": 400.0,
            "tank_size": 32.0,
            "reserve_size": 0.63,
            "range_boost": 10.5,
        }
        router.current_fuel_main = 4.0
        router.current_fuel_reservoir = 0.63

        value = router._suggest_jump_range()

        assert round(value, 2) == 40.94

    def test_suggest_jump_range_does_not_use_unladen_or_max_fallback(self, router):

        with patch("SpanshTools.core.monitor.state", {"SystemName": "Sol", "UnladenJumpRange": 61.2, "MaxJumpRange": 64.8}):
            value = router._suggest_jump_range()

        assert value is None


class TestPlotterSettings:
    def test_settings_are_restored_by_requested_planner(self, router):
        router._store_plotter_settings("Exomastery", {"range": "56"})
        router.current_plotter_name = "Road to Riches"

        assert router._settings_for_planner("Exomastery") == {"range": "56"}


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
        router._fc_tritium_fuel = DummyEntry("1200", minimum=0, maximum=1000)
        router._fc_tritium_market = DummyEntry("70000", minimum=0, maximum=60000)
        router._fc_carrier_type = MagicMock(get=MagicMock(return_value="squadron"))

        with patch("SpanshTools.core.threading.Thread") as thread_cls:
            router._plot_fleet_carrier_route()

        params = thread_cls.call_args.kwargs["args"][0]
        assert params["source"] == "Sol"
        assert params["destinations"] == ["Achenar", "Colonia"]
        assert params["refuel_destinations"] == ["Colonia"]
        assert params["carrier_type"] == "squadron"
        assert params["used_capacity"] == 60000
        assert params["determine_required_fuel"] is False
        assert params["tritium_fuel"] == 1000
        assert params["tritium_market"] == 60000

    def test_cancel_fleet_carrier_plot_closes_window_and_resets_state(self, router):
        router._is_plotting = MagicMock(return_value=True)
        router._mark_plot_stopped = MagicMock()
        router._invalidate_plot_token = MagicMock()
        router._set_main_controls_enabled = MagicMock()
        router._set_plotter_windows_enabled = MagicMock()
        router._close_plotter_window = MagicMock()

        router._cancel_fleet_carrier_plot()

        router._mark_plot_stopped.assert_called_once_with(cancelled=True)
        router._invalidate_plot_token.assert_called_once()
        router._set_main_controls_enabled.assert_called_once_with(True)
        router._set_plotter_windows_enabled.assert_called_once_with(True)
        router._close_plotter_window.assert_called_once()


def test_riches_body_done_does_not_overwrite_system_done(router):

    systems = router._build_riches_systems_from_rows([
        {
            "Done": "□",
            router.system_header: "Sol",
            router.jumps_header: "2",
        },
        {
            "Done": "■",
            router.system_header: "",
            "Name": "Sol A 1",
            "Subtype": "Earth-like world",
        },
    ])

    assert systems[0]["done"] is False
    assert systems[0]["bodies"][0]["done"] is True


def test_exobiology_body_done_does_not_overwrite_system_done(router):

    systems = router._build_exobiology_systems_from_rows([
        {
            "Done": "□",
            router.system_header: "Sol",
            router.jumps_header: "2",
        },
        {
            "Done": "■",
            router.system_header: "",
            router.bodyname_header: "Sol A 1",
            router.bodysubtype_header: "Rocky body",
            "Landmark Subtype": "Bacterium Informem",
            "Count": "3",
            "Landmark Value": "1000",
        },
    ])

    assert systems[0]["done"] is False
    assert systems[0]["bodies"][0]["done"] is True
