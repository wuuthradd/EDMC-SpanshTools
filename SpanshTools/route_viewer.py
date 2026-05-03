"""Route viewer window — CsvViewerWindow backed by TkSheet."""

import csv
import hashlib
import json
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
from tkinter import ttk

from .web_utils import WebUtils, WebOpenError
from .widgets import bind_select_all_and_paste

from config import config
from tksheet import Sheet as TkSheet
from .constants import COLUMN_MIN_WIDTHS, logger


class CsvViewerWindow:
    """Spreadsheet-style route viewer backed by TkSheet, with search, done-toggling, and CSV/web export."""

    __slots__ = ("router",)

    def __init__(self, router):
        self.router = router

    def __getattr__(self, name):
        return getattr(self.router, name)

    def __setattr__(self, name, value):
        if name in self.__slots__:
            super().__setattr__(name, value)
        else:
            setattr(self.router, name, value)

    # --- Viewer Signature & Change Detection ---

    def _viewer_done_state_hash(self):
        """Fast FNV hash of all per-item done states."""
        h = 2166136261
        if self.route_type == "exploration" and self.exploration_route_data:
            is_exo = self._get_exploration_type() == "exo"
            for system in self.exploration_route_data:
                bodies = system.get("bodies", []) or []
                if not bodies:
                    h = ((h ^ int(bool(system.get("done", False)))) * 16777619) & 0xFFFFFFFF
                    continue
                for body in bodies:
                    landmarks = body.get("landmarks", []) or []
                    if is_exo and landmarks:
                        for lm in landmarks:
                            h = ((h ^ int(bool(lm.get("done", False)))) * 16777619) & 0xFFFFFFFF
                    else:
                        h = ((h ^ int(bool(body.get("done", False)))) * 16777619) & 0xFFFFFFFF
        else:
            try:
                route_sig = self._route_rows_signature()
                h = route_sig[-1]
            except Exception:
                for i, done in enumerate(self._route_done_values()):
                    h = ((h ^ ((i + 1) * int(bool(done)) + int(bool(done)))) * 16777619) & 0xFFFFFFFF
        return h

    def _viewer_signature_from_model(self, columns, viewer_model):
        rows = viewer_model["rows"]
        n = len(rows)
        hasher = hashlib.blake2b(digest_size=16)

        def update_values(values, row_sep=b"\x1e", value_sep=b"\x1f"):
            for value in values:
                hasher.update(str(value).encode("utf-8", "replace"))
                hasher.update(value_sep)
            hasher.update(row_sep)

        if n <= 500:
            update_values(columns)
            for row in rows: update_values(row)
            for tags in viewer_model["tags"]: update_values(tags)
            for meta in viewer_model["meta"]:
                update_values((meta.get("mode"), meta.get("row_index"), meta.get("route_index"), meta.get("is_total"), meta.get("no_done")))
            update_values((viewer_model["current_index"], self._csv_viewer_text_size, self._csv_viewer_dark_mode))
        else:
            update_values(columns)
            hasher.update(str(n).encode())
            sample = min(20, n)
            for row in rows[:sample]: update_values(row)
            for row in rows[max(n - 10, sample):]: update_values(row)
            update_values((viewer_model["current_index"], self._csv_viewer_text_size, self._csv_viewer_dark_mode))
            try: hasher.update(str(self._viewer_done_state_hash()).encode())
            except Exception: logger.debug("Failed to compute done state hash", exc_info=True)

        return hasher.hexdigest()

    # --- Viewer Refresh ---

    def _refresh_existing_sheet(self, columns, viewer_model, signature, *, preserve_view=False):
        """Incrementally update the sheet data and highlights without rebuilding the window."""
        runtime = self._csv_viewer_runtime
        if not runtime: return False
        win, sheet, sheet_state, columns_state = runtime.get("win"), runtime.get("sheet"), runtime.get("sheet_state"), runtime.get("columns_state")
        if not win or not sheet or not sheet_state or not columns_state: return False
        try:
            if not win.winfo_exists(): return False
        except Exception: return False

        if tuple(columns_state.get("value", ())) != tuple(columns): return False

        sheet_state["all_rows"] = viewer_model["rows"]
        sheet_state["all_meta"] = viewer_model["meta"]
        sheet_state["all_tags"] = viewer_model["tags"]
        columns_state["value"] = columns
        self._csv_viewer_signature = signature

        current_yview = current_xview = None
        if preserve_view:
            try: current_yview = sheet.get_yview()
            except Exception: pass
            try: current_xview = sheet.get_xview()
            except Exception: pass

        try:
            if callable(sheet_state.get("apply_search_filter")):
                sheet_state["apply_search_filter"](preserve_view=preserve_view, redraw=False)
            else:
                sheet_state["rows"] = list(sheet_state["all_rows"])
                sheet_state["meta"] = list(sheet_state["all_meta"])
                sheet_state["tags"] = list(sheet_state["all_tags"])
                # We don't dehighlight here because apply_highlights (refresh_theme) does it properly
                sheet.set_sheet_data([list(row) for row in sheet_state["rows"]], reset_col_positions=False, reset_row_positions=False, redraw=False, reset_highlights=False)

                if callable(sheet_state.get("refresh_theme")):
                    sheet_state["refresh_theme"](redraw=False)
                if callable(sheet_state.get("apply_sheet_column_widths")):
                    sheet_state["apply_sheet_column_widths"](remeasure=False, adjust_window=True, redraw=False)

                if preserve_view:
                    if current_yview is not None:
                        try: sheet.set_yview(current_yview[0])
                        except Exception: pass
                    if current_xview is not None:
                        try: sheet.set_xview(current_xview[0])
                        except Exception: pass
                else:
                    current_index = viewer_model.get("current_index", -1)
                    if 0 <= current_index < len(sheet_state["rows"]):
                        try: sheet.see(current_index, 0, bottom_right_corner=False, check_cell_visibility=False, redraw=False)
                        except Exception: pass
                sheet.refresh()
            return True
        except Exception:
            self._csv_viewer_runtime = None
            self._log_unexpected("Failed to refresh route viewer in place")
            return False

    def _refresh_viewer_in_place(self, *, preserve_view=False):
        columns, viewer_model, signature = self._build_viewer_state()
        return self._refresh_existing_sheet(columns, viewer_model, signature, preserve_view=preserve_view)

    # --- Window Lifecycle ---

    def _open_viewer_window(self, signature, *, force_refresh=False, restore_geometry=None):
        geometry = restore_geometry
        if self.csv_viewer_win:
            try:
                if self.csv_viewer_win.winfo_exists():
                    if self._csv_viewer_signature == signature and not force_refresh:
                        self.csv_viewer_win.deiconify()
                        self.csv_viewer_win.lift()
                        self.csv_viewer_win.focus_force()
                        return None
                    geometry = geometry or self.csv_viewer_win.geometry()
                    win = self.csv_viewer_win
                    self._csv_viewer_runtime = None
                    for child in win.winfo_children():
                        try: child.destroy()
                        except Exception: pass
                    self._csv_viewer_signature = signature
                    try:
                        if geometry: win.geometry(geometry)
                    except Exception: pass
                    try:
                        win.deiconify()
                        win.lift()
                    except Exception: pass
                    return win
            except tk.TclError: pass
            self._close_csv_viewer()

        win = tk.Toplevel(self.parent)
        planner_name = self._current_route_planner_name() if hasattr(self, "_current_route_planner_name") else ""
        win.title(f"Route Viewer ({planner_name})" if planner_name else "Route Viewer")
        win.resizable(True, True)
        win.minsize(700, 150)
        if geometry:
            try: win.geometry(geometry)
            except Exception: pass

        self.csv_viewer_win = win
        self._csv_viewer_signature = signature
        win.protocol("WM_DELETE_WINDOW", lambda: win.withdraw())
        return win

    def _close_csv_viewer(self):
        self.csv_viewer_win = self._csv_viewer_signature = self._csv_viewer_runtime = None

    def _initial_sheet_state(self):
        return {
            "widget": None, "rows": [], "meta": [], "tags": [],
            "all_rows": [], "all_meta": [], "all_tags": [],
            "resize_after_id": None, "refresh_theme": None,
            "apply_sheet_column_widths": None, "apply_search_filter": None, "ready_for_resize": False,
            "search_label": None, "search_entry": None,
            "search_clear_button": None,
            "topbar": None, "file_button": None, "view_button": None,
            "file_menu": None, "view_menu": None,
        }

    # --- Formatting & Utility Helpers ---

    def _yes_if(self, value): return "Yes" if bool(value) else ""
    def _yes_no(self, value): return "Yes" if bool(value) else "No"

    def _fleet_icy_ring_text(self, jump, false_text=""):
        if jump.get("has_icy_ring") and jump.get("is_system_pristine"): return "Pristine"
        return "Yes" if jump.get("has_icy_ring") else false_text

    def _route_total_jumps(self, row_count): return row_count - 1 if row_count > 1 else 0

    def _add_int_value(self, total, value):
        try: return total + int(value)
        except (TypeError, ValueError): return total

    def _apply_viewer_scrollbar_style(self, sheet, *, dark):
        try:
            style = ttk.Style()
            style.theme_use("clam")
            palette = {
                "trough": "#252525" if dark else "#f2f2f2",
                "thumb": "#555555" if dark else "#c9c9c9",
                "active": "#7a7a7a" if dark else "#a9a9a9",
                "arrow": "#f0f0f0" if dark else "#404040",
                "border": "#252525" if dark else "#f2f2f2",
            }
            for orientation in ("Vertical", "Horizontal"):
                name = f"Sheet{sheet.unique_id}.{orientation}.TScrollbar"
                style.configure(
                    name,
                    troughcolor=palette["trough"],
                    background=palette["thumb"],
                    lightcolor=palette["thumb"],
                    darkcolor=palette["thumb"],
                    bordercolor=palette["border"],
                    relief="flat",
                    troughrelief="flat",
                    borderwidth=0,
                    arrowsize=13,
                )
                style.map(
                    name,
                    background=[
                        ("pressed", palette["active"]),
                        ("active", palette["active"]),
                        ("!active", palette["thumb"]),
                    ],
                    foreground=[
                        ("pressed", palette["arrow"]),
                        ("active", palette["arrow"]),
                        ("!active", palette["arrow"]),
                    ],
                    arrowcolor=[
                        ("pressed", palette["arrow"]),
                        ("active", palette["arrow"]),
                        ("!active", palette["arrow"]),
                    ],
                )
        except Exception:
            pass

    # --- Done-State Lookup & Navigation ---

    def _exploration_done_item_at(self, row_index):
        current_index = 0
        is_exo = self._get_exploration_type() == "exo"
        for system in self.exploration_route_data:
            bodies = system.get("bodies", [])
            if not bodies:
                if current_index == row_index: return system
                current_index += 1
                continue
            for body in bodies:
                landmarks = body.get("landmarks", [])
                if is_exo and landmarks:
                    for landmark in landmarks:
                        if current_index == row_index: return landmark
                        current_index += 1
                else:
                    if current_index == row_index: return body
                    current_index += 1
        return None

    def _route_index_from_meta(self, meta):
        if not meta or meta.get("is_total"): return None
        target_index = meta.get("row_index", -1)
        mode = meta.get("mode")
        if mode == "exploration": target_index = meta.get("route_index", target_index)
        elif mode == "fleet" and target_index >= 0: target_index = self._fleet_group_bounds(target_index)[0]
        if target_index is None: return None
        try: target_index = int(target_index)
        except (TypeError, ValueError): return None
        if not (0 <= target_index < len(self.route)): return None
        return target_index

    def _set_current_waypoint_from_meta(self, meta):
        target_index = self._route_index_from_meta(meta)
        if target_index is None: return False
        self.offset = target_index
        self.next_stop = self._route_name_at(self.offset, "")
        self._waypoint_reached = self._waypoint_reached_restock = False
        self._recalculate_jumps_left_from_offset()
        self.pleaserefuel = self._route_refuel_required_at(self.offset)
        self.compute_distances()
        self.copy_waypoint()
        self.update_gui()
        self.save_all_route()
        return True

    # --- Theme & Layout Measurement ---

    def _csv_theme_colors(self, dark):
        if dark:
            return {
                "selected_bg": "#4a6984", "selected_fg": "white", "table_grid_fg": "#4c4c4c", "header_grid_fg": "#4c4c4c",
                "table_bg": "#252525", "alternate_bg": "#2f2f2f", "header_bg": "#303030", "table_fg": "#f1f1f1",
                "header_fg": "#f5f5f5", "done_fg": "#1ea55b", "done_special_fg": "#0f6b37",
                "menu_separator": "#4c4c4c",
            }
        return {
            "selected_bg": "#dce6f2", "selected_fg": "black", "table_grid_fg": "#d0d6de", "header_grid_fg": "#c4c7c5",
            "table_bg": "#ffffff", "alternate_bg": "#e5edf7", "header_bg": "#f2f2f2", "table_fg": "black",
            "header_fg": "black", "done_fg": "#1ea55b", "done_special_fg": "#0b6e3c",
            "menu_separator": "#c4c7c5",
        }

    _cached_scrollbar_width = None

    def _get_system_scrollbar_width(self):
        if CsvViewerWindow._cached_scrollbar_width is not None:
            return CsvViewerWindow._cached_scrollbar_width
        try:
            tmp_sb = ttk.Scrollbar(self.parent)
            sb_w = tmp_sb.winfo_reqwidth()
            tmp_sb.destroy()
            CsvViewerWindow._cached_scrollbar_width = max(1, sb_w)
            return CsvViewerWindow._cached_scrollbar_width
        except Exception: return 16

    def _viewer_target_width(self, measured_widths):
        if not measured_widths: return 700
        return sum(measured_widths) + 72

    def _measure_viewer_widths(self, headers, text_size):
        margin = (text_size - 12) * 10
        widths = []
        for h in headers:
            h_str = str(h).strip()
            w = COLUMN_MIN_WIDTHS.get(h_str)
            if w is None:
                if any(k in h_str for k in ("System", "Name", "Body")): w = 440
                elif "Subtype" in h_str: w = 260
                elif any(k in h_str for k in ("(T)", "(LY)", "(Ls)", "Value")): w = 140
                elif any(k in h_str for k in ("Jumps", "Restock")): w = 120
                else: w = 100
            widths.append(max(40, w + margin))
        return widths

    # --- Column Definitions & Row Tags ---

    def _current_columns(self):
        cols = ["Done", "System Name"]

        if self.route_type == "exploration":
            exp_type = self._get_exploration_type()
            cols += ["Name"]

            if exp_type == "exo":
                cols += ["Subtype", "Distance (Ls)", "Landmark Subtype", "Count", "Landmark Value"]
            elif exp_type == "riches":
                cols += ["Subtype", "Terra", "Distance (Ls)", "Scan Value", "Mapping Value"]
            elif exp_type == "spec":
                cols += ["Distance (Ls)"]

            cols.append("Jumps") # +1 (9, 9, 5 total)
        elif self.exact_plotter or self.fleetcarrier:
            cols += ["Distance (LY)", "Remaining (LY)", "Jumps Left", "Fuel Left (T)"]
            if self.fleetcarrier: cols += ["Tritium in market", "Fuel Used (T)", "Icy ring", "Restock?", "Restock Amount"]
            else: cols += ["Fuel Used (T)", "Refuel?", "Neutron"]
        elif self._is_neutron_route_active(): cols += ["Distance (LY)", "Remaining (LY)", "Neutron", "Jumps"]
        else:
            cols.append("Jumps")
            cols += ["Distance (LY)", "Remaining (LY)"]
        return tuple(cols)

    def _viewer_row_tags(self, row_index, *, is_total=False, is_refuel=False, is_waypoint=False, is_destination=False):
        if is_total: return ("total",)
        if is_destination: return ("destination",)
        if is_waypoint: return ("waypoint",)
        if is_refuel: return ("refuel",)
        return ("odd" if row_index % 2 else "even",)

    # --- Export Payload Construction ---

    def _spansh_export_payload(self):
        """Build a (headers, rows) tuple for CSV export, returning full data for exploration/neutron routes."""
        if self.route_type == "exploration":
            exp_type = self._get_exploration_type()
            is_exo = exp_type == "exo"
            is_spec = exp_type == "spec"
            
            if is_exo: header = ["Done", "System Name", "Name", "Subtype", "Distance (Ls)", "Landmark Subtype", "Count", "Landmark Value", "Jumps"]
            elif is_spec: header = ["Done", "System Name", "Name", "Distance (Ls)", "Jumps"]
            else: header = ["Done", "System Name", "Name", "Subtype", "Terra", "Distance (Ls)", "Scan Value", "Mapping Value", "Jumps"]
            
            rows = []
            for system in self.exploration_route_data:
                sys_name, bodies, jumps = system.get("name", ""), system.get("bodies", []), self._safe_int(system.get("jumps", 1), 1)
                for body_idx, body in enumerate(bodies):
                    dist = body.get("distance_to_arrival", "")
                    if is_exo:
                        for lm_idx, lm in enumerate(body.get("landmarks", [])):
                            rows.append([self._done_cell_value(lm.get("done", False)), sys_name, body.get("name", ""), body.get("subtype", ""), dist, lm.get("subtype", ""), lm.get("count", ""), lm.get("value", ""), jumps if (body_idx == 0 and lm_idx == 0) else 0])
                    else:
                        common = [self._done_cell_value(body.get("done", False)), sys_name, body.get("name", "")]
                        if is_spec: rows.append(common + [dist, jumps if body_idx == 0 else 0])
                        else: rows.append(common + [body.get("subtype", ""), self._yes_no(body.get("is_terraformable")), dist, body.get("estimated_scan_value", ""), body.get("estimated_mapping_value", ""), jumps if body_idx == 0 else 0])
            return header, rows

        if self.fleetcarrier and self.fleet_carrier_data:
            return None, None  # fallback uses table data; _viewer_export_csv inserts Is Waypoint
        elif self.exact_plotter and self.exact_route_data:
            return None, None  # fallback uses table data
        elif self._is_neutron_route_active():
            vias = {str(v).strip().lower() for v in getattr(self, "_neutron_vias", [])}
            header = ["Done", "System Name", "Is Via", "Distance (LY)", "Remaining (LY)", "Neutron", "Jumps"]
            rows = []
            for i in range(len(self.route)):
                rs = self._route_row_state_at(i)
                name = str(rs.get("name", "")).strip()
                rows.append([self._done_cell_value(self._route_done_at(i)), name, self._yes_no(name.lower() in vias),
                    rs.get("distance_to_arrival", ""), rs.get("remaining_distance", ""),
                    self._yes_no(rs.get("has_neutron")), rs.get("progress", "")])
            return header, rows
        else: return None, None

    # --- Done-State Management ---

    def _toggle_exploration_done_row(self, row_index):
        target = None
        runtime = self._csv_viewer_runtime or {}
        sheet_state = runtime.get("sheet_state") or {}
        meta = (sheet_state.get("meta") or [])[row_index] if 0 <= row_index < len(sheet_state.get("meta") or []) else None
        if meta:
            target = meta.get("done_ref")
        if target is None:
            target = self._exploration_done_item_at(row_index)
        if target is None: return False
        target["done"] = not target.get("done", False)
        self._invalidate_route_rows()
        return True

    def _toggle_done_for_meta(self, meta):
        """Toggle done state using the resolved meta reference to avoid filtered-index mismatches."""
        mode, row_index = meta.get("mode"), meta.get("row_index", -1)
        if row_index < 0: return False
        if mode == "exploration":
            target = meta.get("done_ref")
            if target is not None:
                target["done"] = not target.get("done", False)
                self._invalidate_route_rows()
                return True
            return self._toggle_exploration_done_row(row_index)
        if mode == "exact" and row_index < len(self.exact_route_data):
            self.exact_route_data[row_index]["done"] = not self.exact_route_data[row_index].get("done", False)
            self._invalidate_route_rows()
            return True
        if mode == "fleet" and row_index < len(self.fleet_carrier_data):
            group_start, group_end = self._fleet_group_bounds(row_index)
            target_done = not self.fleet_carrier_data[group_start].get("done", False)
            for group_index in range(group_start, min(group_end + 1, len(self.fleet_carrier_data))):
                self.fleet_carrier_data[group_index]["done"] = target_done
            self.router.route_done = self._route_done_values()
            self._invalidate_route_rows()
            return True
        if mode == "route" and row_index < len(self.route_done):
            self.route_done[row_index] = not self.route_done[row_index]
            self._invalidate_route_rows()
            return True
        return False

    def _done_value_for_meta(self, meta):
        mode, row_index = meta.get("mode"), meta.get("row_index", -1)
        if row_index < 0: return False
        if mode == "exploration":
            target = meta.get("done_ref") or self._exploration_done_item_at(row_index)
            return bool(target.get("done", False)) if target else False
        if mode == "exact" and row_index < len(self.exact_route_data): return self.exact_route_data[row_index].get("done", False)
        if mode == "fleet" and row_index < len(self.fleet_carrier_data): return self.fleet_carrier_data[row_index].get("done", False)
        if mode == "route" and row_index < len(self.route_done): return self.route_done[row_index]
        return False

    def _clear_all_done_state(self):
        changed = False
        def clear(item):
            nonlocal changed
            if isinstance(item, dict) and item.get("done"): item["done"] = False; changed = True
        
        if self.route_type == "exploration" and self.exploration_route_data:
            for s in self.exploration_route_data:
                clear(s)
                for b in (s.get("bodies") or []):
                    clear(b)
                    for l in (b.get("landmarks") or []): clear(l)
        else:
            data = self.fleet_carrier_data if self.fleetcarrier else (self.exact_route_data if self.exact_plotter else None)
            if data:
                for j in data: clear(j)
                if self.fleetcarrier: self.route_done = self._route_done_values()
            else:
                for i in range(len(self.route_done)):
                    if self.route_done[i]: self.route_done[i] = False; changed = True
        if changed:
            self._invalidate_route_rows()
            self.update_gui()
            self._update_overlay()
            self.save_all_route()
            self._refresh_viewer_in_place(preserve_view=True)
        return changed

    # --- Viewer Model Building ---

    def _viewer_anchor_route_index(self):
        if not self.route: return 0
        try: anchor_index = int(self.offset)
        except Exception: anchor_index = 0
        anchor_index = max(0, min(anchor_index, len(self.route) - 1))
        if self.fleetcarrier:
            previous_index = self._route_visible_prev_index(anchor_index)
            return previous_index if previous_index < anchor_index else anchor_index
        return max(anchor_index - 1, 0)

    def _build_viewer_state(self):
        cols = self._current_columns()
        model = self._build_viewer_model(cols)
        sig = self._viewer_signature_from_model(cols, model)
        return cols, model, sig

    def _build_viewer_model(self, columns):
        viewer_model = { "rows": [], "meta": [], "tags": [], "current_index": self._viewer_anchor_route_index() }
        def add_row(vals, tags, mode, idx, is_total=False, no_done=False, system_name="", body_name=""):
            viewer_model["rows"].append(list(vals))
            viewer_model["tags"].append(tuple(tags))
            viewer_model["meta"].append({"mode": mode, "row_index": idx, "is_total": is_total, "no_done": no_done, "system_name": system_name, "body_name": body_name})

        if self.route_type == "exploration":
            anchor = self._viewer_anchor_route_index()
            viewer_model["current_index"] = -1
            for i, row in enumerate(self._exploration_view_rows()):
                add_row(row["values"], self._viewer_row_tags(i, is_total=row["is_total"]), "exploration", i, row["is_total"], row["no_done"], system_name=row.get("system_name", ""), body_name=row.get("body_name", ""))
                viewer_model["meta"][-1]["route_index"] = row["route_index"]
                viewer_model["meta"][-1]["done_ref"] = row.get("done_ref")
                if not row["is_total"] and viewer_model["current_index"] == -1 and row["route_index"] == anchor:
                    viewer_model["current_index"] = i
            return viewer_model

        data = self.fleet_carrier_data if self.fleetcarrier else (self.exact_route_data if self.exact_plotter else None)
        if data:
            t_dist = t_fuel = t_restock = 0.0
            t_jumps = self._route_total_jumps(len(data))
            mode = "fleet" if self.fleetcarrier else "exact"
            for i, jump in enumerate(data):
                dist, fuel = self._safe_float(jump.get("distance"), 0) or 0, self._safe_float(jump.get("fuel_used"), 0) or 0
                t_dist += dist; t_fuel += fuel
                row = [self._done_cell_value(jump.get("done", False)), jump.get("name", ""), self._format_decimal_number(dist, decimals=2), self._format_decimal_number(jump.get("distance_to_destination", 0), decimals=2), max(t_jumps - i, 0), self._format_decimal_number(jump.get("fuel_in_tank", 0), decimals=2) if not self.fleetcarrier else self._format_whole_number(jump.get("fuel_in_tank", 0))]
                if self.fleetcarrier:
                    restock = self._safe_int(jump.get("restock_amount"), 0)
                    t_restock += restock
                    row += [self._format_whole_number(jump.get("tritium_in_market", 0)), self._format_whole_number(fuel), self._fleet_icy_ring_text(jump), self._yes_if(jump.get("must_restock")), self._format_whole_number(restock) if restock else ""]
                    tags = self._viewer_row_tags(i, is_waypoint=bool(jump.get("is_waypoint")))
                else:
                    row += [self._format_decimal_number(fuel, decimals=2), self._yes_if(jump.get("must_refuel")), self._yes_if(jump.get("has_neutron"))]
                    tags = self._viewer_row_tags(i, is_refuel=bool(jump.get("must_refuel")), is_destination=i == len(data)-1)
                add_row(row, tags, mode, i)
            totals = ["Total", f"{self._format_whole_number(len(data))} systems", self._format_decimal_number(t_dist, decimals=2), "", t_jumps, ""]
            if self.fleetcarrier:
                totals += ["", self._format_whole_number(t_fuel), "", "", self._format_whole_number(t_restock) if t_restock else ""]
            else:
                totals += [self._format_decimal_number(t_fuel, decimals=2), "", ""]
            add_row(totals, ("total",), mode, -1, is_total=True, no_done=True)
            return viewer_model

        if self._is_neutron_route_active():
            t_dist = t_jumps = 0
            highlights = {str(v).strip().lower() for v in getattr(self, "_neutron_vias", [])}
            for i in range(len(self.route)):
                rs = self._route_row_state_at(i)
                dist, rem, j = self._safe_float(rs.get("distance_to_arrival"), 0), self._safe_float(rs.get("remaining_distance"), 0), rs.get("progress", 0)
                t_dist += dist; t_jumps = self._add_int_value(t_jumps, j)
                name = str(rs.get("name", "")).strip().lower()
                row = [self._done_cell_value(self._route_done_at(i)), rs.get("name", ""), self._format_decimal_number(dist, decimals=2), self._format_decimal_number(rem, decimals=2), self._yes_if(rs.get("has_neutron")), j]
                tags = self._viewer_row_tags(i, is_destination=i == len(self.route)-1 or name in highlights)
                add_row(row, tags, "route", i)
            add_row(["Total", "", self._format_decimal_number(t_dist, decimals=2), "", "", t_jumps], ("total",), "route", -1, is_total=True, no_done=True)
            return viewer_model

        for i, row_data in enumerate(self.route):
            vals = [self._done_cell_value(self.route_done[i] if i < len(self.route_done) else False)]
            for j, val in enumerate(row_data):
                if j in (2, 3): val = self._format_decimal_number(val, decimals=2)
                vals.append(val)
                if len(vals) >= len(columns): break
            while len(vals) < len(columns): vals.append("")
            is_total = bool(len(vals) > 1 and vals[1] == "Total")
            add_row(vals, self._viewer_row_tags(i, is_total=is_total), "route", i, is_total=is_total)
        return viewer_model

    # --- Cell Selection & Metadata ---

    def _viewer_row_col(self, sheet):
        try:
            sel = sheet.get_currently_selected()
            if not sel: return None, None
            r, c = getattr(sel, "row", None), getattr(sel, "column", None)
            if r is None: r, c = sel[0], sel[1]
            return int(r), int(c)
        except Exception: return None, None

    def _viewer_selected_meta(self, sheet, columns, sheet_state=None):
        r, c = self._viewer_row_col(sheet)
        if r is None or c is None: return None, None, None
        col_name = columns[c] if c < len(columns) else ""
        val = str(sheet.get_cell_data(r, c) or "").strip()
        sys_name = ""
        meta_list = sheet_state.get("meta") if sheet_state else None
        if meta_list and r < len(meta_list):
            row_meta = meta_list[r]
            sys_name = str(row_meta.get("system_name") or "").strip()
            if not val:
                if col_name in ("System Name", "System"):
                    val = sys_name
                elif col_name in ("Body Name", "Name"):
                    val = str(row_meta.get("body_name") or "").strip()
        return col_name, val, sys_name

    # --- Dialogs & Web Integration ---

    def _viewer_warn(self, win, title, msg):
        def _show():
            try:
                popup = tk.Toplevel(win)
                popup.title(title)
                popup.transient(win)
                popup.resizable(False, False)
                popup.grid_columnconfigure(0, weight=1)
                popup.grid_rowconfigure(0, weight=1)

                frame = tk.Frame(popup, padx=18, pady=16)
                frame.grid(row=0, column=0, sticky="nsew")
                frame.grid_columnconfigure(0, weight=1)
                for row in (0, 4):
                    frame.grid_rowconfigure(row, weight=1)

                tk.Label(frame, image="::tk::icons::warning").grid(row=1, column=0, pady=(0, 10))
                tk.Label(
                    frame,
                    text=str(msg),
                    font=("TkDefaultFont", 14, "bold"),
                    justify="center",
                    anchor="center",
                ).grid(row=2, column=0)
                tk.Button(frame, text="OK", width=14, command=popup.destroy).grid(row=3, column=0, pady=(24, 0))

                popup.update_idletasks()
                width, height = 360, 190
                x = win.winfo_rootx() + max(0, (win.winfo_width() - width) // 2)
                y = win.winfo_rooty() + max(0, (win.winfo_height() - height) // 2)
                popup.geometry(f"{width}x{height}+{x}+{y}")
                popup.grab_set()
                popup.focus_set()
                popup.bind("<Return>", lambda _e: popup.destroy())
                popup.bind("<Escape>", lambda _e: popup.destroy())
            except Exception:
                pass

        try:
            win.after(0, _show)
        except Exception:
            pass

    def _viewer_extract_ids(self, sheet, sheet_state, body_name=None):
        sid64, bid64 = None, None
        r, _ = self._viewer_row_col(sheet)
        meta_list = sheet_state.get("meta") if sheet_state else None
        if r is None or not meta_list or r >= len(meta_list):
            return sid64, bid64
        meta = meta_list[r]
        mode = meta.get("mode", "")
        row_index = meta.get("row_index", -1)

        if mode == "exact" and self.exact_route_data and 0 <= row_index < len(self.exact_route_data):
            sid64 = self.exact_route_data[row_index].get("id64")
        elif mode == "fleet" and self.fleet_carrier_data and 0 <= row_index < len(self.fleet_carrier_data):
            sid64 = self.fleet_carrier_data[row_index].get("id64")
        elif mode == "exploration":
            route_index = meta.get("route_index", -1)
            if self.exploration_route_data and 0 <= route_index < len(self.exploration_route_data):
                system = self.exploration_route_data[route_index]
                sid64 = system.get("id64")
                if body_name:
                    body_key = body_name.strip().lower()
                    for body in system.get("bodies", []) or []:
                        if str(body.get("name", "")).strip().lower() == body_key:
                            bid64 = body.get("id64")
                            break
        elif mode == "route":
            neutron_data = getattr(self, "neutron_route_data", None) or []
            if neutron_data and 0 <= row_index < len(neutron_data):
                sid64 = neutron_data[row_index].get("id64")

        return sid64, bid64

    def _viewer_open_web(self, win, sheet, cols, target="edsm", sheet_state=None):
        c_name, val, s_name = self._viewer_selected_meta(sheet, cols, sheet_state=sheet_state)
        if not val: return
        is_body = c_name in ("Body Name", "Name")
        sys = s_name if is_body else val
        sid64, bid64 = self._viewer_extract_ids(sheet, sheet_state, body_name=val if is_body else None)

        def _w():
            try:
                if target == "edsm":
                    WebUtils.open_edsm(sys, val if is_body else None, sid64=sid64)
                else:
                    WebUtils.open_spansh(sys, val if is_body else None, bid64=bid64, sid64=sid64)
            except WebOpenError as exc:
                self._viewer_warn(win, "Error", str(exc))
            except Exception:
                self._viewer_warn(win, "Error", f"{target.title()} error")

        threading.Thread(target=_w, daemon=True).start()

    # --- Export & Clipboard Operations ---

    def _viewer_export_csv(self, win, cols, sheet_state):
        fn = filedialog.asksaveasfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")], defaultextension=".csv",
                                       initialdir=self._dialog_initial_directory("export"),
                                       initialfile=self._default_export_filename(".csv"), parent=win)
        if not fn: return
        try:
            self._remember_dialog_directory("export", fn)
            with open(fn, "w", newline="") as cf:
                w = csv.writer(cf)
                pay = self._spansh_export_payload()
                if pay and pay[0] is not None:
                    h, r = pay
                    w.writerow(h)
                    for row in r: w.writerow(row)
                else:
                    export_cols = list(cols)
                    export_rows = [list(row) for row in sheet_state["rows"]]
                    if self.fleetcarrier and self.fleet_carrier_data:
                        export_cols.insert(2, "Is Waypoint")
                        meta_list = sheet_state.get("meta") or []
                        for i, row in enumerate(export_rows):
                            ri = meta_list[i].get("row_index", -1) if i < len(meta_list) else -1
                            row.insert(2, self._yes_no(self.fleet_carrier_data[ri].get("is_waypoint")) if 0 <= ri < len(self.fleet_carrier_data) else "")
                    # Fill "No" for boolean columns that show blank in the table
                    bool_cols = {"Refuel?", "Neutron", "Restock?", "Is Waypoint", "Icy ring"}
                    bool_idx = [i for i, c in enumerate(export_cols) if c in bool_cols]
                    if bool_idx:
                        for row in export_rows:
                            for ci in bool_idx:
                                if ci < len(row) and not str(row[ci]).strip():
                                    row[ci] = "No"
                    w.writerow(export_cols)
                    for row in export_rows: w.writerow(row)
        except Exception as e: self._viewer_warn(win, "Error", f"CSV export failed: {e}")

    def _viewer_export_json(self, win):
        fn = filedialog.asksaveasfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")], defaultextension=".json",
                                       initialdir=self._dialog_initial_directory("export"),
                                       initialfile=self._default_export_filename(".json"), parent=win)
        if not fn: return
        try:
            self._remember_dialog_directory("export", fn)
            pay = self._spansh_json_export_payload()
            if pay is None: raise ValueError("JSON export unavailable.")
            with open(fn, "w", encoding="utf-8") as jf: json.dump(pay, jf, indent=2)
        except Exception as e: self._viewer_warn(win, "Error", f"JSON export failed: {e}")

    def _viewer_copy_table(self, cols, rows):
        lines = ["\t".join(cols)]
        for r in rows:
            v = [str(self._done_cell_value(val) if isinstance(val, bool) else val).strip() for val in r]
            if any(v): lines.append("\t".join(v))
        self._copy_to_clipboard("\n".join(lines))

    def _viewer_copy_cell(self, sheet, cols, sheet_state=None):
        r, c = self._viewer_row_col(sheet)
        if r is None or c is None:
            try: sheet.MT.ctrl_c()
            except Exception: pass
            return
        v = str(sheet.get_cell_data(r, c) or "").strip()
        if not v:
            c_n = cols[c].strip().lower() if c < len(cols) else ""
            meta_list = sheet_state.get("meta") if sheet_state else None
            if meta_list and r < len(meta_list):
                row_meta = meta_list[r]
                if c_n in ("system name", "system"):
                    v = str(row_meta.get("system_name") or "").strip()
                elif c_n in ("body name", "name"):
                    v = str(row_meta.get("body_name") or "").strip()
        if v: self._copy_to_clipboard(v)
        else:
            try: sheet.MT.ctrl_c()
            except Exception: pass

    # --- Main Viewer Window Construction ---

    def show(self, force_refresh=False, restore_geometry=None):
        if not self.route and not self.exploration_route_data:
            if self.csv_viewer_win:
                try: self.csv_viewer_win.withdraw()
                except Exception: pass
            return

        columns, viewer_model, signature = self._build_viewer_state()

        if self.csv_viewer_win and self.csv_viewer_win.winfo_exists():
            if self._csv_viewer_signature != signature:
                force_refresh = True
            if self.csv_viewer_win.state() == 'withdrawn':
                try:
                    if self._csv_viewer_runtime and "sheet" in self._csv_viewer_runtime:
                        self._csv_viewer_runtime["sheet"].deselect("all")
                except Exception: pass
                
                self.csv_viewer_win.deiconify()
                self.csv_viewer_win.update()
                
                try:
                    if self._csv_viewer_runtime and "sheet" in self._csv_viewer_runtime:
                        c_idx = viewer_model.get("current_index", -1)
                        if c_idx >= 0:
                            self._csv_viewer_runtime["sheet"].see(c_idx, 0, bottom_right_corner=False, check_cell_visibility=False, redraw=True)
                except Exception: pass

                self.csv_viewer_win.lift()
        
        measured_widths = self._measure_viewer_widths(list(columns[1:]), self._csv_viewer_text_size)

        try:
            if force_refresh and self._refresh_existing_sheet(columns, viewer_model, signature): return
            
            win = self._open_viewer_window(signature, force_refresh=force_refresh, restore_geometry=restore_geometry)
            if win is None: return
        except Exception:
            self._log_unexpected("Failed to setup route viewer window")
            return
        if not restore_geometry:
            try: win.geometry(f"{self._viewer_target_width(measured_widths)}x360")
            except Exception: pass
            try: self._configure_child_window(win)
            except Exception: pass

        sheet_state = self._initial_sheet_state()
        dark_mode_var = tk.BooleanVar(value=self._csv_viewer_dark_mode)

        def apply_csv_theme():
            self._csv_viewer_dark_mode = bool(dark_mode_var.get())
            current_theme = self._csv_theme_colors(self._csv_viewer_dark_mode)
            try: config.set('spansh_csv_dark_mode', int(self._csv_viewer_dark_mode))
            except Exception: logger.debug("Failed to save dark mode preference", exc_info=True)
            if not sheet_state["widget"]:
                return
            try:
                sheet_state["widget"].set_options(
                    alternate_color=current_theme["alternate_bg"], table_grid_fg=current_theme["table_grid_fg"],
                    header_grid_fg=current_theme["header_grid_fg"],
                    table_bg=current_theme["table_bg"], header_bg=current_theme["header_bg"],
                    table_fg=current_theme["table_fg"], header_fg=current_theme["header_fg"],
                    table_selected_cells_bg=current_theme["selected_bg"], table_selected_rows_bg=current_theme["selected_bg"],
                    table_selected_cells_fg=current_theme["table_fg"], table_selected_rows_fg=current_theme["table_fg"],
                    header_selected_cells_bg=current_theme["selected_bg"], header_selected_cells_fg=current_theme["selected_fg"],
                    redraw=False,
                )
            except Exception: pass


            if sheet_state.get("topbar"):
                sheet_state["topbar"].configure(bg=current_theme["header_bg"])
            for button_key in ("file_button", "view_button"):
                button = sheet_state.get(button_key)
                if button:
                    button.configure(bg=current_theme["header_bg"], fg=current_theme["header_fg"],
                        activebackground=current_theme["selected_bg"], activeforeground=current_theme["selected_fg"])
            if sheet_state.get("search_label"):
                sheet_state["search_label"].configure(bg=current_theme["header_bg"], fg=current_theme["header_fg"])
            if sheet_state.get("search_entry"):
                sheet_state["search_entry"].configure(bg=current_theme["table_bg"], fg=current_theme["table_fg"],
                    insertbackground=current_theme["table_fg"])
            if sheet_state.get("search_clear_button"):
                sheet_state["search_clear_button"].configure(bg=current_theme["header_bg"], fg=current_theme["header_fg"],
                    activebackground=current_theme["selected_bg"], activeforeground=current_theme["selected_fg"])
            if sheet_state.get("separator"):
                sheet_state["separator"].configure(bg=current_theme["menu_separator"])

            try: win.config(bg=current_theme["header_bg"])
            except Exception: pass

            if callable(sheet_state.get("refresh_theme")):
                sheet_state["refresh_theme"]()
            else:
                sheet_state["widget"].refresh()
            self._apply_viewer_scrollbar_style(sheet_state["widget"], dark=self._csv_viewer_dark_mode)

        def apply_csv_text_size(size):
            self._csv_viewer_text_size = size
            try: text_size_var.set(size); config.set('spansh_csv_text_size', size)
            except Exception: logger.debug("Failed to save text size preference", exc_info=True)
            if not sheet_state["widget"]:
                return
            try:
                saved_yv = None
                try: saved_yv = sheet_state["widget"].get_yview()[0]
                except Exception: pass
                sheet_state["widget"].set_options(font=("TkDefaultFont", size, "normal"), header_font=("TkDefaultFont", size, "bold"),
                    popup_menu_font=("TkDefaultFont", size, "normal"),
                    redraw=False)
                apply_csv_theme()
                apply_sheet_column_widths(remeasure=True, adjust_window=True, redraw=False)
                sheet_state["widget"].refresh()
                if saved_yv is not None:
                    def _restore(yv=saved_yv):
                        try: sheet_state["widget"].set_yview(yv)
                        except Exception: pass
                    sheet_state["widget"].after_idle(_restore)
            except Exception: pass

        text_size_var = tk.IntVar(value=self._csv_viewer_text_size)
        win.grid_rowconfigure(2, weight=1); win.grid_columnconfigure(0, weight=1)
        columns_state = {"value": columns}

        sheet_state["all_rows"], sheet_state["all_meta"] = viewer_model["rows"], viewer_model["meta"]
        sheet_state["all_tags"] = viewer_model["tags"]
        sheet_state["rows"], sheet_state["meta"] = list(sheet_state["all_rows"]), list(sheet_state["all_meta"])
        sheet_state["tags"] = list(sheet_state["all_tags"])
        initial_theme = self._csv_theme_colors(self._csv_viewer_dark_mode)
        try: win.config(bg=initial_theme["header_bg"])
        except Exception: pass

        topbar = tk.Frame(win, bg=initial_theme["header_bg"], padx=2, pady=4, borderwidth=0, highlightthickness=0)
        topbar.grid(row=0, column=0, sticky=tk.EW)
        file_button = tk.Menubutton(topbar, text="File", bg=initial_theme["header_bg"], fg=initial_theme["header_fg"],
            activebackground=initial_theme["selected_bg"], activeforeground=initial_theme["selected_fg"],
            relief="flat", padx=6, pady=2, direction="below", borderwidth=0, highlightthickness=0)
        file_button.pack(side=tk.LEFT)
        file_menu = tk.Menu(file_button, tearoff=0)
        file_button.configure(menu=file_menu)
        view_button = tk.Menubutton(topbar, text="View", bg=initial_theme["header_bg"], fg=initial_theme["header_fg"],
            activebackground=initial_theme["selected_bg"], activeforeground=initial_theme["selected_fg"],
            relief="flat", padx=6, pady=2, direction="below", borderwidth=0, highlightthickness=0)
        view_button.pack(side=tk.LEFT, padx=(4, 0))
        view_menu = tk.Menu(view_button, tearoff=0)
        text_size_menu = tk.Menu(view_menu, tearoff=0)
        for s in (9, 10, 11, 12, 14, 16):
            text_size_menu.add_radiobutton(label=f"Font Size {s}", value=s, variable=text_size_var, command=lambda sz=s: apply_csv_text_size(sz))
        view_menu.add_cascade(label="Font Size", menu=text_size_menu)
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Dark mode", variable=dark_mode_var, command=apply_csv_theme)
        view_menu.add_command(label="Clear Done", command=self._clear_all_done_state)
        view_menu.add_separator()
        view_menu.add_command(label="Reset Column Widths", command=lambda: apply_sheet_column_widths(remeasure=True, adjust_window=True))
        view_button.configure(menu=view_menu)

        search_var = tk.StringVar()
        search_clear_button = tk.Button(topbar, text="❌", width=2, command=lambda: search_var.set(""),
            bg=initial_theme["header_bg"], fg=initial_theme["header_fg"],
            activebackground=initial_theme["selected_bg"], activeforeground=initial_theme["selected_fg"],
            relief="flat", padx=0, pady=0, bd=0)
        search_clear_button.pack(side=tk.RIGHT, padx=(4, 2))
        
        search_entry = tk.Entry(topbar, textvariable=search_var, width=24)
        search_entry.pack(side=tk.RIGHT)
        
        search_label = tk.Label(topbar, text="Search:", bg=initial_theme["header_bg"], fg=initial_theme["header_fg"], borderwidth=0, highlightthickness=0, relief="flat")
        search_label.pack(side=tk.RIGHT, padx=(0, 4))
        
        bind_select_all_and_paste(search_entry)
        sheet_state["search_label"] = search_label
        sheet_state["search_entry"] = search_entry
        sheet_state["search_clear_button"] = search_clear_button
        sheet_state["topbar"] = topbar
        sheet_state["file_button"] = file_button
        sheet_state["view_button"] = view_button
        sheet_state["file_menu"] = file_menu
        sheet_state["view_menu"] = view_menu

        separator = tk.Frame(win, height=1, bg=initial_theme["menu_separator"], borderwidth=0, highlightthickness=0)
        separator.grid(row=1, column=0, sticky=tk.EW)
        sheet_state["separator"] = separator

        def export_viewer_csv(): self._viewer_export_csv(win, columns_state["value"], sheet_state)
        def export_viewer_json(): self._viewer_export_json(win)
        file_menu.add_command(label="📤 Export CSV...", command=export_viewer_csv)
        file_menu.add_command(label="📤 Export JSON...", command=export_viewer_json)

        def copy_row():
            r, _ = self._viewer_row_col(sheet_state["widget"])
            if r is not None and r < len(sheet_state["rows"]):
                vals = [str(self._done_cell_value(v) if isinstance(v, bool) else v).strip() for v in sheet_state["rows"][r]]
                self._copy_to_clipboard("\t".join([v for v in vals if v]))

        def copy_col():
            r, c = self._viewer_row_col(sheet_state["widget"])
            if r is not None and c is not None:
                try: vals = sheet_state["widget"].get_column_data(int(c), get_displayed=True, get_header=True)
                except Exception: return
                self._copy_to_clipboard("\n".join([str(v).strip() for v in vals if str(v).strip()]))

        def copy_tbl(): self._viewer_copy_table(columns_state["value"], sheet_state["rows"])
        def set_wp():
            r, _ = self._viewer_row_col(sheet_state["widget"])
            if r is not None and r < len(sheet_state["meta"]): self._set_current_waypoint_from_meta(sheet_state["meta"][r])

        sheet = TkSheet(win, headers=list(columns_state["value"]),
            data=[list(row) for row in sheet_state["rows"]],
            show_row_index=False, show_header=True, show_top_left=False, show_horizontal_grid=True, show_vertical_grid=True,
            horizontal_grid_to_end_of_window=False, vertical_grid_to_end_of_window=False,
            empty_horizontal=0, empty_vertical=0, row_snap_scroll=True,
            alternate_color=initial_theme["alternate_bg"], table_grid_fg=initial_theme["table_grid_fg"], 
            header_grid_fg=initial_theme["header_grid_fg"],
            table_bg=initial_theme["table_bg"], header_bg=initial_theme["header_bg"], table_fg=initial_theme["table_fg"], header_fg=initial_theme["header_fg"],
            table_selected_cells_bg=initial_theme["selected_bg"], table_selected_rows_bg=initial_theme["selected_bg"],
            table_selected_cells_fg=initial_theme["table_fg"], table_selected_rows_fg=initial_theme["table_fg"],
            rc_bindings=["<ButtonRelease-3>"],
            font=("TkDefaultFont", self._csv_viewer_text_size, "normal"), header_font=("TkDefaultFont", self._csv_viewer_text_size, "bold"),
            popup_menu_font=("TkDefaultFont", self._csv_viewer_text_size, "normal"),
            width=max(700, self._viewer_target_width(measured_widths)), height=max(150, win.winfo_height()))

        sheet_state["widget"] = sheet
        sheet.grid(row=2, column=0, sticky=tk.NSEW)

        try:
            sheet.enable_bindings(("single_select", "arrowkeys", "right_click_popup_menu", "rc_select", "column_width_resize", "copy"))
            sheet.headers(list(columns_state["value"]), redraw=False)
            sheet.display_columns("all", all_columns_displayed=True, redraw=False)
            sheet.set_options(column_drag_and_drop_perform=False, redraw=False)
            sheet.column_width(0, width=72)
            sheet.lock_column_width(0)
            sheet.align_columns(0, align="center", redraw=False)
            sheet.readonly_columns(list(range(len(columns_state["value"]))), readonly=True, redraw=False)
            sheet.MT.zoom_in = lambda *a: None
            sheet.MT.zoom_out = lambda *a: None
        except Exception: pass
        self._apply_viewer_scrollbar_style(sheet, dark=self._csv_viewer_dark_mode)
        def base_row_style(idx, current_theme=None):
            if current_theme is None:
                current_theme = self._csv_theme_colors(self._csv_viewer_dark_mode)
            tags = sheet_state["tags"][idx] if idx < len(sheet_state["tags"]) else ()
            if "total" in tags: return "#11b98f", "white", tags
            if "destination" in tags: return "#3da0e3", "white", tags
            if "waypoint" in tags: return "#eb5a46", "white", tags
            if "refuel" in tags: return "#f39a19", ("white" if self._csv_viewer_dark_mode else "black"), tags
            if idx % 2 == 0: return current_theme["table_bg"], current_theme["table_fg"], tags
            return current_theme["alternate_bg"], current_theme["table_fg"], tags

        def row_has_special_highlight(tags):
            return any(t in tags for t in ("total", "destination", "waypoint", "refuel"))

        def apply_row_highlight(idx, *, redraw=False):
            if idx >= len(sheet_state["meta"]):
                return
            current_theme = self._csv_theme_colors(self._csv_viewer_dark_mode)
            meta = sheet_state["meta"][idx]
            bg, fg, tags = base_row_style(idx, current_theme)
            is_special = row_has_special_highlight(tags)
            is_done = bool(meta and not meta.get("is_total") and not meta.get("no_done") and self._done_value_for_meta(meta))
            try:
                sheet.highlight_rows(idx, bg=bg, fg=fg, redraw=False)
                if meta and meta.get("is_total"):
                    sheet.highlight_cells(
                        row=idx,
                        column=0,
                        bg=bg,
                        fg=fg,
                        redraw=False,
                        overwrite=True,
                    )
                elif meta and not meta.get("no_done"):
                    if is_done or is_special:
                        sheet.highlight_cells(
                            row=idx,
                            column=0,
                            bg=bg,
                            fg=(
                                current_theme["done_special_fg"]
                                if is_done and is_special else
                                current_theme["done_fg"]
                                if is_done else
                                current_theme["table_fg"] if is_special else fg
                            ),
                            redraw=False,
                            overwrite=True,
                        )
                    else:
                        sheet.dehighlight_cells(row=idx, column=0, redraw=False)
                if redraw:
                    sheet.refresh()
            except Exception:
                pass

        def update_sheet_done_cell(idx, checked, redraw=False):
            if idx >= len(sheet_state["rows"]): return
            sym = self._done_cell_value(checked)
            sheet_state["rows"][idx][0] = sym
            try:
                sheet.set_cell_data(idx, 0, sym, redraw=False)
                apply_row_highlight(idx, redraw=redraw)
            except Exception: pass

        def apply_search_filter(*, preserve_view=False, redraw=True):
            query = str(search_var.get() or "")
            if len(query) > 80:
                query = query[:80]
                search_var.set(query)
            query = query.strip().lower()

            current_yview = current_xview = None
            if preserve_view:
                try: current_yview = sheet.get_yview()
                except Exception: pass
                try: current_xview = sheet.get_xview()
                except Exception: pass

            if not query:
                filtered = list(zip(sheet_state["all_rows"], sheet_state["all_meta"], sheet_state["all_tags"]))
            else:
                filtered = []
                punct_trans = str.maketrans("", "", ",.")
                query_plain = query.translate(punct_trans)

                tokens = query.split()
                tokens_plain = query_plain.split() if query_plain else tokens
                for row, meta, tags in zip(sheet_state["all_rows"], sheet_state["all_meta"], sheet_state["all_tags"]):
                    matched = False
                    for value in row:
                        cell = str(value).lower()
                        if all(t in cell for t in tokens) or (query_plain and all(t in cell.translate(punct_trans) for t in tokens_plain)):
                            matched = True
                            break
                    if matched:
                        filtered.append((row, meta, tags))

            sheet_state["rows"] = [row for row, _, _ in filtered]
            sheet_state["meta"] = [meta for _, meta, _ in filtered]
            sheet_state["tags"] = [tags for _, _, tags in filtered]

            try:
                sheet.set_sheet_data([list(row) for row in sheet_state["rows"]], reset_col_positions=False, reset_row_positions=True, redraw=False, reset_highlights=False)
                if callable(sheet_state.get("refresh_theme")):
                    sheet_state["refresh_theme"](redraw=False)
                if callable(sheet_state.get("apply_sheet_column_widths")):
                    sheet_state["apply_sheet_column_widths"](remeasure=False, adjust_window=False, redraw=False)
                if preserve_view:
                    if current_yview is not None:
                        try: sheet.set_yview(current_yview[0])
                        except Exception: pass
                    if current_xview is not None:
                        try: sheet.set_xview(current_xview[0])
                        except Exception: pass
                if redraw:
                    sheet.refresh()
                    if callable(sheet_state.get("apply_sheet_column_widths")):
                        sheet_state["apply_sheet_column_widths"](remeasure=False, adjust_window=False, redraw=True)
            except Exception:
                pass

        def apply_highlights(*, redraw=True):
            try:
                sheet.deselect("all", redraw=False)
                sheet.dehighlight_all(cells=True, rows=True, columns=True, header=True, index=True, redraw=False)
            except Exception: pass

            current_theme = self._csv_theme_colors(self._csv_viewer_dark_mode)
            even_rows, odd_rows, special_idx = [], [], []
            for idx, (tags, meta) in enumerate(zip(sheet_state["tags"], sheet_state["meta"])):
                if row_has_special_highlight(tags) or (not meta.get("is_total") and not meta.get("no_done") and self._done_value_for_meta(meta)):
                    special_idx.append(idx)
                elif idx % 2 == 0:
                    even_rows.append(idx)
                else:
                    odd_rows.append(idx)
            
            try:
                if even_rows:
                    sheet.highlight_rows(even_rows, bg=current_theme["table_bg"], fg=current_theme["table_fg"], redraw=False)
                if odd_rows:
                    sheet.highlight_rows(odd_rows, bg=current_theme["alternate_bg"], fg=current_theme["table_fg"], redraw=False)
            except Exception: pass

            for idx in special_idx:
                apply_row_highlight(idx, redraw=False)

            if redraw:
                sheet.refresh()

        def apply_sheet_column_widths(remeasure=False, adjust_window=False, redraw=True):
            dw = 72
            ideal_mw = self._measure_viewer_widths(list(columns_state["value"][1:]), self._csv_viewer_text_size)
            if remeasure or not sheet_state.get("manual_widths"):
                sheet_state["manual_widths"] = ideal_mw[:]

            mw = sheet_state["manual_widths"][:]
            pin_position = sheet_state.get("ready_for_resize", False)
            if pin_position:
                y_offset = self.router._wm_y_decoration_offset(win)
                pre_parsed = self.router._parse_geometry(win)
                if pre_parsed:
                    pre_x, pre_y, pre_h = pre_parsed[2], pre_parsed[3] - y_offset, pre_parsed[1]
                else:
                    pre_x, pre_y, pre_h = win.winfo_x(), win.winfo_y() - y_offset, win.winfo_height()
            else:
                pre_x, pre_y, pre_h = 0, 0, win.winfo_height()
            win.update_idletasks()
            sw = self._get_system_scrollbar_width() if getattr(sheet, "yscroll_showing", False) else 0
            curr_w = win.winfo_width()

            if adjust_window:
                tw = sum(mw) + dw + sw
                ch = max(pre_h, 360)
                if pin_position and (pre_x > 1 or pre_y > 1):
                    win.geometry(f"{int(tw)}x{int(ch)}+{int(pre_x)}+{int(pre_y)}")
                else:
                    win.geometry(f"{int(tw)}x{int(ch)}")
                curr_w = tw

            target_cols_w = curr_w - dw - sw
            current_sum = sum(mw)
            if target_cols_w > current_sum:
                n = len(mw); delta = (target_cols_w - current_sum) // n
                leftover = int(target_cols_w - current_sum) % n
                for i in range(n):
                    mw[i] += delta
                    if i < leftover: mw[i] += 1

            sheet_state["is_stretching"] = True
            sheet.column_width(0, width=dw, redraw=False)
            for i, w in enumerate(mw): sheet.column_width(i + 1, width=int(w), redraw=False)
            sheet_state["is_stretching"] = False
            if redraw:
                try: saved_yview = sheet.get_yview()[0]
                except Exception: saved_yview = None
                sheet.refresh()
                if saved_yview is not None:
                    def _restore_yview(yv=saved_yview):
                        try: sheet.set_yview(yv)
                        except Exception: pass
                    sheet.after_idle(_restore_yview)

        def handle_release(ev=None):
            if ev and sheet.identify_region(ev) in ("cell", "table"):
                r = sheet.identify_row(ev)
                c = sheet.identify_column(ev)
                if r is not None and c == 0 and r < len(sheet_state["meta"]):
                    meta = sheet_state["meta"][r]
                    if meta and not meta.get("is_total") and not meta.get("no_done") and self._toggle_done_for_meta(meta):
                        if meta.get("mode") == "fleet":
                            # Fleet carrier groups: update all rows since grouped toggles affect multiple rows
                            for vi in range(len(sheet_state["meta"])):
                                vm = sheet_state["meta"][vi]
                                if vm and not vm.get("is_total") and not vm.get("no_done"):
                                    update_sheet_done_cell(vi, self._done_value_for_meta(vm), redraw=False)
                        else:
                            update_sheet_done_cell(r, self._done_value_for_meta(meta), redraw=False)
                        self.save_all_route()
                        sheet.deselect("all", redraw=False)
                        sheet.refresh()
                        try:
                            _, _, new_sig = self._build_viewer_state()
                            self._csv_viewer_signature = new_sig
                        except Exception: logger.debug("Failed to update viewer signature", exc_info=True)

        def run_resize():
            sheet_state["resize_after_id"] = None
            if sheet_state.get("ready_for_resize"):
                apply_sheet_column_widths(redraw=True)
        
        def schedule_resize(_ev=None):
            if not sheet_state.get("ready_for_resize"): return
            if sheet_state.get("resize_after_id"):
                win.after_cancel(sheet_state["resize_after_id"])
            sheet_state["resize_after_id"] = win.after(20, run_resize)

        def finalize_paint():
            try: win.update_idletasks(); sheet_state["ready_for_resize"] = True; apply_sheet_column_widths(remeasure=True)
            except Exception: pass

        sheet_state["refresh_theme"] = apply_highlights
        sheet_state["apply_sheet_column_widths"] = apply_sheet_column_widths
        sheet_state["apply_search_filter"] = apply_search_filter
        
        def _on_menu(ev=None):
            menu = sheet.MT.rc_popup_menu
            if not menu: return
            for label in ("🔗 Open in EDSM", "🔗 Open in Spansh"):
                try:
                    idx = menu.index(label)
                    menu.delete(idx)
                except Exception: pass
            try:
                wp_idx = menu.index("📌 Set as current waypoint")
                if wp_idx > 0 and menu.type(wp_idx - 1) == "separator":
                    menu.delete(wp_idx - 1)
            except Exception: pass

            try: menu.insert_separator(menu.index("📌 Set as current waypoint"))
            except Exception: pass
            r, c = self._viewer_row_col(sheet.MT)
            if r is None: r, c = self._viewer_row_col(sheet)
            c_n = columns_state["value"][c] if c is not None and c < len(columns_state["value"]) else ""
            meta = sheet_state["meta"][r] if r is not None and r < len(sheet_state["meta"]) else {}
            try: menu.entryconfigure(sheet.MT.PAR.ops.copy_label, command=lambda: self._viewer_copy_cell(sheet, columns_state["value"], sheet_state=sheet_state))
            except Exception: pass
            
            if c_n in ("System Name", "System", "Name", "Body Name") and not meta.get("is_total"):
                f = sheet.MT.PAR.ops.popup_menu_font
                menu.add_command(label="🔗 Open in EDSM", command=lambda: self._viewer_open_web(win, sheet, columns_state["value"], "edsm", sheet_state=sheet_state), font=f)
                menu.add_command(label="🔗 Open in Spansh", command=lambda: self._viewer_open_web(win, sheet, columns_state["value"], "spansh", sheet_state=sheet_state), font=f)

        sheet.popup_menu_add_command("📋 Copy row", copy_row, table_menu=True)
        sheet.popup_menu_add_command("📋 Copy column", copy_col, table_menu=True)
        sheet.popup_menu_add_command("📋 Copy table", copy_tbl, table_menu=True)
        sheet.popup_menu_add_command("📌 Set as current waypoint", set_wp, table_menu=True)
        sheet.MT.extra_rc_func = _on_menu
        
        def on_column_width_resize(ev):
            if sheet_state.get("ready_for_resize") and not sheet_state.get("is_stretching"):
                sheet_state["manual_widths"] = [sheet.column_width(i) for i in range(1, len(columns_state["value"]))]
        sheet.extra_bindings([("column_width_resize", on_column_width_resize)])

        sheet.MT.bind("<Control-c>", lambda ev: self._viewer_copy_cell(sheet, columns_state["value"], sheet_state=sheet_state), add="+")
        sheet.MT.bind("<ButtonRelease-1>", handle_release, add="+")
        search_var.trace_add("write", lambda *_: apply_search_filter(redraw=True))
        search_entry.bind("<Escape>", lambda _ev: (search_var.set(""), "break")[1])
        apply_csv_text_size(self._csv_viewer_text_size)

        self._csv_viewer_runtime = {"win": win, "sheet": sheet, "sheet_state": sheet_state, "columns_state": columns_state}
        win.bind("<Configure>", schedule_resize, add="+")
        
        try: sheet.refresh()
        except Exception: pass

        initial_see_index = viewer_model["current_index"]
        def _finalize_and_see():
            finalize_paint()
            if 0 <= initial_see_index < len(sheet_state["rows"]):
                try: sheet.see(initial_see_index, 0, redraw=True)
                except Exception: pass
        win.after_idle(_finalize_and_see)
