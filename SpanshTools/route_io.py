"""Route import/export and state persistence mixin."""

import csv
import io
import json
import os
import re
import tempfile
import tkinter.filedialog as filedialog

from config import config
from .constants import (
    RICHES_CSV_HEADER,
    ROUTE_PLANNERS,
    SPECIALIZED_RICHES_CSV_HEADER,
    SPANSH_SPECIALIZED_RICHES_CSV_HEADER,
    PLUGIN_SPECIALIZED_RICHES_CSV_HEADER,
    EXOBIOLOGY_CSV_HEADER,
    LEGACY_EXOBIOLOGY_CSV_HEADER_V2,
    LEGACY_RICHES_CSV_HEADER,
    LEGACY_RICHES_CSV_HEADER_V2,
    LEGACY_EXOBIOLOGY_CSV_HEADER,
    logger,
)


class RouteIOMixin:
    """Mixin providing route import/export/persistence for SpanshTools."""

    _EXPORT_NAME_SANITIZER = re.compile(r'[\\\\/:*?\"<>|]+')
    _IMPORT_DIR_CONFIG_KEY = "spansh_last_import_dir"
    _EXPORT_DIR_CONFIG_KEY = "spansh_last_export_dir"

    def _route_state_path(self):
        return os.path.join(self.plugin_dir, self.route_state_filename)


    def _dialog_initial_directory(self, kind):
        key = (
            self._IMPORT_DIR_CONFIG_KEY
            if kind == "import"
            else self._EXPORT_DIR_CONFIG_KEY
        )
        try:
            saved_path = config.get_str(key, default="")
        except Exception:
            saved_path = ""
        if saved_path and os.path.isdir(saved_path):
            return saved_path
        return os.path.expanduser("~")


    def _remember_dialog_directory(self, kind, filename):
        directory = os.path.dirname(os.path.abspath(filename or ""))
        if not directory or not os.path.isdir(directory):
            return
        key = (
            self._IMPORT_DIR_CONFIG_KEY
            if kind == "import"
            else self._EXPORT_DIR_CONFIG_KEY
        )
        try:
            config.set(key, directory)
        except Exception:
            pass


    def _write_json_atomic(self, path, payload, *, prefix):
        temp_path = None
        fd = None
        try:
            fd, temp_path = tempfile.mkstemp(
                prefix=prefix,
                suffix=".json",
                dir=os.path.dirname(path),
                text=True,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
            if temp_path:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise


    def _resolve_saved_route_type(self, payload):
        saved_route_type = payload.get("route_type")
        if saved_route_type in ("exact", "galaxy", "fleet_carrier", "exploration", "neutron", "simple"):
            return saved_route_type
        if bool(payload.get("exploration_plotter", False)):
            return "exploration"
        if bool(payload.get("fleetcarrier", False)):
            return "fleet_carrier"
        if bool(payload.get("galaxy", False)):
            return "galaxy"
        if bool(payload.get("exact_plotter", False)):
            return "exact"
        if str(payload.get("planner", "")).strip() == "Neutron Plotter":
            return "neutron"
        if payload.get("route"):
            return "simple"
        return None


    def _restore_route_done_values(self, payload):
        route_done = [bool(value) for value in payload.get("route_done", [])]
        if self.route_type == "exploration" and self.exploration_route_data:
            return self._exploration_system_done_values()
        if self.route_type == "exact" and self.exact_route_data:
            return [bool(jump.get("done", False)) for jump in self.exact_route_data]
        if self.route_type == "fleet_carrier" and self.fleet_carrier_data:
            return [bool(jump.get("done", False)) for jump in self.fleet_carrier_data]
        return route_done


    def _finalize_imported_route(self, *, sync_refuel=True):
        if not self.route:
            return
        if not self._restore_offset_from_done_progress():
            self._reset_offset_from_current_system()
        self._recalculate_jumps_left_from_offset()
        if sync_refuel:
            self.pleaserefuel = self._route_refuel_required_at(self.offset)
        self.compute_distances()
        if self._route_complete_for_ui():
            self.jumps_left = 0
        else:
            self.copy_waypoint()
        self.update_gui()
        self._update_overlay()
        self.save_all_route()


    def _serialize_route_state(self):
        if not self.route:
            return None
        return {
            "version": 1,
            "planner": self._current_route_planner_name(),
            "route_type": self.route_type,
            "offset": int(self.offset or 0),
            "jumps_left": int(self.jumps_left or 0),
            "route": [list(row) for row in self.route],
            "route_done": self._route_done_values(),
            # Legacy boolean fields kept for backwards compatibility
            "exploration_plotter": bool(self.exploration_plotter),
            "exploration_mode": self.exploration_mode,
            "exploration_route_data": self.exploration_route_data,
            "fleetcarrier": bool(self.fleetcarrier),
            "fleet_carrier_data": self.fleet_carrier_data,
            "galaxy": bool(self.galaxy),
            "exact_plotter": bool(self.exact_plotter),
            "exact_route_data": self.exact_route_data,
        }


    def _restore_offset_from_done_progress(self):
        if self.exploration_plotter and self.exploration_route_data:
            return self._restore_exploration_offset_from_done_progress()
        done_values = self._route_done_values()
        if not done_values:
            return False
        last_done_index = None
        for index, done in enumerate(done_values[:len(self.route)]):
            if done:
                last_done_index = index
        if last_done_index is None:
            return False
        if last_done_index >= len(self.route) - 1:
            self.offset = max(0, len(self.route) - 1)
            self.next_stop = ""
            return True
        next_index = min(last_done_index + 1, max(0, len(self.route) - 1))
        self.offset = next_index
        self.next_stop = self._route_name_at(self.offset, self._route_source_name(""))
        return True


    def _restore_exploration_offset_from_done_progress(self):
        visible_rows = [
            row for row in self._exploration_view_rows()
            if not row.get("is_total")
        ]
        if not visible_rows:
            return False

        last_done_row_index = None
        last_done_route_index = None
        for row_index, row in enumerate(visible_rows):
            if row.get("no_done"):
                continue
            values = row.get("values", [])
            if values and self._is_done_value(values[0]):
                last_done_row_index = row_index
                last_done_route_index = self._safe_int(row.get("route_index"), None)

        if last_done_row_index is None:
            return False

        target_index = None
        for row in visible_rows[last_done_row_index + 1:]:
            route_index = self._safe_int(row.get("route_index"), None)
            if route_index is None or route_index == last_done_route_index:
                continue
            target_index = route_index
            break

        if target_index is None:
            if last_done_route_index == len(self.route) - 1:
                self.offset = max(0, len(self.route) - 1)
                self.next_stop = ""
                return True
            target_index = last_done_route_index

        if target_index is None or not (0 <= target_index < len(self.route)):
            return False

        self.offset = target_index
        self.next_stop = self._route_name_at(self.offset, self._route_source_name(""))
        return True


    def _save_route_state(self):
        route_state_path = self._route_state_path()
        payload = self._serialize_route_state()
        try:
            if not payload:
                os.remove(route_state_path)
                return
        except FileNotFoundError:
            return
        except Exception:
            return

        try:
            self._write_json_atomic(
                route_state_path,
                payload,
                prefix=".route_state.",
            )
        except Exception as e:
            logger.debug(f"Could not save route state: {e}")


    def _load_route_state(self):
        try:
            with open(self._route_state_path(), "r") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        except Exception as e:
            logger.debug(f"Could not load route state: {e}")
            return None

        if not isinstance(payload, dict):
            return None
        route = payload.get("route", [])
        if not isinstance(route, list) or not route:
            return None
        return payload


    def _apply_route_state(self, payload):
        self.route = [list(row) for row in payload.get("route", []) if isinstance(row, (list, tuple))]
        self._invalidate_route_rows()
        self.exploration_mode = payload.get("exploration_mode") or None
        self.exploration_route_data = payload.get("exploration_route_data", []) if isinstance(payload.get("exploration_route_data", []), list) else []
        self.fleet_carrier_data = payload.get("fleet_carrier_data", []) if isinstance(payload.get("fleet_carrier_data", []), list) else []
        self.exact_route_data = payload.get("exact_route_data", []) if isinstance(payload.get("exact_route_data", []), list) else []
        self.route_type = self._resolve_saved_route_type(payload)
        planner = str(payload.get("planner", "")).strip()
        if not planner:
            planner = self._current_route_planner_name()
        self.current_plotter_name = planner or None
        self.offset = self._safe_int(payload.get("offset"), 0)
        self.route_done = self._restore_route_done_values(payload)
        self._sync_route_done()


    def _load_plotter_settings(self):
        try:
            with open(self.plotter_settings_path, 'r') as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                self._plotter_settings = {}
                return
            planners = payload.get("planners")
            normalized_planners = {}
            if isinstance(planners, dict):
                normalized_planners = {
                    str(name): dict(settings or {})
                    for name, settings in planners.items()
                    if isinstance(name, str) and isinstance(settings, dict)
                }
            planner = str(payload.get("planner", "")).strip()
            settings = dict(payload.get("settings", {}) or {}) if isinstance(payload.get("settings", {}), dict) else {}
            if planner and settings and planner not in normalized_planners:
                normalized_planners[planner] = dict(settings)
            normalized_payload = dict(payload)
            if normalized_planners:
                normalized_payload["planners"] = normalized_planners
            self._plotter_settings = normalized_payload
        except (FileNotFoundError, json.JSONDecodeError):
            self._plotter_settings = {}
        except Exception as exc:
            logger.debug(f"Could not load plotter settings: {exc}")
            self._plotter_settings = {}


    def _save_plotter_settings(self):
        try:
            if self._plotter_settings:
                self._write_json_atomic(
                    self.plotter_settings_path,
                    self._plotter_settings,
                    prefix=".plotter_settings.",
                )
            else:
                os.remove(self.plotter_settings_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug(f"Could not save plotter settings: {e}")


    def _store_plotter_settings(self, planner, settings):
        planners = {}
        existing = self._plotter_settings.get("planners", {})
        if isinstance(existing, dict):
            planners.update({
                str(name): dict(values or {})
                for name, values in existing.items()
                if isinstance(name, str) and isinstance(values, dict)
            })
        planners[str(planner)] = dict(settings or {})
        self._plotter_settings = {
            "planner": planner,
            "settings": dict(settings or {}),
            "planners": planners,
        }
        self._save_plotter_settings()


    def _settings_for_planner(self, planner):
        planners = self._plotter_settings.get("planners", {})
        if isinstance(planners, dict) and planner in planners:
            return dict(planners.get(planner, {}) or {})
        if self._plotter_settings.get("planner") == planner:
            return dict(self._plotter_settings.get("settings", {}) or {})
        return {}


    def _set_current_plotter(self, planner):
        self.current_plotter_name = planner


    def _clear_plotter_settings(self):
        self.current_plotter_name = None
        self._plotter_settings = {}
        try:
            os.remove(self.plotter_settings_path)
        except Exception:
            pass


    def _is_specialized_exploration_mode(self, mode):
        return mode in {"Ammonia World Route", "Earth-like World Route", "Rocky/HMC Route"}


    def _planner_from_filename(self, filename):
        lower_name = os.path.basename(filename).lower()
        if "ammonia" in lower_name:
            return "Ammonia World Route"
        if "earth" in lower_name:
            return "Earth-like World Route"
        if "rocky" in lower_name or "metal" in lower_name:
            return "Rocky/HMC Route"
        if "exobiology" in lower_name or "exomastery" in lower_name:
            return "Exomastery"
        if "riches" in lower_name:
            return "Road to Riches"
        return None


    def _sanitize_export_name_token(self, value, default="undefined"):
        token = str(value or "").strip() or default
        return self._EXPORT_NAME_SANITIZER.sub("_", token)


    def _export_filename_prefix(self):
        if self.route_type in ("exact", "galaxy"):
            return "exact-plotter"
        if self.route_type == "fleet_carrier":
            return "fleet-carrier"
        if self.route_type == "neutron":
            return "neutron"
        if self.route_type == "exploration":
            if self.exploration_mode == "Exomastery":
                return "exobiology"
            if self.exploration_mode == "Road to Riches":
                return "riches"
            if self.exploration_mode == "Ammonia World Route":
                return "ammonia"
            if self.exploration_mode == "Earth-like World Route":
                return "earth"
            if self.exploration_mode == "Rocky/HMC Route":
                return "rocky-metal"
            return "exploration"
        return "route"


    def _export_filename_tokens(self):
        prefix = self._export_filename_prefix()
        source = self._route_source_name("")
        destination = self._route_destination_name("")

        if self.route_type in ("exact", "galaxy") and self._exact_settings:
            source = self._exact_settings.get("source", source)
            destination = self._exact_settings.get("destination", destination)
        elif self.route_type == "neutron":
            settings = self._settings_for_planner("Neutron Plotter")
            source = settings.get("source", source)
            destination = settings.get("destination", destination)
        elif self.route_type == "exploration":
            settings = self._settings_for_planner(self.exploration_mode)
            source = settings.get("source", source)
            destination = settings.get("destination", destination)
        elif self.route_type == "fleet_carrier":
            settings = self._settings_for_planner("Fleet Carrier Router")
            source = settings.get("source", source)
            destinations = settings.get("destinations", []) if isinstance(settings.get("destinations", []), list) else []
            if destinations:
                destination = destinations[-1]

        return [
            prefix,
            self._sanitize_export_name_token(source, default="undefined"),
            self._sanitize_export_name_token(destination, default="undefined"),
        ]


    def _default_export_filename(self, extension):
        ext = extension if str(extension).startswith(".") else f".{extension}"
        return f"{'-'.join(self._export_filename_tokens())}{ext}"


    def _infer_exploration_mode(self, headerline, filename):
        inferred_from_name = self._planner_from_filename(filename)
        saved_planner = self._plotter_settings.get("planner")
        is_saved_route = os.path.abspath(filename) == os.path.abspath(self.save_route_path)
        current_planner = ""
        try:
            current_planner = self.planner_var.get()
        except Exception:
            pass

        is_specialized_header = headerline in (
            SPECIALIZED_RICHES_CSV_HEADER,
            SPANSH_SPECIALIZED_RICHES_CSV_HEADER,
            PLUGIN_SPECIALIZED_RICHES_CSV_HEADER,
        )

        if is_specialized_header:
            if inferred_from_name in ("Ammonia World Route", "Earth-like World Route", "Rocky/HMC Route"):
                return inferred_from_name
            if current_planner in ("Ammonia World Route", "Earth-like World Route", "Rocky/HMC Route"):
                return current_planner
            if saved_planner in ("Ammonia World Route", "Earth-like World Route", "Rocky/HMC Route"):
                return saved_planner
            return "Ammonia World Route"

        if "Landmark Subtype" in headerline and (
            "Landmark Value" in headerline or "Value" in headerline
        ):
            return inferred_from_name or "Exomastery"

        if inferred_from_name in ROUTE_PLANNERS:
            return inferred_from_name

        if (
            is_saved_route
            and saved_planner in ("Road to Riches", "Ammonia World Route", "Earth-like World Route", "Rocky/HMC Route")
        ):
            return saved_planner

        return "Road to Riches"


    def _apply_exploration_route_data(self, mode, systems):
        self._reset_exploration_state()

        self.fleetcarrier = False
        self.galaxy = False
        self.exact_plotter = False
        self.exact_route_data = []
        self.fleet_carrier_data = []
        self.exploration_plotter = True
        self.exploration_mode = mode
        self.exploration_route_data = systems
        self._set_current_plotter(mode)
        self.route = []
        self._invalidate_route_rows()
        self.route_done = []
        self.jumps_left = 0

        for system in systems:
            system_name = system.get("name", "")
            jumps = self._safe_int(system.get("jumps"), 1)
            self.route.append([system_name, str(jumps)])
            self.route_done.append(False)
            self.jumps_left += jumps
        self._sync_runtime_route_rows()


    def _build_riches_systems_from_rows(self, rows, specialized=False):
        systems = []
        current = None
        current_system_name = ""

        for row in rows:
            done_value = (self._csv_row_value(row, "Done") or "").strip()
            if done_value.lower() == "total":
                continue
            system_name = (self._csv_row_value(row, self.system_header) or "").strip()
            if system_name.lower() == "total":
                continue
            if system_name:
                current_system_name = system_name
            else:
                system_name = current_system_name
            if not system_name:
                continue

            jumps_value = self._csv_row_value(row, self.jumps_header)
            if current is None or current["name"] != system_name:
                jumps = self._safe_int(jumps_value, 1)
                current = {
                    "name": system_name,
                    "jumps": jumps,
                    "done": self._is_done_value(self._csv_row_value(row, "Done")),
                    "bodies": [],
                }
                systems.append(current)
            elif jumps_value not in (None, "", []):
                parsed_jumps = self._safe_int(jumps_value, current["jumps"])
                if parsed_jumps > 0 or current["jumps"] in (None, "", 0):
                    current["jumps"] = parsed_jumps

            body_name = (self._csv_row_value(row, self.bodyname_header, "Name") or "").strip()
            if specialized:
                if not body_name:
                    continue
                current["bodies"].append({
                    "done": self._is_done_value(self._csv_row_value(row, "Done")),
                    "name": body_name,
                    "subtype": "",
                    "is_terraformable": False,
                    "distance_to_arrival": self._safe_float(
                        self._csv_row_value(row, "Distance (Ls)", "Distance To Arrival", "Distance"),
                        0,
                    ),
                    "estimated_scan_value": 0,
                    "estimated_mapping_value": 0,
                })
            else:
                body_subtype = (self._csv_row_value(row, self.bodysubtype_header, "Subtype") or "").strip()
                if not body_name and not body_subtype:
                    continue
                current["bodies"].append({
                    "done": self._is_done_value(self._csv_row_value(row, "Done")),
                    "name": body_name,
                    "subtype": body_subtype,
                    "is_terraformable": self._is_terraformable_value(
                        self._csv_row_value(row, "Is Terraformable", "Terra")
                    ),
                    "distance_to_arrival": self._safe_float(
                        self._csv_row_value(row, "Distance (Ls)", "Distance To Arrival", "Distance"),
                        0,
                    ),
                    "estimated_scan_value": self._safe_int(
                        self._csv_row_value(row, "Scan Value", "Scan Value (Cr)", "Estimated Scan Value"),
                        0,
                    ),
                    "estimated_mapping_value": self._safe_int(
                        self._csv_row_value(row, "Mapping Value", "Mapping Value (Cr)", "Estimated Mapping Value"),
                        0,
                    ),
                })

        return systems


    def _build_exobiology_systems_from_rows(self, rows):
        systems = []
        current_system = None
        current_body = None
        current_system_name = ""

        for row in rows:
            done_value = (self._csv_row_value(row, "Done") or "").strip()
            if done_value.lower() == "total":
                continue
            system_name = (self._csv_row_value(row, self.system_header) or "").strip()
            if system_name.lower() == "total":
                continue
            if system_name:
                current_system_name = system_name
            else:
                system_name = current_system_name
            if not system_name:
                continue

            jumps_value = self._csv_row_value(row, self.jumps_header)
            if current_system is None or current_system["name"] != system_name:
                jumps = self._safe_int(jumps_value, 1)
                current_system = {
                    "name": system_name,
                    "jumps": jumps,
                    "done": self._is_done_value(self._csv_row_value(row, "Done")),
                    "bodies": [],
                }
                systems.append(current_system)
                current_body = None
            elif jumps_value not in (None, "", []):
                jumps = self._safe_int(jumps_value, current_system["jumps"])
                if jumps:
                    current_system["jumps"] = jumps

            body_name = (self._csv_row_value(row, self.bodyname_header, "Name") or "").strip()
            body_subtype = (self._csv_row_value(row, self.bodysubtype_header, "Subtype") or "").strip()
            if body_name or body_subtype:
                if (
                    current_body is None
                    or current_body.get("name") != body_name
                    or current_body.get("subtype") != body_subtype
                ):
                    current_body = {
                        "name": body_name,
                        "subtype": body_subtype,
                        "distance_to_arrival": self._safe_float(
                            self._csv_row_value(row, "Distance (LS)", "Distance (Ls)", "Distance To Arrival", "Distance"),
                            0,
                        ),
                        "landmarks": [],
                        "done": self._is_done_value(self._csv_row_value(row, "Done")),
                    }
                    current_system["bodies"].append(current_body)
                elif self._csv_row_value(row, "Done") not in (None, "", []):
                    current_body["done"] = self._is_done_value(self._csv_row_value(row, "Done"))

            if current_body is None:
                continue

            landmark_subtype = (self._csv_row_value(row, "Landmark Subtype") or "").strip()
            landmark_count = self._csv_row_value(row, "Landmark Count", "Count")
            landmark_value = self._csv_row_value(
                row,
                "Landmark Value",
                "Landmark Value (Cr)",
                "Value",
            )
            if not landmark_subtype and landmark_count in ("", None) and landmark_value in ("", None):
                continue

            current_body["landmarks"].append({
                "subtype": landmark_subtype,
                "count": self._safe_int(landmark_count, 0),
                "value": self._safe_int(landmark_value, 0),
                "done": self._is_done_value(self._csv_row_value(row, "Done")),
            })

        return systems


    def _exploration_view_rows(self):
        rows = []
        if self.exploration_mode == "Exomastery":
            total_systems = 0
            total_bodies = 0
            total_landmarks = 0
            total_value = 0
            total_jumps = 0
            route_index = -1
            for system in self.exploration_route_data:
                system_name = system.get("name", "")
                jumps = self._safe_int(system.get("jumps", 1), 1)
                total_jumps += jumps
                total_systems += 1
                route_index += 1
                bodies = system.get("bodies", [])
                show_system = True
                if not bodies:
                    rows.append({
                        "values": ["", system_name, "", "", "", "", "", "", jumps],
                        "route_index": route_index,
                        "is_total": False,
                        "no_done": True,
                    })
                    continue
                for body in bodies:
                    total_bodies += 1
                    landmarks = body.get("landmarks", [])
                    if not landmarks:
                        rows.append({
                            "values": [
                                self._done_cell_value(body.get("done", False)),
                                system_name if show_system else "",
                                body.get("name", ""),
                                body.get("subtype", ""),
                                self._format_whole_number(body.get("distance_to_arrival"), ""),
                                "",
                                "",
                                self._format_whole_number("", ""),
                                jumps if show_system else "",
                            ],
                            "route_index": route_index,
                            "is_total": False,
                            "no_done": False,
                        })
                        show_system = False
                        continue
                    show_body = True
                    for landmark in landmarks:
                        total_landmarks += 1
                        total_value += self._safe_int(landmark.get("value", 0), 0)
                        rows.append({
                            "values": [
                                self._done_cell_value(landmark.get("done", False)),
                                system_name if show_system else "",
                                body.get("name", "") if show_body else "",
                                body.get("subtype", "") if show_body else "",
                                self._format_whole_number(body.get("distance_to_arrival"), "") if show_body else "",
                                landmark.get("subtype", ""),
                                landmark.get("count", ""),
                                self._format_whole_number(landmark.get("value", ""), ""),
                                jumps if show_system else "",
                            ],
                            "route_index": route_index,
                            "is_total": False,
                            "no_done": False,
                        })
                        show_system = False
                        show_body = False
            if rows:
                rows.append({
                    "values": [
                        "Total",
                        f"{self._format_whole_number(total_systems)} systems",
                        f"{self._format_whole_number(total_bodies)} bodies",
                        "",
                        "",
                        f"{self._format_whole_number(total_landmarks)} landmarks",
                        "",
                        self._format_whole_number(total_value, ""),
                        total_jumps,
                    ],
                    "route_index": -1,
                    "is_total": True,
                    "no_done": True,
                })
        else:
            total_scan = 0
            total_mapping = 0
            total_jumps = 0
            total_systems = 0
            total_bodies = 0
            route_index = -1
            for system in self.exploration_route_data:
                system_name = system.get("name", "")
                jumps = self._safe_int(system.get("jumps", 1), 1)
                total_jumps += jumps
                total_systems += 1
                route_index += 1
                bodies = system.get("bodies", [])
                show_system = True
                if not bodies:
                    if self._is_specialized_exploration_mode(self.exploration_mode):
                        rows.append({
                            "values": ["", system_name, "", "", jumps],
                            "route_index": route_index,
                            "is_total": False,
                            "no_done": True,
                        })
                    else:
                        rows.append({
                            "values": ["", system_name, "", "", "", "", "", "", jumps],
                            "route_index": route_index,
                            "is_total": False,
                            "no_done": True,
                        })
                    continue
                for body in bodies:
                    total_bodies += 1
                    total_scan += self._safe_int(body.get("estimated_scan_value", 0), 0)
                    total_mapping += self._safe_int(body.get("estimated_mapping_value", 0), 0)
                    if self._is_specialized_exploration_mode(self.exploration_mode):
                        rows.append({
                            "values": [
                                self._done_cell_value(body.get("done", False)),
                                system_name if show_system else "",
                                body.get("name", ""),
                                self._format_whole_number(body.get("distance_to_arrival"), ""),
                                jumps if show_system else "",
                            ],
                            "route_index": route_index,
                            "is_total": False,
                            "no_done": False,
                        })
                    else:
                        rows.append({
                            "values": [
                                self._done_cell_value(body.get("done", False)),
                                system_name if show_system else "",
                                body.get("name", ""),
                                body.get("subtype", ""),
                                self._terraformable_display_value("Yes" if body.get("is_terraformable") else "No") if self.exploration_mode == "Road to Riches" else ("Yes" if body.get("is_terraformable") else "No"),
                                self._format_whole_number(body.get("distance_to_arrival"), ""),
                                self._format_whole_number(body.get("estimated_scan_value", ""), ""),
                                self._format_whole_number(body.get("estimated_mapping_value", ""), ""),
                                jumps if show_system else "",
                            ],
                            "route_index": route_index,
                            "is_total": False,
                            "no_done": False,
                        })
                    show_system = False
            if rows:
                if self._is_specialized_exploration_mode(self.exploration_mode):
                    rows.append({
                        "values": [
                            "Total",
                            f"{self._format_whole_number(total_systems)} systems",
                            f"{self._format_whole_number(total_bodies)} bodies",
                            "",
                            total_jumps,
                        ],
                        "route_index": -1,
                        "is_total": True,
                        "no_done": True,
                    })
                else:
                    rows.append({
                        "values": [
                            "Total",
                            f"{self._format_whole_number(total_systems)} systems",
                            f"{self._format_whole_number(total_bodies)} bodies",
                            "",
                            "",
                            "",
                            self._format_whole_number(total_scan, ""),
                            self._format_whole_number(total_mapping, ""),
                            total_jumps,
                        ],
                        "route_index": -1,
                        "is_total": True,
                        "no_done": True,
                    })
        return rows


    def _apply_neutron_route_rows(self, neutron_rows, *, settings=None):
        self._set_current_plotter("Neutron Plotter")
        self.route_type = "neutron"
        self.exact_plotter = False
        self.fleetcarrier = False
        self.galaxy = False
        self.exact_route_data = []
        self.fleet_carrier_data = []
        self._reset_exploration_state()
        self.route = []
        self._invalidate_route_rows()
        self.route_done = []
        self.jumps_left = 0

        for row in neutron_rows:
            system = row.get("system", "")
            jumps = str(row.get("jumps", ""))
            distance_to_arrival = row.get("distance_to_arrival", "")
            distance_remaining = row.get("distance_remaining", "")
            neutron_star = "Yes" if str(row.get("neutron", "")).strip().lower() == "yes" else "No"

            self.route.append([system, jumps, distance_to_arrival, distance_remaining, neutron_star])
            self.route_done.append(bool(row.get("done", False)))
            try:
                self.jumps_left += int(jumps)
            except Exception:
                pass

        if settings is not None:
            self._store_plotter_settings("Neutron Plotter", settings)


    def _infer_fleet_waypoint_names(self, *, source="", destinations=None, settings=None):
        waypoint_names = {
            (source or "").strip().lower(),
            *[(name or "").strip().lower() for name in (destinations or [])],
        }
        waypoint_names.discard("")
        if waypoint_names:
            return waypoint_names

        settings = settings or {}
        waypoint_names = {
            (settings.get("source", "") or "").strip().lower(),
            *[(name or "").strip().lower() for name in settings.get("destinations", [])],
        }
        waypoint_names.discard("")
        return waypoint_names


    def _apply_fleet_waypoint_flags(self, jumps, *, source="", destinations=None, settings=None):
        waypoint_names = self._infer_fleet_waypoint_names(
            source=source,
            destinations=destinations,
            settings=settings,
        )
        if waypoint_names:
            for jump in jumps:
                jump["is_waypoint"] = (jump.get("name", "") or "").strip().lower() in waypoint_names
            return

        normalized_names = [
            (jump.get("name", "") or "").strip().lower()
            for jump in jumps
        ]
        name_counts = {}
        for name in normalized_names:
            if not name:
                continue
            name_counts[name] = name_counts.get(name, 0) + 1
        duplicate_names = {
            name for name, count in name_counts.items()
            if count > 1
        }
        for index, jump in enumerate(jumps):
            name = (jump.get("name", "") or "").strip().lower()
            jump["is_waypoint"] = bool(
                name and (
                    index == 0
                    or index == len(jumps) - 1
                    or name in duplicate_names
                )
            )


    def plot_file(self):
        ftypes = [
            ('All supported files', '*.csv *.json'),
            ('CSV files', '*.csv'),
            ('JSON files', '*.json'),
        ]
        filename = filedialog.askopenfilename(
            filetypes=ftypes,
            initialdir=self._dialog_initial_directory("import"),
        )

        if len(filename) > 0:
            try:
                self._remember_dialog_directory("import", filename)
                self._close_csv_viewer_if_open()
                ftype_supported = False
                if filename.endswith(".csv"):
                    ftype_supported = True
                    self.plot_csv(filename)

                elif filename.endswith(".json"):
                    ftype_supported = True
                    self.plot_json(filename)
                    return

                if not ftype_supported:
                    self.show_error("Unsupported file type")
            except Exception:
                self._log_unexpected("Failed to import route file")
                self.enable_plot_gui(True)
                self.show_error("(1) An error occurred while reading the file.")


    def _build_neutron_route_from_system_jumps(self, route, settings=None):
        self._close_csv_viewer_if_open()
        self.clear_route(show_dialog=False)
        self._apply_neutron_route_rows([
            {
                "system": waypoint.get("system", ""),
                "jumps": waypoint.get("jumps", 0),
                "distance_to_arrival": waypoint.get("distance_jumped", ""),
                "distance_remaining": waypoint.get("distance_left", ""),
                "neutron": "Yes" if waypoint.get("neutron_star") else "No",
                "done": self._is_done_value(waypoint.get("done", "")),
            }
            for waypoint in route
        ], settings=settings)
        self._finalize_imported_route()


    def _infer_neutron_vias_from_route(self):
        vias = []
        for index, row in enumerate(self.route):
            if index == 0 or index == len(self.route) - 1:
                continue
            remaining = self._safe_float(row[3] if len(row) > 3 else None, None)
            if remaining is not None and abs(remaining) < 1e-9:
                name = str(row[0] if len(row) > 0 else "").strip()
                if name and name not in vias:
                    vias.append(name)
        return vias


    def _neutron_highlight_names(self):
        settings = self._settings_for_planner("Neutron Plotter")
        names = set()
        for value in settings.get("vias", []) or []:
            text = str(value).strip().lower()
            if text:
                names.add(text)
        if names:
            return names
        for value in self._infer_neutron_vias_from_route():
            text = str(value).strip().lower()
            if text:
                names.add(text)
        return names


    def _infer_exploration_planner_from_json(self, payload, systems):
        params = payload.get("parameters", {}) if isinstance(payload, dict) else {}
        planner = params.get("planner", "")
        if planner in ROUTE_PLANNERS:
            return planner

        for system in systems:
            for body in system.get("bodies", []):
                if body.get("landmarks"):
                    return "Exomastery"

        body_types = params.get("body_types", []) or []
        if isinstance(body_types, str):
            body_types = [body_types]
        normalized = sorted(re.sub(r'[^a-z0-9]+', '', str(item).lower()) for item in body_types)
        if normalized == ["ammoniaworld"]:
            return "Ammonia World Route"
        if normalized == ["earthlikeworld"]:
            return "Earth-like World Route"
        if normalized == ["highmetalcontentworld", "rockybody"]:
            return "Rocky/HMC Route"
        return "Road to Riches"


    def _json_exploration_settings(self, payload, planner):
        params = payload.get("parameters", {}) if isinstance(payload, dict) else {}
        return {
            "source": str(params.get("source", "")),
            "destination": str(params.get("destination", params.get("to", ""))),
            "range": str(params.get("range", "")),
            "radius": str(params.get("radius", "")),
            "max_results": str(params.get("max_results", "")),
            "max_distance": str(params.get("max_distance", "")),
            "min_value": str(params.get("min_value", "")),
            "use_mapping_value": bool(params.get("use_mapping_value", False)),
            "avoid_thargoids": bool(params.get("avoid_thargoids", False)),
            "loop": bool(params.get("loop", False)),
            "planner": planner,
        }


    def _import_exploration_json(self, payload, systems):
        planner = self._infer_exploration_planner_from_json(payload, systems)
        settings = self._json_exploration_settings(payload, planner)
        self._close_csv_viewer_if_open()
        self.clear_route(show_dialog=False)
        self._apply_exploration_route_data(planner, systems)
        self._store_plotter_settings(planner, settings)
        if not self.route:
            self.show_error("No route found in JSON.")
            return
        self._finalize_imported_route()


    def _json_fleet_params(self, payload, result):
        params = payload.get("parameters", {}) if isinstance(payload, dict) else {}
        jumps = result.get("jumps", []) if isinstance(result, dict) else []
        id_to_name = {}
        for jump in jumps:
            jump_id = str(jump.get("id64", "")).strip()
            jump_name = str(jump.get("name", "")).strip()
            if jump_id and jump_name:
                id_to_name[jump_id] = jump_name

        result_source = str(result.get("source", "")).strip()
        param_source = str(params.get("source_system", "")).strip()
        source = id_to_name.get(param_source, result_source or param_source)

        destinations = []
        seen_destinations = set()
        for jump in jumps:
            if not jump.get("is_desired_destination"):
                continue
            name = str(jump.get("name", "")).strip()
            if not name or (source and name.lower() == source.lower()) or name.lower() in seen_destinations:
                continue
            seen_destinations.add(name.lower())
            destinations.append(name)
        if not destinations:
            raw_destinations = params.get("destination_systems", result.get("destinations", []))
            if not isinstance(raw_destinations, list):
                raw_destinations = [raw_destinations] if raw_destinations not in (None, "") else []
            known_jump_names = {
                str(jump.get("name", "")).strip().lower()
                for jump in jumps
                if str(jump.get("name", "")).strip()
            }
            for value in raw_destinations:
                raw_value = str(value).strip()
                name = id_to_name.get(raw_value)
                if not name and raw_value.lower() in known_jump_names:
                    name = raw_value
                if not name:
                    continue
                if (source and name.lower() == source.lower()) or name.lower() in seen_destinations:
                    continue
                seen_destinations.add(name.lower())
                destinations.append(name)
        if not destinations and jumps:
            last_name = str(jumps[-1].get("name", "")).strip()
            if last_name and (not source or last_name.lower() != source.lower()):
                destinations.append(last_name)

        refuel_destinations = params.get("refuel_destinations", result.get("refuel_destinations", []))
        if not isinstance(refuel_destinations, list):
            refuel_destinations = []
        mapped_refuel_destinations = []
        seen_refuel = set()
        known_jump_names = {
            str(jump.get("name", "")).strip().lower()
            for jump in jumps
            if str(jump.get("name", "")).strip()
        }
        for value in refuel_destinations:
            raw_value = str(value).strip()
            name = id_to_name.get(raw_value)
            if not name and raw_value.lower() in known_jump_names:
                name = raw_value
            if name and name.lower() not in seen_refuel:
                seen_refuel.add(name.lower())
                mapped_refuel_destinations.append(name)
        current_fuel = self._safe_float(params.get("current_fuel"), None)
        if current_fuel is None:
            current_fuel = self._safe_float(result.get("tritium_stored"), 0) or 0
        tritium_amount = self._safe_float(params.get("tritium_amount"), None)
        if tritium_amount is None:
            tritium_amount = self._safe_float(result.get("fuel_loaded"), 0) or 0
        explicit_carrier_type = params.get("carrier_type", result.get("carrier_type", ""))
        capacity_value = self._safe_int(params.get("capacity"), None)
        if capacity_value is None:
            capacity_value = self._safe_int(result.get("capacity"), None)
        mass_value = self._safe_int(params.get("mass"), None)
        if mass_value is None:
            mass_value = self._safe_int(result.get("mass"), None)
        return {
            "source": source,
            "destinations": destinations,
            "refuel_destinations": mapped_refuel_destinations,
            "carrier_type": self._infer_fleet_carrier_type(
                explicit_type=explicit_carrier_type,
                capacity=capacity_value,
                mass=mass_value,
            ),
            "used_capacity": (
                self._safe_int(params.get("capacity_used"), None)
                if self._safe_int(params.get("capacity_used"), None) is not None
                else (self._safe_int(result.get("capacity_used"), 0) or 0)
            ),
            "determine_required_fuel": bool(params.get("calculate_starting_fuel", result.get("calculate_starting_fuel", False))),
            "tritium_fuel": current_fuel,
            "tritium_market": tritium_amount,
        }


    def _merged_plotter_settings(self, planner, defaults):
        settings = self._settings_for_planner(planner)
        merged = dict(defaults)
        merged.update({key: value for key, value in settings.items() if value not in (None, "")})
        return merged

    def _exploration_export_defaults(self):
        is_exobiology = self.exploration_mode == "Exomastery"
        return {
            "source": self._route_source_name(""),
            "destination": self._route_destination_name(""),
            "range": "",
            "radius": "25",
            "max_results": "100",
            "max_distance": "1000000" if self.exploration_mode in ("Road to Riches", "Exomastery") else "50000",
            "min_value": "10000000" if is_exobiology else "100000",
            "use_mapping_value": False,
            "avoid_thargoids": True,
            "loop": True,
            "planner": self.exploration_mode,
        }

    def _fleet_export_defaults(self):
        source = self._route_source_name("")
        destinations = []
        refuel_destinations = []
        normalized_names = [
            (jump.get("name", "") or "").strip().lower()
            for jump in self.fleet_carrier_data
        ]
        name_counts = {}
        for name in normalized_names:
            if not name:
                continue
            name_counts[name] = name_counts.get(name, 0) + 1
        duplicate_names = {
            name for name, count in name_counts.items()
            if count > 1
        }
        for index, jump in enumerate(self.fleet_carrier_data):
            name = str(jump.get("name", "")).strip()
            if not name:
                continue
            is_duplicate_waypoint = name.lower() in duplicate_names
            if index > 0 and (jump.get("is_waypoint") or is_duplicate_waypoint) and name not in destinations:
                destinations.append(name)
            if jump.get("must_restock") and name not in refuel_destinations:
                refuel_destinations.append(name)
        return {
            "source": source,
            "destinations": destinations,
            "refuel_destinations": refuel_destinations,
            "carrier_type": "fleet",
            "used_capacity": "0",
            "determine_required_fuel": True,
            "tritium_fuel": "0",
            "tritium_market": "0",
        }

    def _exact_export_defaults(self):
        return {
            "source": self._route_source_name(""),
            "destination": self._route_destination_name(""),
            "cargo": "",
            "reserve": "",
            "is_supercharged": False,
            "use_supercharge": True,
            "use_injections": False,
            "exclude_secondary": False,
            "refuel_scoopable": True,
            "algorithm": "optimistic",
        }

    def _neutron_export_defaults(self):
        return {
            "source": self._route_source_name(""),
            "destination": self._route_destination_name(""),
            "range": "",
            "efficiency": 60,
            "supercharge_multiplier": 4,
            "vias": self._infer_neutron_vias_from_route(),
        }

    def _spansh_json_export_payload(self):
        status_block = {"status": "ok", "state": "completed", "job": ""}

        if self.exploration_plotter and self.exploration_route_data:
            params = {}
            settings = self._merged_plotter_settings(
                self.exploration_mode,
                self._exploration_export_defaults(),
            )
            params.update({
                "source": settings.get("source", ""),
                "destination": settings.get("destination", ""),
                "range": self._safe_float(settings.get("range"), settings.get("range", "")) if settings.get("range", "") != "" else "",
                "radius": self._safe_int(settings.get("radius"), settings.get("radius", "")) if settings.get("radius", "") != "" else "",
                "max_results": self._safe_int(settings.get("max_results"), settings.get("max_results", "")) if settings.get("max_results", "") != "" else "",
                "max_distance": self._safe_int(settings.get("max_distance"), settings.get("max_distance", "")) if settings.get("max_distance", "") != "" else "",
                "min_value": self._safe_int(settings.get("min_value"), settings.get("min_value", "")) if settings.get("min_value", "") != "" else "",
                "use_mapping_value": bool(settings.get("use_mapping_value", False)),
                "avoid_thargoids": bool(settings.get("avoid_thargoids", False)),
                "loop": bool(settings.get("loop", False)),
                "planner": self.exploration_mode,
            })
            body_types_map = {
                "Ammonia World Route": ["Ammonia world"],
                "Earth-like World Route": ["Earth-like world"],
                "Rocky/HMC Route": ["Rocky body", "High metal content world"],
            }
            if self.exploration_mode in body_types_map:
                params["body_types"] = body_types_map[self.exploration_mode]
                params["min_value"] = 1
            return {
                **status_block,
                "parameters": params,
                "result": self.exploration_route_data,
            }

        if self.fleetcarrier and self.fleet_carrier_data:
            settings = self._merged_plotter_settings(
                "Fleet Carrier Router",
                self._fleet_export_defaults(),
            )
            carrier_profile = self._fleet_carrier_profile(settings.get("carrier_type"))
            return {
                **status_block,
                "parameters": {
                    "source_system": settings.get("source", self._route_source_name("")),
                    "destination_systems": list(settings.get("destinations", [])),
                    "refuel_destinations": list(settings.get("refuel_destinations", [])),
                    "carrier_type": carrier_profile["carrier_type"],
                    "capacity": carrier_profile["capacity"],
                    "mass": carrier_profile["mass"],
                    "capacity_used": self._safe_int(settings.get("used_capacity"), 0) or 0,
                    "current_fuel": self._safe_float(settings.get("tritium_fuel"), 0) or 0,
                    "tritium_amount": self._safe_float(settings.get("tritium_market"), 0) or 0,
                    "calculate_starting_fuel": bool(settings.get("determine_required_fuel", False)),
                    "planner": "Fleet Carrier Router",
                },
                "result": {
                    "source": settings.get("source", self._route_source_name("")),
                    "destinations": list(settings.get("destinations", [])),
                    "refuel_destinations": list(settings.get("refuel_destinations", [])),
                    "jumps": self.fleet_carrier_data,
                },
            }

        if self.exact_plotter and self.exact_route_data:
            return {
                **status_block,
                "parameters": self._normalize_exact_settings_payload(
                    self._exact_settings or self._exact_export_defaults(),
                    result={
                        "source_system": self._route_source_name(""),
                        "destination_system": self._route_destination_name(""),
                    },
                ),
                "result": {
                    "jumps": self.exact_route_data,
                },
            }

        if self._is_neutron_route_active():
            settings = self._merged_plotter_settings(
                "Neutron Plotter",
                self._neutron_export_defaults(),
            )
            via_values = list(settings.get("vias", []) or [])
            system_jumps = []
            for index in range(len(self.route)):
                row_state = self._route_row_state_at(index)
                system_jumps.append({
                    "system": row_state["name"],
                    "jumps": row_state["progress"],
                    "distance_jumped": row_state["distance_to_arrival"] or 0,
                    "distance_left": row_state["remaining_distance"] or 0,
                    "neutron_star": row_state["has_neutron"],
                    "done": row_state["done"],
                })
            return {
                **status_block,
                "parameters": {
                    "from": settings.get("source", self._route_source_name("")),
                    "to": settings.get("destination", self._route_destination_name("")),
                    "range": self._safe_float(settings.get("range"), settings.get("range", "")) if settings.get("range", "") != "" else "",
                    "efficiency": self._safe_float(settings.get("efficiency"), settings.get("efficiency", "")) if settings.get("efficiency", "") != "" else "",
                    "supercharge_multiplier": self._safe_float(settings.get("supercharge_multiplier"), settings.get("supercharge_multiplier", "")) if settings.get("supercharge_multiplier", "") != "" else "",
                    "planner": "Neutron Plotter",
                    "via": via_values,
                },
                "result": {
                    "source_system": self._route_source_name(""),
                    "destination_system": self._route_destination_name(""),
                    "system_jumps": system_jumps,
                },
            }

        return None


    def _infer_jump_json_mode(self, payload, result):
        params = payload.get("parameters", {}) if isinstance(payload, dict) else {}
        planner = str(params.get("planner", "")).strip()
        if planner == "Fleet Carrier Router":
            return "fleet"
        if planner == "Galaxy Plotter":
            return "exact"

        route_type = str(payload.get("route_type", "")).strip()
        if route_type == "fleet_carrier":
            return "fleet"
        if route_type in ("exact", "galaxy"):
            return "exact"

        first_jump = result["jumps"][0] if result["jumps"] else {}
        is_fleet_json = (
            "destinations" in result
            or "refuel_destinations" in result
            or "tritium_stored" in result
            or "destination_systems" in params
            or any(key in first_jump for key in ("tritium_in_market", "must_restock", "restock_amount", "is_desired_destination", "has_icy_ring", "is_system_pristine"))
        )
        return "fleet" if is_fleet_json else "exact"


    def _parse_neutron_json_payload(self, payload, result):
        params = payload.get("parameters", {}) if isinstance(payload.get("parameters"), dict) else {}
        vias = params.get("via", params.get("vias", result.get("via", [])))
        if isinstance(vias, str):
            vias = [vias]
        elif not isinstance(vias, list):
            vias = []
        settings = {
            "source": str(params.get("from", result.get("source_system", ""))),
            "destination": str(params.get("to", result.get("destination_system", ""))),
            "range": str(params.get("range", "")),
            "efficiency": self._safe_float(params.get("efficiency"), 0.6) if params.get("efficiency", "") != "" else 0.6,
            "supercharge_multiplier": self._normalize_supercharge_multiplier(
                params.get("supercharge_multiplier", 4)
            ),
            "vias": [str(v).strip() for v in vias if str(v).strip()],
        }
        self._build_neutron_route_from_system_jumps(result.get("system_jumps", []), settings)


    def _parse_jump_json_payload(self, payload, result):
        if self._infer_jump_json_mode(payload, result) == "fleet":
            self._fleet_carrier_route_success(result, self._json_fleet_params(payload, result))
            self._finalize_imported_route()
        else:
            self._pending_exact_settings = self._normalize_exact_settings_payload(
                payload.get("parameters", {}),
                result=result,
            )
            self._exact_plot_success({"result": result})
            self._finalize_imported_route()


    def _parse_exploration_json_payload(self, payload, result):
        self._import_exploration_json(payload, result)


    def plot_json(self, filename):
        with io.open(filename, 'r', encoding='utf-8-sig') as jsonfile:
            payload = json.load(jsonfile)

        if not isinstance(payload, dict):
            raise ValueError("Unsupported JSON format")

        result = payload.get("result", payload)

        if isinstance(result, dict) and isinstance(result.get("system_jumps"), list):
            self._parse_neutron_json_payload(payload, result)
            return

        if isinstance(result, dict) and isinstance(result.get("jumps"), list):
            self._parse_jump_json_payload(payload, result)
            return

        if isinstance(result, list):
            self._parse_exploration_json_payload(payload, result)
            return

        raise ValueError("Unsupported JSON format")


    def _reset_import_route_buffers(self):
        self.route_type = None
        self.route = []
        self._invalidate_route_rows()
        self.route_done = []
        self.jumps_left = 0
        self.exact_route_data = []
        self.fleet_carrier_data = []
        self.exact_plotter = False
        self.fleetcarrier = False
        self.galaxy = False

        self._reset_exploration_state()


    def _finalize_csv_import(self):
        if self.current_plotter_name and self._plotter_settings.get("planner") != self.current_plotter_name:
            self._store_plotter_settings(self.current_plotter_name, {})
        self._finalize_imported_route()


    def _parse_exact_csv_rows(self, route_reader, has_any_field, get_field_value, parse_yes_no):
        self.exact_plotter = True
        self._set_current_plotter("Galaxy Plotter")
        is_current_layout = (
            has_any_field("Distance (Ly)", "Distance(LY)", "Distance Travelled")
            and has_any_field("Remaining (Ly)", "Remaining(LY)", "Remaining")
            and has_any_field("Fuel Left (tonnes)", "Fuel Remaining")
            and has_any_field("Fuel Used (tonnes)", "Fuel Used")
            and not has_any_field("Fuel In Tank", "Distance To Arrival")
        )

        for index, row in enumerate(route_reader):
            if row in (None, "", []):
                continue
            system_name = get_field_value(row, self.system_header, "System", "SystemName")
            if (system_name or "").strip().lower() == "total":
                continue
            jumps_val = "0" if index == 0 else "1"
            if not is_current_layout:
                jumps_val = get_field_value(row, self.jumps_header, "Jumps Left", default=("0" if index == 0 else "1"))
            self.route.append([
                system_name,
                jumps_val,
                get_field_value(row, "Distance To Arrival", "Distance (Ly)", "Distance(LY)", "Distance Travelled", "Distance"),
                get_field_value(row, "Distance Remaining", "Remaining (Ly)", "Remaining(LY)", "Remaining"),
            ])
            self.exact_route_data.append({
                "done": self._is_done_value(row.get("Done", "")),
                "name": system_name,
                "distance": get_field_value(row, "Distance To Arrival", "Distance (Ly)", "Distance(LY)", "Distance Travelled", "Distance"),
                "distance_to_destination": get_field_value(row, "Distance Remaining", "Remaining (Ly)", "Remaining(LY)", "Remaining"),
                "fuel_in_tank": get_field_value(row, "Fuel In Tank", "Fuel Left (tonnes)", "Fuel Remaining", "Fuel Left"),
                "fuel_used": get_field_value(row, "Fuel Used", "Fuel Used (tonnes)"),
                "must_refuel": parse_yes_no(get_field_value(row, "Must Refuel", "Refuel?", "Refuel", default="No")),
                "has_neutron": parse_yes_no(get_field_value(row, "Has Neutron", "Neutron", "Neutron Star", default="No")),
                "is_scoopable": parse_yes_no(get_field_value(row, "Is Scoopable", default="No")),
            })
            try:
                self.jumps_left += int(jumps_val)
            except ValueError:
                self.jumps_left += 1

        if self.exact_route_data:
            self.exact_route_data[0]["must_refuel"] = True


    def _parse_neutron_csv_rows(self, route_reader, get_field_value):
        neutron_rows = []
        for row in route_reader:
            if row in (None, "", []):
                continue
            system_name = get_field_value(row, self.system_header, "System", "SystemName")
            if system_name in (None, ""):
                raise ValueError(f"Missing required CSV column '{self.system_header}'.")
            neutron_rows.append({
                "system": system_name,
                "jumps": get_field_value(row, self.jumps_header, default=""),
                "distance_to_arrival": get_field_value(row, "Distance To Arrival", "Distance (Ly)", "Distance", default=""),
                "distance_remaining": get_field_value(row, "Distance Remaining", "Remaining (Ly)", "Remaining", default=""),
                "neutron": "Yes" if str(get_field_value(row, "Neutron Star", "Neutron", default="")).strip().lower() == "yes" else "No",
                "done": self._is_done_value(get_field_value(row, "Done", default="")),
            })

        self._apply_neutron_route_rows(neutron_rows)

        if self.route:
            self._store_plotter_settings(
                "Neutron Plotter",
                {
                    "source": self._route_source_name(""),
                    "destination": self._route_destination_name(""),
                    "vias": self._infer_neutron_vias_from_route(),
                },
            )


    def _parse_simple_csv_rows(self, route_reader, get_field_value):
        self.route_type = "simple"
        self._set_current_plotter("Simple Route")
        for row in route_reader:
            if row in (None, "", []):
                continue
            system_name = get_field_value(row, self.system_header, "System", "SystemName")
            if system_name in (None, ""):
                raise ValueError(f"Missing required CSV column '{self.system_header}'.")
            self.route.append([
                system_name,
                get_field_value(row, self.jumps_header, default=""),
            ])
            self.route_done.append(self._is_done_value(get_field_value(row, "Done", default="")))
            try:
                self.jumps_left += int(get_field_value(row, self.jumps_header, default=0))
            except Exception:
                pass


    def _parse_fleet_csv_rows(self, route_reader, get_distance_fields, get_field_value):
        self.fleetcarrier = True
        self._set_current_plotter("Fleet Carrier Router")

        rows = [row for row in route_reader if row not in (None, "", [])]
        route_rows = [row for row in rows if (row.get(self.system_header, "") or "").strip().lower() != "total"]
        total_jumps = len(route_rows) - 1 if len(route_rows) > 1 else 0

        for index, row in enumerate(route_rows):
            dist_to_arrival, dist_remaining = get_distance_fields(row)
            restock = get_field_value(row, self.restocktritium_header, "Restock?", default="")
            self.fleet_carrier_data.append({
                "done": self._is_done_value(row.get("Done", "")),
                "name": get_field_value(row, self.system_header, "System", default=""),
                "distance": dist_to_arrival,
                "distance_to_destination": dist_remaining,
                "is_waypoint": (row.get("Is Waypoint", "") or "").strip().lower() == "yes",
                "fuel_in_tank": get_field_value(row, "Tritium in tank", "Fuel Left (tonnes)", default=""),
                "tritium_in_market": get_field_value(row, "Tritium in market", default=""),
                "fuel_used": get_field_value(row, "Fuel Used", "Fuel Used (tonnes)", default=""),
                "has_icy_ring": (get_field_value(row, "Icy Ring", "Icy ring", default="") or "").strip().lower() in ("yes", "pristine"),
                "is_system_pristine": (get_field_value(row, "Pristine", default="") or "").strip().lower() == "yes" or (get_field_value(row, "Icy Ring", "Icy ring", default="") or "").strip().lower() == "pristine",
                "must_restock": restock.strip().lower() == "yes",
                "restock_amount": get_field_value(row, "Restock Amount", default=""),
            })
            jumps_remaining = max(total_jumps - index, 0)
            self.route.append([
                get_field_value(row, self.system_header, "System", default=""),
                str(jumps_remaining),
                dist_to_arrival,
                dist_remaining,
                restock,
            ])
            self.jumps_left = max(self.jumps_left, jumps_remaining)

        if self.fleet_carrier_data and not any(jump.get("is_waypoint") for jump in self.fleet_carrier_data):
            settings = self._settings_for_planner("Fleet Carrier Router")
            self._apply_fleet_waypoint_flags(self.fleet_carrier_data, settings=settings)

        for index in range(1, len(self.fleet_carrier_data)):
            jump = self.fleet_carrier_data[index]
            if not jump.get("must_restock") or jump.get("restock_amount") not in ("", None):
                continue
            previous_fuel = self._safe_float(self.fleet_carrier_data[index - 1].get("fuel_in_tank"), None)
            current_fuel = self._safe_float(jump.get("fuel_in_tank"), None)
            current_used = self._safe_float(jump.get("fuel_used"), None)
            if previous_fuel is None or current_fuel is None or current_used is None:
                continue
            if current_fuel > previous_fuel:
                jump["restock_amount"] = current_fuel - previous_fuel + current_used


    def _parse_exploration_csv_rows(self, headerline, filename, route_reader):
        rows = [row for row in route_reader if row not in (None, "", [])]
        if headerline in (EXOBIOLOGY_CSV_HEADER, LEGACY_EXOBIOLOGY_CSV_HEADER_V2, LEGACY_EXOBIOLOGY_CSV_HEADER) or (
            "Landmark Subtype" in headerline and ("Landmark Value" in headerline or "Value" in headerline)
        ):
            systems = self._build_exobiology_systems_from_rows(rows)
            self._apply_exploration_route_data("Exomastery", systems)
            return

        mode = self._infer_exploration_mode(headerline, filename)
        if headerline in (
            SPECIALIZED_RICHES_CSV_HEADER,
            SPANSH_SPECIALIZED_RICHES_CSV_HEADER,
            PLUGIN_SPECIALIZED_RICHES_CSV_HEADER,
        ):
            systems = self._build_riches_systems_from_rows(rows, specialized=True)
        else:
            systems = self._build_riches_systems_from_rows(rows)
        self._apply_exploration_route_data(mode, systems)


    def _parse_galaxy_csv_rows(self, route_reader, get_distance_fields, get_field_value):
        self.galaxy = True
        self._set_current_plotter("Galaxy Plotter")

        for row in route_reader:
            if row in (None, "", []):
                continue
            dist_to_arrival, dist_remaining = get_distance_fields(row)
            route_row = [
                get_field_value(row, self.system_header, "System", "SystemName"),
                get_field_value(row, self.refuel_header, "Refuel", "Refuel?", default=""),
            ]

            if dist_to_arrival or dist_remaining:
                route_row.append(dist_to_arrival)
                route_row.append(dist_remaining)

            self.route.append(route_row)
            self.route_done.append(self._is_done_value(row.get("Done", "")))
            self.jumps_left += 1


    def plot_csv(self, filename, clear_previous_route=True):
        with io.open(filename, 'r', encoding='utf-8-sig', newline='') as csvfile:
            if clear_previous_route:
                self.clear_route(False)
            else:
                self._reset_import_route_buffers()

    
            self._reset_exploration_state()
            self.fleetcarrier = False
            self.galaxy = False

            route_reader = csv.DictReader(csvfile)
            headerline = ','.join(route_reader.fieldnames) if route_reader.fieldnames else ""
            normalized_fields = {
                re.sub(r'[^a-z0-9]+', '', field.lower()): field
                for field in (route_reader.fieldnames or [])
                if field
            }

            exactplotterheader = "System Name,Distance (Ly),Remaining (Ly),Jumps Left,Fuel Left (tonnes),Fuel Used (tonnes),Refuel?,Neutron"
            exactplotterheader_spansh = "System Name,Distance Travelled,Remaining,Fuel Remaining,Fuel Used,Refuel,Neutron"
            exactplotterheader_spansh_v2 = "System Name,Distance,Distance Remaining,Fuel Left,Fuel Used,Refuel,Neutron Star"
            neutronimportheader = "System Name,Distance To Arrival,Distance Remaining,Neutron Star,Jumps"
            fleetcarrierimportheader = "System Name,Distance,Distance Remaining,Tritium in tank,Tritium in market,Fuel Used,Icy Ring,Pristine,Restock Tritium"

            def has_any_field(*names):
                return any(re.sub(r'[^a-z0-9]+', '', name.lower()) in normalized_fields for name in names)

            def has_field_fragment(*fragments):
                normalized_keys = list(normalized_fields.keys())
                for fragment in fragments:
                    normalized_fragment = re.sub(r'[^a-z0-9]+', '', fragment.lower())
                    if any(normalized_fragment in key for key in normalized_keys):
                        return True
                return False

            def get_field_value(row, *names, default=""):
                for name in names:
                    actual_name = normalized_fields.get(re.sub(r'[^a-z0-9]+', '', name.lower()))
                    if actual_name in row and row[actual_name] not in (None, ""):
                        return row[actual_name]
                return default

            def parse_yes_no(value):
                return str(value).strip().lower() in ("yes", "true", "1")

            is_neutron_csv = headerline == neutronimportheader or (
                has_any_field(self.system_header)
                and has_any_field("Distance To Arrival")
                and has_any_field("Distance Remaining")
                and has_any_field("Neutron Star")
                and has_any_field(self.jumps_header)
                and not (
                    has_any_field("Fuel Left (tonnes)", "Fuel Remaining", "Fuel Left", "Fuel In Tank")
                    or has_any_field("Fuel Used", "Fuel Used (tonnes)")
                    or has_any_field("Refuel", "Refuel?")
                )
            )

            is_fleet_csv = headerline == fleetcarrierimportheader or (
                has_any_field(self.system_header)
                and has_any_field("Tritium in tank", "Fuel Left (tonnes)")
                and has_any_field("Tritium in market")
                and has_any_field("Fuel Used", "Fuel Used (tonnes)")
            )

            is_exact_csv = headerline in (
                exactplotterheader,
                exactplotterheader_spansh,
                exactplotterheader_spansh_v2,
            ) or (
                not is_neutron_csv
                and not is_fleet_csv
                and
                has_any_field(self.system_header, "System", "SystemName")
                and has_field_fragment("distance", "distancetravelled")
                and has_field_fragment("remaining", "distanceremaining")
                and (
                    has_field_fragment("fuelremaining", "fuelleft", "fuelintank")
                    or has_field_fragment("fuelused")
                    or has_field_fragment("refuel")
                    or has_field_fragment("neutron")
                )
            )

            def get_distance_fields(row):
                dist_to_arrival = (
                    row.get("Distance To Arrival", "")
                    or row.get("Distance (Ly)", "")
                    or row.get("Distance (Ls)", "")
                    or row.get("Distance", "")
                )
                dist_remaining = (
                    row.get("Distance Remaining", "")
                    or row.get("Remaining (Ly)", "")
                    or row.get("Remaining", "")
                    or ""
                )
                return dist_to_arrival, dist_remaining

            if is_exact_csv:
                self._parse_exact_csv_rows(route_reader, has_any_field, get_field_value, parse_yes_no)
            elif is_neutron_csv:
                self._parse_neutron_csv_rows(route_reader, get_field_value)
            elif (
                has_any_field(self.system_header)
                and has_any_field(self.jumps_header)
                and not has_any_field(
                    "Distance To Arrival",
                    "Distance (Ly)",
                    "Distance (Ls)",
                    "Distance",
                    "Refuel",
                    "Landmark Subtype",
                    "Body Name",
                    "Name",
                    "Subtype",
                    "Is Terraformable",
                    "Scan Value",
                    "Mapping Value",
                )
            ):
                self._parse_simple_csv_rows(route_reader, get_field_value)
            elif is_fleet_csv:
                self._parse_fleet_csv_rows(route_reader, get_distance_fields, get_field_value)
            elif headerline in (EXOBIOLOGY_CSV_HEADER, LEGACY_EXOBIOLOGY_CSV_HEADER_V2, LEGACY_EXOBIOLOGY_CSV_HEADER) or (
                "Landmark Subtype" in headerline and (
                    "Landmark Value" in headerline or "Value" in headerline
                )
            ):
                self._parse_exploration_csv_rows(headerline, filename, route_reader)
            elif headerline in (
                RICHES_CSV_HEADER,
                SPECIALIZED_RICHES_CSV_HEADER,
                SPANSH_SPECIALIZED_RICHES_CSV_HEADER,
                PLUGIN_SPECIALIZED_RICHES_CSV_HEADER,
                LEGACY_RICHES_CSV_HEADER,
                LEGACY_RICHES_CSV_HEADER_V2,
            ) or (
                ("Body Name" in headerline or "Name" in headerline) and (
                    "Body Subtype" in headerline or "Subtype" in headerline or
                    (
                        ("Distance (Ls)" in headerline or "Distance To Arrival" in headerline)
                        and self.jumps_header in headerline
                    )
                )
            ):
                self._parse_exploration_csv_rows(headerline, filename, route_reader)
            elif (
                "Refuel" in headerline
                and self.system_header in headerline
                and not has_any_field(
                    "Fuel Left (tonnes)",
                    "Fuel Remaining",
                    "Fuel In Tank",
                    "Fuel Used",
                    "Fuel Used (tonnes)",
                    "Neutron",
                    "Has Neutron",
                )
            ):
                self._parse_galaxy_csv_rows(route_reader, get_distance_fields, get_field_value)
            else:
                self._parse_simple_csv_rows(route_reader, get_field_value)

            self._finalize_csv_import()

    def save_all_route(self):
        self._save_route_state()
        try:
            os.remove(self.save_route_path)
        except Exception:
            pass
        try:
            os.remove(self.offset_file_path)
        except Exception:
            pass


    def _save_exact_settings(self):
        """Save exact plotter settings to plugin folder."""
        try:
            if self._exact_settings:
                self._write_json_atomic(
                    self.exact_settings_path,
                    self._exact_settings,
                    prefix=".exact_settings.",
                )
        except Exception as e:
            logger.debug(f"Could not save exact settings: {e}")

    def _normalize_exact_settings_payload(self, settings, *, result=None):
        if not isinstance(settings, dict):
            settings = {}
        normalized = dict(settings)
        normalized.pop("is_supercharged", None)
        source = (
            normalized.get("source")
            or normalized.get("source_system")
            or normalized.get("from")
            or (result.get("source_system", "") if isinstance(result, dict) else "")
        )
        destination = (
            normalized.get("destination")
            or normalized.get("destination_system")
            or normalized.get("to")
            or (result.get("destination_system", "") if isinstance(result, dict) else "")
        )
        if source:
            normalized["source"] = str(source).strip()
        if destination:
            normalized["destination"] = str(destination).strip()
        return normalized or None


    def _load_exact_settings(self):
        """Load exact plotter settings from plugin folder."""
        try:
            with open(self.exact_settings_path, 'r') as f:
                payload = json.load(f)
            self._exact_settings = self._normalize_exact_settings_payload(payload)
        except (FileNotFoundError, json.JSONDecodeError):
            self._exact_settings = None
        except Exception as exc:
            logger.debug(f"Could not load exact settings: {exc}")
            self._exact_settings = None
