"""Route import/export and state persistence mixin."""

import json
import os
import re
import tempfile
from collections import Counter
import tkinter.filedialog as filedialog

from config import config
from .constants import logger


class RouteIOMixin:
    """Mixin for route serialization, deserialization, and import/export (JSON, CSV, clipboard)."""

    _EXPORT_NAME_SANITIZER = re.compile(r'[\\/:*?"<>|]+')
    _IMPORT_DIR_CONFIG_KEY = "spansh_last_import_dir"
    _EXPORT_DIR_CONFIG_KEY = "spansh_last_export_dir"

    # --- Utilities ---

    def _route_state_path(self):
        return os.path.join(self.plugin_dir, self.route_state_filename)

    def _dialog_initial_directory(self, kind):
        key = self._IMPORT_DIR_CONFIG_KEY if kind == "import" else self._EXPORT_DIR_CONFIG_KEY
        try:
            saved_path = config.get_str(key, default="")
            if saved_path and os.path.isdir(saved_path): return saved_path
        except Exception: logger.debug("Failed to read dialog directory from config", exc_info=True)
        return os.path.expanduser("~")

    def _remember_dialog_directory(self, kind, filename):
        if not filename: return
        directory = os.path.dirname(os.path.abspath(filename))
        if directory and os.path.isdir(directory):
            key = self._IMPORT_DIR_CONFIG_KEY if kind == "import" else self._EXPORT_DIR_CONFIG_KEY
            try: config.set(key, directory)
            except Exception: logger.debug("Failed to save dialog directory to config", exc_info=True)
        return

    def _resolve_system_id(self, system_id, result):
        if not system_id: return ""
        target_id = str(system_id).strip()
        if not target_id.isdigit(): return target_id

        search_list = []
        if isinstance(result, dict): search_list = result.get("jumps", [])
        elif isinstance(result, list): search_list = result

        for item in search_list:
            if str(item.get("id64", "")).strip() == target_id:
                return str(item.get("name", "")).strip() or target_id
        return target_id

    def _write_json_atomic(self, path, payload, *, prefix):
        fd, temp_path = None, None
        try:
            target_dir = os.path.dirname(path)
            os.makedirs(target_dir, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=target_dir, text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None; json.dump(payload, handle); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            if fd is not None:
                try: os.close(fd)
                except Exception: logger.debug("Failed to close temp file descriptor", exc_info=True)
            if temp_path:
                try: os.remove(temp_path)
                except Exception: logger.debug("Failed to remove temp file", exc_info=True)
            raise

    # --- Route State Management ---

    def _reset_route_data(self, route_type, plotter_name=None, exp_mode=None):
        self._reset_exploration_state()
        self.route_type = route_type
        self.current_plotter_name = plotter_name
        self.exploration_mode = exp_mode
        self.route, self.route_done = [], []
        self.jumps_left = 0
        self.exact_route_data, self.fleet_carrier_data, self.exploration_route_data, self.neutron_route_data = [], [], [], []
        self._saved_route_complete = False
        self._invalidate_route_rows()

    def _resolve_saved_route_type(self, payload):
        saved = payload.get("route_type")
        if saved in ("exact", "fleet_carrier", "exploration", "neutron", "simple"):
            return saved
        return "simple" if payload.get("route") else None

    def _restore_route_done_values(self, payload):
        if self.route_type == "exploration" and self.exploration_route_data: return self._exploration_system_done_values()
        if self.route_type == "exact" and self.exact_route_data: return [bool(j.get("done", False)) for j in self.exact_route_data]
        if self.route_type == "fleet_carrier" and self.fleet_carrier_data: return [bool(j.get("done", False)) for j in self.fleet_carrier_data]
        return [bool(v) for v in payload.get("route_done", [])]

    def _finalize_imported_route(self, *, sync_refuel=True):
        """Post-import cleanup: restore offset from done progress, recount jumps, and update GUI widths."""
        if not self.route: return
        if not self._restore_offset_from_done_progress(): self._reset_offset_from_current_system()
        self._recalculate_jumps_left_from_offset()
        if sync_refuel: self.pleaserefuel = self._route_refuel_required_at(self.offset)
        self.compute_distances()
        self._first_wp_distances = ()
        if self._route_complete_for_ui() or getattr(self, "_saved_route_complete", False): self.jumps_left = 0
        else: self.copy_waypoint()
        self.update_gui(); self._update_overlay(); self.save_all_route()

    def _serialize_route_state(self):
        if not self.route: return None
        return {
            "planner": self._current_route_planner_name(),
            "route_type": self.route_type,
            "offset": int(self.offset or 0),
            "jumps_left": int(self.jumps_left or 0),
            "route_complete": bool(self._route_complete_for_ui()),
            "route": [list(row) for row in self.route],
            "route_done": self._route_done_values(),
            "exploration_mode": self.exploration_mode,
            "exploration_body_types": list(getattr(self, "exploration_body_types", []) or []),
            "exploration_route_data": self.exploration_route_data,
            "fleet_carrier_data": self.fleet_carrier_data,
            "exact_route_data": self.exact_route_data,
            "neutron_route_data": self.neutron_route_data,
        }

    def _apply_route_state(self, payload):
        """Restore full route state (type, data, done flags) from a saved JSON payload."""
        def _list(key): v = payload.get(key, []); return v if isinstance(v, list) else []

        self.route = [list(row) for row in payload.get("route", []) if isinstance(row, (list, tuple))]
        self.route_type = self._resolve_saved_route_type(payload)
        self.current_plotter_name = str(payload.get("planner", "")).strip()
        self.exploration_mode = payload.get("exploration_mode")
        self.exploration_body_types = _list("exploration_body_types")
        self.exploration_route_data = _list("exploration_route_data")
        self.fleet_carrier_data = _list("fleet_carrier_data")
        self.exact_route_data = _list("exact_route_data")
        self.neutron_route_data = _list("neutron_route_data")
        self.offset = self._safe_int(payload.get("offset"), 0)
        self._saved_route_complete = bool(payload.get("route_complete", False))
        self.route_done = self._restore_route_done_values(payload)

        self._sync_route_done()
        self._invalidate_route_rows()

    def _save_route_state(self):
        try:
            payload = self._serialize_route_state()
            if not payload:
                try: os.remove(self._route_state_path())
                except OSError: pass
                return
            self._write_json_atomic(self._route_state_path(), payload, prefix=".route_state.")
        except Exception as e: logger.debug(f"Could not save route state: {e}")

    def _load_route_state(self):
        try:
            with open(self._route_state_path(), "r", encoding="utf-8") as handle: return json.load(handle)
        except Exception:
            logger.debug("Failed to load route state", exc_info=True)
            return None

    def _restore_offset_from_done_progress(self):
        done_values = self._route_done_values()
        if not done_values:
            return False
        last_done = None
        for i in range(min(len(done_values), len(self.route)) - 1, -1, -1):
            if done_values[i]:
                last_done = i
                break
        if last_done is None:
            return False
        if last_done >= len(self.route) - 1:
            self.offset = max(0, len(self.route) - 1)
            self.next_stop = ""
        else:
            self.offset = last_done + 1
            self.next_stop = self._route_name_at(self.offset, self._route_source_name(""))
        return True

    # --- Plotter Settings ---

    def _load_plotter_settings(self):
        try:
            with open(self.plotter_settings_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            planners = {n: dict(s) for n, s in (payload.get("planners") or {}).items() if isinstance(s, dict)}
            # Migrate legacy top-level "planner"/"settings" into planners dict
            legacy_name = str(payload.get("planner", "")).strip()
            legacy_settings = payload.get("settings")
            if legacy_name and isinstance(legacy_settings, dict) and legacy_name not in planners:
                planners[legacy_name] = dict(legacy_settings)
            # Migrate "Galaxy Plotter" → "Exact Plotter"
            if "Galaxy Plotter" in planners and "Exact Plotter" not in planners:
                planners["Exact Plotter"] = planners.pop("Galaxy Plotter")
            self._plotter_settings = {"planners": planners}
        except Exception:
            logger.debug("Failed to load plotter settings", exc_info=True)
            self._plotter_settings = {}

    def _save_plotter_settings(self):
        try:
            if self._plotter_settings:
                self._write_json_atomic(self.plotter_settings_path, self._plotter_settings, prefix=".plotter_settings.")
            else:
                os.remove(self.plotter_settings_path)
        except Exception: logger.debug("Failed to save plotter settings", exc_info=True)

    def _store_plotter_settings(self, planner, settings):
        planners = dict(self._plotter_settings.get("planners") or {})
        planners[planner] = dict(settings or {})
        self._plotter_settings = {"planners": planners}
        self._save_plotter_settings()

    def _settings_for_planner(self, planner):
        return dict((self._plotter_settings.get("planners", {}) or {}).get(planner, {}) or {})

    def _set_current_plotter(self, planner): self.current_plotter_name = planner
    def _clear_plotter_settings(self):
        self.current_plotter_name, self._plotter_settings = None, {}
        try: os.remove(self.plotter_settings_path)
        except Exception: pass
    def _sanitize_export_name_token(self, value, default="undefined"): return self._EXPORT_NAME_SANITIZER.sub("_", str(value or "").strip() or default)

    # --- Exploration Route Handling ---

    def _route_has_exobiology_landmarks(self, route_data):
        return any(body.get("landmarks") for sys in (route_data or []) for body in (sys.get("bodies") or []))

    def _get_exploration_type(self):
        mode = str(getattr(self, "exploration_mode", getattr(self, "current_plotter_name", ""))).lower()
        if "exomastery" in mode or "exobiology" in mode: return "exo"
        if any(x in mode for x in ("ammonia", "earth", "rocky", "hmc")): return "spec"
        if "riches" in mode: return "riches"

        if self._route_has_exobiology_landmarks(getattr(self, "exploration_route_data", None)):
            return "exo"

        return "riches"

    _EXPLORATION_FILENAME_PREFIXES = {
        "Exomastery": "exomastery", "Road to Riches": "riches",
        "Ammonia World Route": "ammonia", "Earth-like World Route": "earth-like", "Rocky/HMC Route": "rocky-metal",
    }

    def _export_filename_prefix(self):
        if self.route_type == "exact": return "exact-plotter"
        if self.route_type == "fleet_carrier": return "fleet-carrier"
        if self.route_type == "neutron": return "neutron"
        if self.route_type == "exploration":
            return self._EXPLORATION_FILENAME_PREFIXES.get(getattr(self, "exploration_mode", ""), "exploration")
        return "route"

    def _export_filename_tokens(self):
        source, dest = self._route_source_name(""), self._route_destination_name("")
        settings = self._settings_for_planner(self._current_route_planner_name())
        if settings:
            source = settings.get("source", source)
            if self.route_type == "fleet_carrier":
                dests = settings.get("destinations") or []
                dest = dests[-1] if dests else settings.get("destination", dest)
            else:
                dest = settings.get("destination", dest)
        return [self._export_filename_prefix(), self._sanitize_export_name_token(source), self._sanitize_export_name_token(dest)]

    def _default_export_filename(self, extension): return f"{'-'.join(self._export_filename_tokens())}{extension if str(extension).startswith('.') else '.'+extension}"

    def _apply_exploration_route_data(self, mode, systems, body_types=None):
        """Populate the exploration route from an API result — builds route list and per-body metadata."""
        self._reset_route_data("exploration", mode, mode)
        self.exploration_plotter = True
        self.exploration_route_data = systems
        self.exploration_body_types = body_types
        for system in systems:
            jumps = self._safe_int(system.get("jumps"), 1)
            self.route.append([system.get("name", ""), str(jumps)])
            self.route_done.append(False); self.jumps_left += jumps
        self._sync_runtime_route_rows()

    def _exploration_view_rows(self):
        rows = []
        exp_type = self._get_exploration_type()
        is_exo = exp_type == "exo"
        is_spec = exp_type == "spec"
        is_riches = exp_type == "riches"
        t_sys = t_bod = t_val = t_scan = t_map = t_jump = 0

        for r_idx, system in enumerate(self.exploration_route_data):
            s_name, jumps = system.get("name", ""), self._safe_int(system.get("jumps", 1), 1)
            t_sys += 1; t_jump += jumps; show_sys = True
            bodies = system.get("bodies", [])

            if not bodies:
                empty_row = [" ", s_name, "", ""] # [Done, Sys, Name, Body-Spec-Trailing]
                if is_exo or is_riches: empty_row += ["", "", "", ""]
                empty_row.append(jumps)
                rows.append({"values": empty_row, "route_index": r_idx, "is_total": False, "no_done": True, "done_ref": system, "system_name": s_name})
                continue

            for body in bodies:
                t_bod += 1
                b_name = body.get("name", "")
                dist_str = self._format_whole_number(body.get("distance_to_arrival"))
                row = [self._done_cell_value(body.get("done")), s_name if show_sys else "", b_name]

                if is_exo:
                    lms = body.get("landmarks", [])
                    if not lms:
                        row += [body.get("subtype", ""), dist_str, "", "", "", jumps if show_sys else ""]
                        rows.append({"values": row, "route_index": r_idx, "is_total": False, "no_done": False, "done_ref": body, "system_name": s_name, "body_name": b_name})
                    else:
                        show_bod = True
                        for lm in lms:
                            t_val += self._safe_int(lm.get("value", 0))
                            row = [self._done_cell_value(lm.get("done")), s_name if show_sys else "", b_name if show_bod else ""]
                            row += [body.get("subtype", "") if show_bod else "", dist_str if show_bod else "", lm.get("subtype", ""), lm.get("count", ""), self._format_whole_number(lm.get("value", "")), jumps if show_sys else ""]
                            rows.append({"values": row, "route_index": r_idx, "is_total": False, "no_done": False, "done_ref": lm, "system_name": s_name, "body_name": b_name})
                            show_bod = False
                elif is_riches:
                    scan_val = self._safe_int(body.get("estimated_scan_value", 0))
                    map_val = self._safe_int(body.get("estimated_mapping_value", 0))
                    t_scan += scan_val; t_map += map_val
                    row += [body.get("subtype", ""), self._terraformable_display_value(body.get("is_terraformable")), dist_str, self._format_whole_number(scan_val), self._format_whole_number(map_val), jumps if show_sys else ""]
                    rows.append({"values": row, "route_index": r_idx, "is_total": False, "no_done": False, "done_ref": body, "system_name": s_name, "body_name": b_name})
                elif is_spec:
                    row += [dist_str, jumps if show_sys else ""]
                    rows.append({"values": row, "route_index": r_idx, "is_total": False, "no_done": False, "done_ref": body, "system_name": s_name, "body_name": b_name})

                show_sys = False

        if rows:
            totals = ["Total", f"{self._format_whole_number(t_sys)} systems", f"{self._format_whole_number(t_bod)} bodies"]
            if is_exo: totals += ["", "", "", "", self._format_whole_number(t_val)]
            elif is_riches: totals += ["", "", "", self._format_whole_number(t_scan), self._format_whole_number(t_map)]
            elif is_spec: totals += [""]
            totals.append(t_jump)
            rows.append({"values": totals, "route_index": -1, "is_total": True, "no_done": True})
        return rows

    # --- Route Data Application ---

    def _apply_neutron_route_rows(self, rows, settings=None):
        self._reset_route_data("neutron", "Neutron Plotter")
        self.neutron_route_data = list(rows)
        for row in rows:
            jumps = str(row.get("jumps", ""))
            is_neutron = bool(row.get("neutron_star", row.get("neutron", False)))
            self.route.append([row.get("system", ""), jumps, row.get("distance_jumped", ""), row.get("distance_left", ""), "Yes" if is_neutron else "No"])
            self.route_done.append(bool(row.get("done", False)))
            try: self.jumps_left += int(jumps)
            except Exception: pass
        if settings:
            self._store_plotter_settings("Neutron Plotter", settings)
            vias = list(settings.get("vias", []))
            self._neutron_vias = vias
            self._neutron_via_visible = bool(vias)
            try: self._refresh_neutron_vias()
            except Exception: pass

    def _apply_fleet_waypoint_flags(self, jumps, source="", destinations=None):
        wps = {str(source).strip().lower()}
        wps.update(str(d).strip().lower() for d in (destinations or []))
        wps.discard("")

        if wps or any(j.get("is_desired_destination") for j in jumps):
            for j in jumps:
                name = (j.get("name", "") or "").strip().lower()
                sys_id = str(j.get("id64", "")).strip()
                j["is_waypoint"] = bool(j.get("is_desired_destination") or name in wps or sys_id in wps)
        else:
            names = [(j.get("name", "") or "").strip().lower() for j in jumps]
            counts = Counter(names)
            dupes = {n for n, c in counts.items() if c > 1}
            for i, j in enumerate(jumps):
                j["is_waypoint"] = bool(i == 0 or i == len(jumps) - 1 or names[i] in dupes)

    def _apply_exact_route_data(self, jumps, settings=None):
        self._reset_route_data("exact", "Exact Plotter")
        self.exact_plotter = True
        self.exact_route_data = jumps
        if self.exact_route_data:
            self.exact_route_data[0]["must_refuel"] = True
        for i, jump in enumerate(self.exact_route_data):
            jump.setdefault("done", False)
            self.route.append([jump.get("name", ""), "1" if i > 0 else "0", str(jump.get("distance", 0)), str(jump.get("distance_to_destination", 0))])
        self.jumps_left = max(0, len(jumps) - 1)
        self._sync_runtime_route_rows()
        if settings is not None:
            self._store_plotter_settings("Exact Plotter", settings)

    def _apply_fleet_route_data(self, jumps, params):
        self._reset_route_data("fleet_carrier", "Fleet Carrier Router")
        self.fleetcarrier = True
        self.fleet_carrier_data = jumps
        for jump in self.fleet_carrier_data:
            jump.setdefault("done", False)
        self._apply_fleet_waypoint_flags(self.fleet_carrier_data, source=params.get("source", ""), destinations=params.get("destinations", []))
        total_jumps = max(0, len(jumps) - 1)
        for i, jump in enumerate(jumps):
            self.route.append([jump.get("name", ""), str(max(total_jumps - i, 0)), jump.get("distance", ""), jump.get("distance_to_destination", ""), "Yes" if jump.get("must_restock") else "No"])
        self._sync_runtime_route_rows()
        settings = {
            "source": params["source"], "destinations": list(params["destinations"]),
            "refuel_destinations": list(params.get("refuel_destinations", [])),
            "carrier_type": params["carrier_type"], "used_capacity": params["used_capacity"],
            "determine_required_fuel": params["determine_required_fuel"],
            "tritium_fuel": params.get("tritium_fuel", 1000), "tritium_market": params.get("tritium_market", 0),
        }
        self._store_plotter_settings("Fleet Carrier Router", settings)

    # --- JSON Import ---

    def _detect_json_route_type(self, params, result):
        if not isinstance(params, dict):
            params = {}
        if "efficiency" in params:
            return "neutron"
        if "algorithm" in params:
            return "exact"
        if "calculate_starting_fuel" in params:
            return "fleet_carrier"
        if "body_types" in params:
            return "body_types"
        # Exomastery — detected from result data (landmarks on bodies).
        # Must be checked before use_mapping_value because exported
        # exomastery JSONs carry use_mapping_value=false in parameters.
        systems = result if isinstance(result, list) else []
        if self._route_has_exobiology_landmarks(systems):
            return "exomastery"
        if "use_mapping_value" in params:
            return "riches"
        # Fallback: list result without distinguishing params → riches
        if isinstance(result, list):
            return "riches"
        return None

    def plot_file(self):
        filename = filedialog.askopenfilename(filetypes=[('JSON files', '*.json'), ('All supported files', '*.json')], initialdir=self._dialog_initial_directory("import"))
        if filename:
            try:
                self._remember_dialog_directory("import", filename)
                self._close_csv_viewer_if_open()
                if filename.endswith(".json"): self.plot_json(filename)
                else: self.show_error("Unsupported file type. Only JSON is supported.")
            except Exception:
                self._log_unexpected("Failed to import route file")
                self.enable_plot_gui(True)
                self.show_error("(1) An error occurred while reading the file.")

    def plot_json(self, filename):
        with open(filename, 'r', encoding='utf-8-sig') as jsonfile: payload = json.load(jsonfile)
        if not isinstance(payload, dict): raise ValueError("Unsupported JSON format")

        result = payload.get("result")
        params = payload.get("parameters", {}) or {}
        if result is None: raise ValueError("Unsupported JSON format: missing 'result'")

        route_type = self._detect_json_route_type(params, result)
        if route_type is None:
            raise ValueError("Unsupported JSON format")

        self._close_csv_viewer_if_open()
        self.clear_route(show_dialog=False)

        if route_type == "neutron":
            self._import_neutron_json(result, params)
        elif route_type == "exact":
            self._import_exact_json(result, params)
        elif route_type == "fleet_carrier":
            self._import_fleet_json(result, params)
        elif route_type in ("riches", "body_types", "exomastery"):
            if not self._import_exploration_json(result, params, route_type):
                return

        self._finalize_imported_route()

    def _import_neutron_json(self, result, params):
        vias = params.get("via", params.get("vias", result.get("via", [])))
        settings = {
            "source": str(params.get("from", result.get("source_system", ""))),
            "destination": str(params.get("to", result.get("destination_system", ""))),
            "range": str(params.get("range", "")),
            "efficiency": self._safe_float(params["efficiency"], 0.6) if params.get("efficiency") not in (None, "") else 0.6,
            "supercharge_multiplier": self._normalize_supercharge_multiplier(params.get("supercharge_multiplier", 4)),
            "vias": [str(v).strip() for v in (vias if isinstance(vias, list) else [vias]) if str(v).strip()],
        }
        self._apply_neutron_route_rows(result.get("system_jumps", []), settings=settings)

    def _import_exact_json(self, result, params):
        jumps = result.get("jumps", []) if isinstance(result, dict) else []
        settings = dict(params)
        src = settings.get("source") or settings.get("source_system") or settings.get("from") or (result.get("source_system", "") if isinstance(result, dict) else "")
        dst = settings.get("destination") or settings.get("destination_system") or settings.get("to") or (result.get("destination_system", "") if isinstance(result, dict) else "")
        settings["source"] = self._resolve_system_id(src, result)
        settings["destination"] = self._resolve_system_id(dst, result)
        if "reserve_size" in settings and "reserve" not in settings:
            settings["reserve"] = settings.pop("reserve_size")
        if isinstance(result, dict) and isinstance(result.get("jumps"), list):
            settings["refuel_destinations"] = [str(j.get("id64")) for j in result["jumps"] if j.get("must_refuel")]
        self._apply_exact_route_data(jumps, settings=settings)

    def _import_fleet_json(self, result, params):
        fleet_params = self._json_fleet_params(params, result)
        jumps = result.get("jumps", []) if isinstance(result, dict) else []
        self._apply_fleet_route_data(jumps, fleet_params)

    def _import_exploration_json(self, result, params, route_type):
        systems = result if isinstance(result, list) else []
        if route_type == "exomastery":
            planner = "Exomastery"
        elif route_type == "body_types":
            b_types = params.get("body_types", [])
            if not isinstance(b_types, list):
                b_types = [b_types]
            joined = "".join(re.sub(r'[^a-z0-9]+', '', str(v).lower()) for v in b_types if str(v).strip())
            if "ammoniaworld" in joined: planner = "Ammonia World Route"
            elif "earthlikeworld" in joined: planner = "Earth-like World Route"
            elif "highmetalcontent" in joined or "rockybody" in joined: planner = "Rocky/HMC Route"
            else: planner = "Road to Riches"
        else:
            planner = "Road to Riches"
        self._apply_exploration_route_data(planner, systems, body_types=params.get("body_types"))
        self._store_plotter_settings(planner, self._json_exploration_settings(params, systems, planner))
        if self.route:
            return True
        self.show_error("No route found in JSON.")
        return False

    def _json_fleet_params(self, params, result):
        jumps = result.get("jumps", []) if isinstance(result, dict) else []
        source = self._resolve_system_id(result.get("source", params.get("source_system", "")), result)

        dest_ids = params.get("destination_systems") or result.get("destinations", [])
        destinations = [self._resolve_system_id(d, result) for d in dest_ids]
        destinations = [n for n in destinations if n and not n.isdigit()]
        if not destinations:
            seen = {source.lower()}
            for j in jumps:
                name = str(j.get("name", "")).strip()
                if name and (j.get("is_desired_destination") or j.get("is_waypoint")) and name.lower() not in seen:
                    seen.add(name.lower()); destinations.append(name)
        if not destinations and jumps:
            last = str(jumps[-1].get("name", "")).strip()
            if last: destinations = [last]

        ref_ids = params.get("refuel_destinations") or result.get("refuel_destinations", [])
        refuels = [n for n in (self._resolve_system_id(r, result) for r in ref_ids) if n]

        return {
            "source": source, "destinations": destinations, "refuel_destinations": refuels,
            "carrier_type": self._infer_fleet_carrier_type(explicit_type=params.get("carrier_type", result.get("carrier_type", "")), capacity=self._safe_int(params.get("capacity", result.get("capacity"))), mass=self._safe_int(params.get("mass", result.get("mass")))),
            "used_capacity": self._safe_int(params.get("capacity_used", result.get("capacity_used")), 0),
            "determine_required_fuel": bool(params.get("calculate_starting_fuel", result.get("calculate_starting_fuel", False))),
            "tritium_fuel": self._safe_int(params.get("current_fuel", result.get("tritium_stored")), 0),
            "tritium_market": self._safe_int(params.get("tritium_amount", result.get("fuel_loaded")), 0),
        }

    def _json_exploration_settings(self, params, result, planner):
        src = str(params.get("source") or params.get("from") or "").strip()
        dst = str(params.get("destination") or params.get("to") or "").strip()
        res_src = self._resolve_system_id(src, result) if src else ""
        res_dst = self._resolve_system_id(dst, result) if dst else ""
        if res_src.isdigit(): res_src = ""
        if res_dst.isdigit(): res_dst = ""

        return {
            "source": res_src, "destination": res_dst,
            "range": params.get("range") or "",
            "radius": params.get("radius") or "",
            "max_results": params.get("max_results") or "",
            "max_distance": params.get("max_distance") or "",
            "min_value": params.get("min_value") or "",
            "use_mapping_value": bool(params.get("use_mapping_value")),
            "avoid_thargoids": bool(params.get("avoid_thargoids")),
            "loop": bool(params.get("loop")),
            "planner": planner,
        }

    # --- JSON Export ---

    def _spansh_json_export_payload(self):
        """Build a Spansh-compatible JSON payload for the current route (re-importable by plot_json)."""
        status = {"status": "ok", "state": "completed", "job": ""}
        if self.route_type == "exploration" and self.exploration_route_data:
            return self._exploration_export_payload(status)
        if self.route_type == "fleet_carrier" and self.fleet_carrier_data:
            return self._fleet_export_payload(status)
        if self.route_type == "exact" and self.exact_route_data:
            return self._exact_export_payload(status)
        if self.route_type == "neutron" and self.route:
            return self._neutron_export_payload(status)
        return None

    _SPECIALIZED_BODY_TYPES = {
        "Ammonia World Route": ["Ammonia world"],
        "Earth-like World Route": ["Earth-like world"],
        "Rocky/HMC Route": ["Rocky body", "High metal content world"],
    }

    def _exploration_export_payload(self, status):
        exp_type = self._get_exploration_type()
        mode_name = self.exploration_mode or "Road to Riches"
        settings = self._settings_for_planner(mode_name)
        settings.setdefault("source", self._route_source_name(""))
        settings.setdefault("destination", self._route_destination_name(""))
        settings["planner"] = mode_name
        if exp_type == "spec":
            settings["body_types"] = self._SPECIALIZED_BODY_TYPES.get(mode_name, [])
            settings["min_value"] = 1
        return {**status, "parameters": settings, "result": self.exploration_route_data}

    def _fleet_export_payload(self, status):
        settings = self._settings_for_planner("Fleet Carrier Router")
        settings.setdefault("source", self._route_source_name(""))
        settings.setdefault("destinations", [self._route_destination_name("")])
        profile = self._fleet_carrier_profile(settings.get("carrier_type", "fleet"))
        return {
            **status,
            "parameters": {
                "source_system": settings.get("source", ""),
                "destination_systems": list(settings.get("destinations", [])),
                "refuel_destinations": list(settings.get("refuel_destinations", [])),
                "carrier_type": profile["carrier_type"],
                "capacity": profile["capacity"],
                "mass": profile["mass"],
                "capacity_used": self._safe_int(settings.get("used_capacity"), 0),
                "calculate_starting_fuel": bool(settings.get("determine_required_fuel")),
                "current_fuel": self._safe_int(settings.get("tritium_fuel"), 1000),
                "tritium_amount": self._safe_int(settings.get("tritium_market"), 0),
                "planner": "Fleet Carrier Router",
            },
            "result": {
                "source": settings.get("source", ""),
                "destinations": list(settings.get("destinations", [])),
                "refuel_destinations": list(settings.get("refuel_destinations", [])),
                "jumps": self.fleet_carrier_data,
            },
        }

    def _exact_export_payload(self, status):
        settings = self._settings_for_planner("Exact Plotter")
        settings.setdefault("source", self._route_source_name(""))
        settings.setdefault("destination", self._route_destination_name(""))
        settings.setdefault("algorithm", "optimistic")
        return {**status, "parameters": settings, "result": {"jumps": self.exact_route_data}}

    def _neutron_export_payload(self, status):
        settings = self._settings_for_planner("Neutron Plotter")
        settings.setdefault("source", self._route_source_name(""))
        settings.setdefault("destination", self._route_destination_name(""))
        system_jumps = []
        for index in range(len(self.route)):
            row_state = self._route_row_state_at(index)
            raw = self.neutron_route_data[index] if index < len(self.neutron_route_data) else {}
            entry = {
                "system": row_state.get("name", ""),
                "jumps": row_state.get("progress", 0),
                "distance_jumped": self._safe_float(row_state.get("distance_to_arrival"), 0),
                "distance_left": self._safe_float(row_state.get("remaining_distance"), 0),
                "neutron_star": bool(row_state.get("has_neutron")),
                "done": bool(row_state.get("done")),
            }
            id64 = raw.get("id64")
            if id64 is not None:
                entry["id64"] = id64
            system_jumps.append(entry)
        return {
            **status,
            "parameters": {
                "from": settings.get("source", ""),
                "to": settings.get("destination", ""),
                "range": settings.get("range", ""),
                "efficiency": settings.get("efficiency", ""),
                "supercharge_multiplier": settings.get("supercharge_multiplier", ""),
                "planner": "Neutron Plotter",
                "via": list(settings.get("vias", [])),
            },
            "result": {
                "source_system": self._route_source_name(""),
                "destination_system": self._route_destination_name(""),
                "system_jumps": system_jumps,
            },
        }

    def save_all_route(self):
        """Persist current route state and plotter settings to disk."""
        self._save_route_state()
