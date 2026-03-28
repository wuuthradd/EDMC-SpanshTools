"""Route viewer window — CsvViewerWindow backed by TkSheet."""

import csv
import hashlib
import json
import os
import tkinter as tk
import tkinter.font as tkfont
import tkinter.filedialog as filedialog

from config import config
from monitor import monitor
from tksheet import Sheet as TkSheet


class CsvViewerWindow:
    __slots__ = ("router",)

    def __init__(self, router):
        self.router = router

    def __getattr__(self, name):
        return getattr(self.router, name)

    @property
    def csv_viewer_win(self):
        return self.router.csv_viewer_win

    @csv_viewer_win.setter
    def csv_viewer_win(self, value):
        self.router.csv_viewer_win = value

    @property
    def _csv_viewer_signature(self):
        return self.router._csv_viewer_signature

    @_csv_viewer_signature.setter
    def _csv_viewer_signature(self, value):
        self.router._csv_viewer_signature = value

    @property
    def _csv_viewer_text_size(self):
        return self.router._csv_viewer_text_size

    @_csv_viewer_text_size.setter
    def _csv_viewer_text_size(self, value):
        self.router._csv_viewer_text_size = value

    @property
    def _csv_viewer_dark_mode(self):
        return self.router._csv_viewer_dark_mode

    @_csv_viewer_dark_mode.setter
    def _csv_viewer_dark_mode(self, value):
        self.router._csv_viewer_dark_mode = value

    @property
    def _csv_viewer_width_cache(self):
        return self.router._csv_viewer_width_cache

    @property
    def _csv_viewer_runtime(self):
        return self.router._csv_viewer_runtime

    @_csv_viewer_runtime.setter
    def _csv_viewer_runtime(self, value):
        self.router._csv_viewer_runtime = value

    @property
    def offset(self):
        return self.router.offset

    @offset.setter
    def offset(self, value):
        self.router.offset = value

    @property
    def next_stop(self):
        return self.router.next_stop

    @next_stop.setter
    def next_stop(self, value):
        self.router.next_stop = value

    @property
    def pleaserefuel(self):
        return self.router.pleaserefuel

    @pleaserefuel.setter
    def pleaserefuel(self, value):
        self.router.pleaserefuel = value

    @property
    def _waypoint_reached(self):
        return self.router._waypoint_reached

    @_waypoint_reached.setter
    def _waypoint_reached(self, value):
        self.router._waypoint_reached = value

    @property
    def _waypoint_reached_restock(self):
        return self.router._waypoint_reached_restock

    @_waypoint_reached_restock.setter
    def _waypoint_reached_restock(self, value):
        self.router._waypoint_reached_restock = value

    def _viewer_signature_from_model(self, columns, viewer_model):
        hasher = hashlib.blake2b(digest_size=16)

        def update_values(values, row_sep=b"\x1e", value_sep=b"\x1f"):
            for value in values:
                hasher.update(str(value).encode("utf-8", "replace"))
                hasher.update(value_sep)
            hasher.update(row_sep)

        update_values(columns)
        for row in viewer_model["rows"]:
            update_values(row)
        for tags in viewer_model["tags"]:
            update_values(tags)
        for meta in viewer_model["meta"]:
            update_values(
                (
                    meta.get("mode"),
                    meta.get("row_index"),
                    meta.get("route_index"),
                    meta.get("is_total"),
                    meta.get("no_done"),
                )
            )
        update_values(
            (
                viewer_model["current_index"],
                self._csv_viewer_text_size,
                self._csv_viewer_dark_mode,
            )
        )
        return hasher.hexdigest()

    def _build_viewer_state(self):
        columns = self._current_columns()
        viewer_model = self._build_viewer_model(columns)
        signature = self._viewer_signature_from_model(columns, viewer_model)
        return columns, viewer_model, signature

    def _refresh_existing_sheet(self, columns, viewer_model, signature, *, preserve_view=False):
        runtime = self._csv_viewer_runtime
        if not runtime:
            return False
        win = runtime.get("win")
        sheet = runtime.get("sheet")
        sheet_state = runtime.get("sheet_state")
        columns_state = runtime.get("columns_state")
        if not win or not sheet or not sheet_state or not columns_state:
            return False
        try:
            if not win.winfo_exists():
                return False
        except Exception:
            return False

        if tuple(columns_state.get("value", ())) != tuple(columns):
            return False

        sheet_state["rows"] = viewer_model["rows"]
        sheet_state["meta"] = viewer_model["meta"]
        sheet_state["tags"] = viewer_model["tags"]
        columns_state["value"] = columns
        self._csv_viewer_signature = signature

        current_yview = None
        current_selection = None
        if preserve_view:
            try:
                current_yview = sheet.get_yview()
            except Exception:
                current_yview = None
            try:
                current_selection = sheet.get_currently_selected()
            except Exception:
                current_selection = None

        try:
            sheet.set_sheet_data(
                [row[1:] for row in sheet_state["rows"]],
                reset_col_positions=False,
                reset_row_positions=False,
                redraw=False,
                reset_highlights=True,
            )
            sheet.row_index(
                [row[0] for row in sheet_state["rows"]],
                reset_row_positions=False,
                redraw=False,
            )
            if callable(runtime.get("refresh_theme")):
                runtime["refresh_theme"]()
            if callable(runtime.get("apply_sheet_column_widths")):
                runtime["apply_sheet_column_widths"](remeasure=False, adjust_window=False)
            if preserve_view:
                if current_yview is not None:
                    try:
                        sheet.set_yview(current_yview[0])
                    except Exception:
                        pass
                if current_selection:
                    try:
                        row = getattr(current_selection, "row", None)
                        column = getattr(current_selection, "column", None)
                        if row is None or column is None:
                            if isinstance(current_selection, (tuple, list)) and len(current_selection) >= 2:
                                row, column = current_selection[0], current_selection[1]
                        row = int(row)
                        column = int(column)
                        if 0 <= row < len(sheet_state["rows"]):
                            sheet.set_currently_selected(row=row, column=column)
                    except Exception:
                        pass
            else:
                current_index = viewer_model.get("current_index", -1)
                if 0 <= current_index < len(sheet_state["rows"]):
                    try:
                        sheet.see(
                            current_index,
                            0,
                            bottom_right_corner=False,
                            check_cell_visibility=False,
                            redraw=False,
                        )
                    except Exception:
                        pass
            sheet.refresh()
            return True
        except Exception:
            self._csv_viewer_runtime = None
            self._log_unexpected("Failed to refresh route viewer in place")
            return False

    def _refresh_viewer_in_place(self, *, preserve_view=False):
        columns, viewer_model, signature = self._build_viewer_state()
        return self._refresh_existing_sheet(columns, viewer_model, signature, preserve_view=preserve_view)

    def _open_viewer_window(self, signature, *, force_refresh=False, restore_geometry=None):
        geometry = restore_geometry
        if self.csv_viewer_win:
            try:
                if self.csv_viewer_win.winfo_exists():
                    if self._csv_viewer_signature == signature and not force_refresh:
                        self.csv_viewer_win.lift()
                        self.csv_viewer_win.focus_force()
                        return None
                    geometry = geometry or self.csv_viewer_win.geometry()
                    win = self.csv_viewer_win
                    self._csv_viewer_runtime = None
                    for child in win.winfo_children():
                        try:
                            child.destroy()
                        except Exception:
                            pass
                    self._csv_viewer_signature = signature
                    try:
                        if geometry:
                            win.geometry(geometry)
                    except Exception:
                        pass
                    try:
                        win.lift()
                    except Exception:
                        pass
                    return win
            except tk.TclError:
                pass
            self._close_csv_viewer()

        win = tk.Toplevel(self.parent)
        win.title("Route Viewer")
        win.resizable(True, True)
        win.minsize(700, 360)
        if geometry:
            try:
                win.geometry(geometry)
            except Exception:
                pass

        self.csv_viewer_win = win
        self._csv_viewer_signature = signature
        win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), self._close_csv_viewer()))
        return win

    def _initial_sheet_state(self):
        return {
            "widget": None,
            "rows": [],
            "meta": [],
            "tags": [],
            "measured_widths": [],
            "done_header_label": None,
            "resize_after_id": None,
            "refresh_theme": None,
            "ready_for_resize": False,
        }

    def _export_done_value(self, done):
        return "1" if bool(done) else ""

    def _yes_if(self, value):
        return "Yes" if bool(value) else ""

    def _yes_no(self, value):
        return "Yes" if bool(value) else "No"

    def _fleet_icy_ring_text(self, jump, false_text=""):
        if jump.get("has_icy_ring") and jump.get("is_system_pristine"):
            return "Pristine"
        return "Yes" if jump.get("has_icy_ring") else false_text

    def _route_total_jumps(self, row_count):
        return row_count - 1 if row_count > 1 else 0

    def _add_int_value(self, total, value):
        try:
            return total + int(value)
        except (TypeError, ValueError):
            return total

    def _destroy_window_if_alive(self, window):
        if window is None:
            return
        try:
            if window.winfo_exists():
                window.destroy()
        except Exception:
            pass

    def _handle_viewer_setup_failure(self, context, window):
        self._log_unexpected(context)
        self._csv_viewer_runtime = None
        self._destroy_window_if_alive(window)
        self._close_csv_viewer()

    def _exploration_done_item_at(self, row_index):
        current_index = 0
        for system in self.exploration_route_data:
            bodies = system.get("bodies", [])
            if not bodies:
                if current_index == row_index:
                    return system
                current_index += 1
                continue
            for body in bodies:
                landmarks = body.get("landmarks", [])
                if self.exploration_mode == "Exomastery" and landmarks:
                    for landmark in landmarks:
                        if current_index == row_index:
                            return landmark
                        current_index += 1
                else:
                    if current_index == row_index:
                        return body
                    current_index += 1
        return None

    def _route_index_from_meta(self, meta):
        if not meta or meta.get("is_total"):
            return None
        target_index = meta.get("row_index", -1)
        mode = meta.get("mode")
        if mode == "exploration":
            target_index = meta.get("route_index", target_index)
        elif mode == "fleet" and target_index >= 0:
            target_index = self._fleet_group_bounds(target_index)[0]
        if target_index is None:
            return None
        try:
            target_index = int(target_index)
        except (TypeError, ValueError):
            return None
        if not (0 <= target_index < len(self.route)):
            return None
        return target_index

    def _set_current_waypoint_from_meta(self, meta):
        target_index = self._route_index_from_meta(meta)
        if target_index is None:
            return False

        self.offset = target_index
        self.next_stop = self._route_name_at(self.offset, "")
        self._waypoint_reached = False
        self._waypoint_reached_restock = False
        self._recalculate_jumps_left_from_offset()
        self.pleaserefuel = self._route_refuel_required_at(self.offset)
        self.compute_distances()
        self.copy_waypoint()
        self.update_gui()
        self.save_all_route()
        return True

    def _csv_theme_colors(self, dark):
        if dark:
            return {
                "selected_bg": "#4a6984",
                "selected_fg": "white",
                "table_grid_fg": "#4c4c4c",
                "header_grid_fg": "#4c4c4c",
                "table_bg": "#252525",
                "alternate_bg": "#2f2f2f",
                "header_bg": "#303030",
                "table_fg": "#f1f1f1",
                "header_fg": "#f5f5f5",
                "index_bg": "#303030",
                "index_fg": "#f5f5f5",
                "index_done_fg": "#1ea55b",
                "index_empty_fg": "#b0b0b0",
            }
        return {
            "selected_bg": "#dce6f2",
            "selected_fg": "black",
            "table_grid_fg": "#d0d6de",
            "header_grid_fg": "#c4c7c5",
            "table_bg": "#ffffff",
            "alternate_bg": "#e5edf7",
            "header_bg": "#f2f2f2",
            "table_fg": "black",
            "header_fg": "black",
            "index_bg": "#f2f2f2",
            "index_fg": "black",
            "index_done_fg": "#1ea55b",
            "index_empty_fg": "#555555",
        }

    def _viewer_target_width(self, measured_widths):
        if not measured_widths:
            return 700
        try:
            screen_width = self.parent.winfo_screenwidth()
        except Exception:
            screen_width = 1280
        scrollbar_width = 24
        frame_padding = 44
        target_width = sum(measured_widths) + 72 + scrollbar_width + frame_padding
        return max(700, min(int(target_width), max(900, screen_width - 80)))

    def _viewer_zebra_row_style(self, row_index):
        colors = self._csv_theme_colors(self._csv_viewer_dark_mode)
        if row_index % 2 == 0:
            return colors["table_bg"], colors["table_fg"]
        return colors["alternate_bg"], colors["table_fg"]

    def _sample_viewer_rows_for_widths(self, rows):
        total = len(rows)
        if total <= 220:
            return rows
        sample_indices = set(range(min(120, total)))
        sample_indices.update(range(max(0, total - 40), total))
        step = max(1, total // 80)
        sample_indices.update(range(0, total, step))
        return [rows[index] for index in sorted(sample_indices)]

    def _measure_viewer_widths(self, headers, rows, text_size):
        column_min_widths = {
            "System Name": 180,
            "System": 180,
            "Name": 180,
            "Subtype": 140,
            "Terra": 70,
            "Distance (LS)": 120,
            "Distance (Ls)": 120,
            "Distance (Ly)": 120,
            "Remaining (Ly)": 130,
            "Landmark Subtype": 170,
            "Landmark Value": 140,
            "Landmark Value (Cr)": 140,
            "Scan Value": 130,
            "Scan Value (Cr)": 130,
            "Mapping Value": 130,
            "Mapping Value (Cr)": 130,
            "Count": 80,
            "Jumps": 110,
            "Jumps Left": 110,
            "Fuel Left (tonnes)": 130,
            "Fuel Used (tonnes)": 130,
            "Refuel?": 85,
            "Neutron": 85,
            "Tritium in market": 130,
            "Icy ring": 90,
            "Restock?": 90,
            "Restock Amount": 130,
        }
        try:
            body_font = tkfont.nametofont("TkDefaultFont").copy()
            body_font.configure(size=text_size, weight="normal")
            header_font = tkfont.nametofont("TkDefaultFont").copy()
            header_font.configure(size=text_size, weight="bold")
        except Exception:
            return [column_min_widths.get(header, 90) for header in headers]

        sampled_rows = self._sample_viewer_rows_for_widths(rows)
        widths = []
        for column_index, header in enumerate(headers, start=1):
            max_width = header_font.measure(str(header)) + 28
            for row in sampled_rows:
                if column_index >= len(row):
                    continue
                text = str(row[column_index]).strip()
                if not text:
                    continue
                max_width = max(max_width, body_font.measure(text) + 28)
            widths.append(max(column_min_widths.get(header, 90), int(max_width)))
        return widths

    def _current_columns(self):
        if self.exploration_plotter and self.exploration_mode == "Exomastery":
            return (
                "Done",
                "System Name",
                "Name",
                "Subtype",
                "Distance (LS)",
                "Landmark Subtype",
                "Count",
                "Landmark Value",
                "Jumps",
            )
        if self.exploration_plotter and self._is_specialized_exploration_mode(self.exploration_mode):
            return (
                "Done",
                "System Name",
                "Name",
                "Distance (Ls)",
                "Jumps",
            )
        if self.exploration_plotter:
            if self.exploration_mode == "Road to Riches":
                return (
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
            return (
                "Done",
                "System Name",
                "Name",
                "Subtype",
                "Is Terraformable",
                "Distance (Ls)",
                "Scan Value",
                "Mapping Value",
                "Jumps",
            )
        if self.exact_plotter:
            return (
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
        if self.fleetcarrier:
            return (
                "Done",
                "System Name",
                "Distance (Ly)",
                "Remaining (Ly)",
                "Jumps Left",
                "Fuel Left (tonnes)",
                "Tritium in market",
                "Fuel Used (tonnes)",
                "Icy ring",
                "Restock?",
                "Restock Amount",
            )
        if self._is_neutron_route_active():
            return (
                "Done",
                "System Name",
                "Distance (Ly)",
                "Remaining (Ly)",
                "Neutron",
                "Jumps",
            )
        if self.galaxy:
            return ("Done", "System", "Refuel", "Distance (Ly)", "Remaining (Ly)")
        return ("Done", "System", "Jumps", "Distance (Ly)", "Remaining (Ly)")

    def _viewer_row_tags(self, row_index, *, is_total=False, is_refuel=False, is_waypoint=False, is_destination=False):
        if is_total:
            return ("total",)
        if is_destination:
            return ("destination",)
        if is_waypoint:
            return ("waypoint",)
        if is_refuel:
            return ("refuel",)
        return ("odd" if row_index % 2 else "even",)

    def _viewer_export_rows(self):
        if self.fleetcarrier and self.fleet_carrier_data:
            rows = []
            total_distance = 0.0
            total_fuel_used = 0.0
            total_restock_amount = 0.0
            total_jumps = self._route_total_jumps(len(self.fleet_carrier_data))
            for i, jump in enumerate(self.fleet_carrier_data):
                distance = self._safe_float(jump.get("distance"), 0) or 0
                fuel_used = self._safe_float(jump.get("fuel_used"), 0) or 0
                restock_amount = self._safe_float(jump.get("restock_amount"), 0) or 0
                total_distance += distance
                total_fuel_used += fuel_used
                total_restock_amount += restock_amount
                rows.append([
                    self._done_cell_value(jump.get("done", False)),
                    jump.get("name", ""),
                    jump.get("distance", ""),
                    jump.get("distance_to_destination", ""),
                    max(total_jumps - i, 0),
                    jump.get("fuel_in_tank", ""),
                    jump.get("tritium_in_market", ""),
                    jump.get("fuel_used", ""),
                    self._fleet_icy_ring_text(jump),
                    self._yes_if(jump.get("must_restock")),
                    jump.get("restock_amount", "") if self._safe_float(jump.get("restock_amount", 0), 0) else "",
                ])
            rows.append([
                "",
                "Total",
                total_distance,
                "",
                total_jumps,
                "",
                "",
                total_fuel_used,
                "",
                "",
                total_restock_amount if total_restock_amount else "",
            ])
            return rows

        if self.exact_plotter and self.exact_route_data:
            rows = []
            total_distance = 0.0
            total_fuel_used = 0.0
            total_jumps = self._route_total_jumps(len(self.exact_route_data))
            for i, jump in enumerate(self.exact_route_data):
                distance = self._safe_float(jump.get("distance"), 0) or 0
                fuel_used = self._safe_float(jump.get("fuel_used"), 0) or 0
                total_distance += distance
                total_fuel_used += fuel_used
                rows.append([
                    self._done_cell_value(jump.get("done", False)),
                    jump.get("name", ""),
                    jump.get("distance", ""),
                    jump.get("distance_to_destination", ""),
                    max(total_jumps - i, 0),
                    jump.get("fuel_in_tank", ""),
                    jump.get("fuel_used", ""),
                    self._yes_if(jump.get("must_refuel")),
                    self._yes_if(jump.get("has_neutron")),
                ])
            rows.append([
                "",
                "Total",
                total_distance,
                "",
                total_jumps,
                "",
                total_fuel_used,
                "",
                "",
            ])
            return rows

        if self._is_neutron_route_active():
            rows = []
            total_distance = 0.0
            total_jumps = 0
            for i in range(len(self.route)):
                row_state = self._route_row_state_at(i)
                distance = self._safe_float(row_state.get("distance_to_arrival"), 0) or 0
                total_distance += distance
                jumps = row_state.get("progress", 0)
                total_jumps = self._add_int_value(total_jumps, jumps)
                rows.append([
                    self._done_cell_value(self._route_done_at(i)),
                    row_state.get("name", ""),
                    row_state.get("distance_to_arrival", ""),
                    row_state.get("remaining_distance", ""),
                    self._yes_if(row_state.get("has_neutron")),
                    jumps,
                ])
            rows.append(["", "Total", total_distance, "", "", total_jumps])
            return rows

        if self.galaxy:
            rows = []
            for i in range(len(self.route)):
                row_state = self._route_row_state_at(i)
                rows.append([
                    self._done_cell_value(self._route_done_at(i)),
                    row_state.get("name", ""),
                    self._yes_if(row_state.get("refuel_required")),
                    row_state.get("distance_to_arrival", ""),
                    row_state.get("remaining_distance", ""),
                ])
            return rows

        return None

    def _spansh_export_payload(self):
        if self.exploration_plotter:
            if self.exploration_mode == "Exomastery":
                header = [
                    "Done",
                    "System Name",
                    "Body Name",
                    "Body Subtype",
                    "Distance To Arrival",
                    "Landmark Subtype",
                    "Value",
                    "Count",
                    "Jumps",
                ]
                rows = []
                for system in self.exploration_route_data:
                    system_name = system.get("name", "")
                    jumps = self._safe_int(system.get("jumps", 1), 1)
                    bodies = system.get("bodies", [])
                    if not bodies:
                        continue
                    for body in bodies:
                        landmarks = body.get("landmarks", [])
                        if not landmarks:
                            continue
                        first_landmark = True
                        for landmark in landmarks:
                            rows.append([
                                self._export_done_value(landmark.get("done", False)),
                                system_name,
                                body.get("name", ""),
                                body.get("subtype", ""),
                                body.get("distance_to_arrival", ""),
                                landmark.get("subtype", ""),
                                landmark.get("value", ""),
                                landmark.get("count", ""),
                                jumps if first_landmark else 0,
                            ])
                            first_landmark = False
                return header, rows

            if self._is_specialized_exploration_mode(self.exploration_mode):
                header = ["Done", "System Name", "Body Name", "Distance To Arrival", "Jumps"]
                rows = []
                for system in self.exploration_route_data:
                    system_name = system.get("name", "")
                    jumps = self._safe_int(system.get("jumps", 1), 1)
                    bodies = system.get("bodies", [])
                    if not bodies:
                        continue
                    first_body = True
                    for body in bodies:
                        rows.append([
                            self._export_done_value(body.get("done", False)),
                            system_name,
                            body.get("name", ""),
                            body.get("distance_to_arrival", ""),
                            jumps if first_body else 0,
                        ])
                        first_body = False
                return header, rows

            header = [
                "Done",
                "System Name",
                "Body Name",
                "Body Subtype",
                "Is Terraformable",
                "Distance To Arrival",
                "Estimated Scan Value",
                "Estimated Mapping Value",
                "Jumps",
            ]
            rows = []
            for system in self.exploration_route_data:
                system_name = system.get("name", "")
                jumps = self._safe_int(system.get("jumps", 1), 1)
                bodies = system.get("bodies", [])
                if not bodies:
                    continue
                first_body = True
                for body in bodies:
                    rows.append([
                        self._export_done_value(body.get("done", False)),
                        system_name,
                        body.get("name", ""),
                        body.get("subtype", ""),
                        self._yes_no(body.get("is_terraformable")),
                        body.get("distance_to_arrival", ""),
                        body.get("estimated_scan_value", ""),
                        body.get("estimated_mapping_value", ""),
                        jumps if first_body else 0,
                    ])
                    first_body = False
            return header, rows

        if self.fleetcarrier and self.fleet_carrier_data:
            header = [
                "Done",
                "System Name",
                "Distance",
                "Distance Remaining",
                "Tritium in tank",
                "Tritium in market",
                "Fuel Used",
                "Icy Ring",
                "Pristine",
                "Restock Tritium",
            ]
            rows = []
            for jump in self.fleet_carrier_data:
                rows.append([
                    self._export_done_value(jump.get("done", False)),
                    jump.get("name", ""),
                    jump.get("distance", ""),
                    jump.get("distance_to_destination", ""),
                    jump.get("fuel_in_tank", ""),
                    jump.get("tritium_in_market", ""),
                    jump.get("fuel_used", ""),
                    self._yes_no(jump.get("has_icy_ring")),
                    self._yes_no(jump.get("is_system_pristine")),
                    self._yes_no(jump.get("must_restock")),
                ])
            return header, rows

        if self.exact_plotter and self.exact_route_data:
            header = [
                "Done",
                "System Name",
                "Distance",
                "Distance Remaining",
                "Fuel Left",
                "Fuel Used",
                "Refuel",
                "Neutron Star",
            ]
            rows = []
            for jump in self.exact_route_data:
                rows.append([
                    self._export_done_value(jump.get("done", False)),
                    jump.get("name", ""),
                    jump.get("distance", ""),
                    jump.get("distance_to_destination", ""),
                    jump.get("fuel_in_tank", ""),
                    jump.get("fuel_used", ""),
                    self._yes_no(jump.get("must_refuel")),
                    self._yes_no(jump.get("has_neutron")),
                ])
            return header, rows

        if self._is_neutron_route_active():
            header = [
                "Done",
                "System Name",
                "Distance To Arrival",
                "Distance Remaining",
                "Neutron Star",
                "Jumps",
            ]
            rows = []
            for index in range(len(self.route)):
                row_state = self._route_row_state_at(index)
                rows.append([
                    self._export_done_value(row_state.get("done", False)),
                    row_state.get("name", ""),
                    row_state.get("distance_to_arrival", ""),
                    row_state.get("remaining_distance", ""),
                    self._yes_no(row_state.get("has_neutron")),
                    row_state.get("progress", 0),
                ])
            return header, rows

        if self.galaxy:
            header = [
                "Done",
                "System Name",
                "Refuel",
                "Distance To Arrival",
                "Distance Remaining",
            ]
            rows = []
            for index in range(len(self.route)):
                row_state = self._route_row_state_at(index)
                rows.append([
                    self._export_done_value(row_state.get("done", False)),
                    row_state.get("name", ""),
                    self._yes_no(row_state.get("refuel_required")),
                    row_state.get("distance_to_arrival", ""),
                    row_state.get("remaining_distance", ""),
                ])
            return header, rows

        return None

    def _toggle_exploration_done_row(self, row_index):
        target = self._exploration_done_item_at(row_index)
        if target is None:
            return False
        target["done"] = not target.get("done", False)
        self._invalidate_route_rows()
        return True

    def _toggle_done_for_meta(self, meta):
        mode = meta.get("mode")
        row_index = meta.get("row_index", -1)
        if row_index < 0:
            return False
        if mode == "exploration":
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
        mode = meta.get("mode")
        row_index = meta.get("row_index", -1)
        if row_index < 0:
            return False
        if mode == "exploration":
            target = self._exploration_done_item_at(row_index)
            return bool(target.get("done", False)) if target else False
        if mode == "exact" and row_index < len(self.exact_route_data):
            return self.exact_route_data[row_index].get("done", False)
        if mode == "fleet" and row_index < len(self.fleet_carrier_data):
            return self.fleet_carrier_data[row_index].get("done", False)
        if mode == "route" and row_index < len(self.route_done):
            return self.route_done[row_index]
        return False

    def _clear_all_done_state(self):
        changed = False
        if self.exploration_plotter and self.exploration_route_data:
            for system in self.exploration_route_data:
                if system.get("done", False):
                    system["done"] = False
                    changed = True
                for body in system.get("bodies", []) or []:
                    if body.get("done", False):
                        body["done"] = False
                        changed = True
                    for landmark in body.get("landmarks", []) or []:
                        if landmark.get("done", False):
                            landmark["done"] = False
                            changed = True
        elif self.exact_plotter and self.exact_route_data:
            for jump in self.exact_route_data:
                if jump.get("done", False):
                    jump["done"] = False
                    changed = True
        elif self.fleetcarrier and self.fleet_carrier_data:
            for jump in self.fleet_carrier_data:
                if jump.get("done", False):
                    jump["done"] = False
                    changed = True
            self.route_done = self._route_done_values()
        else:
            for index, done in enumerate(self.route_done):
                if done:
                    self.route_done[index] = False
                    changed = True
        if changed:
            self._invalidate_route_rows()
            self.update_gui()
            self._update_overlay()
            self.save_all_route()
        return changed

    def _current_system_name(self):
        _coords, current_system = self._get_current_location()
        if current_system:
            return str(current_system).strip()
        try:
            return str(monitor.state.get("SystemName") or "").strip()
        except Exception:
            return ""

    def _viewer_anchor_route_index(self):
        if not self.route:
            return 0
        try:
            anchor_index = int(self.offset)
        except Exception:
            anchor_index = 0
        anchor_index = max(0, min(anchor_index, len(self.route) - 1))
        if self.fleetcarrier:
            previous_index = self._route_visible_prev_index(anchor_index)
            return previous_index if previous_index < anchor_index else anchor_index
        return max(anchor_index - 1, 0)

    def _build_viewer_model(self, columns):
        viewer_model = {
            "rows": [],
            "meta": [],
            "tags": [],
            "current_index": self._viewer_anchor_route_index(),
        }

        def add_model_row(values, tags, meta):
            viewer_model["rows"].append(list(values))
            viewer_model["tags"].append(tuple(tags))
            viewer_model["meta"].append(dict(meta))

        if self.exploration_plotter:
            target_route_index = self._viewer_anchor_route_index()
            viewer_model["current_index"] = -1
            for row_index, row in enumerate(self._exploration_view_rows()):
                row_data = row["values"]
                is_total = row["is_total"]
                tags = self._viewer_row_tags(row_index, is_total=is_total)
                add_model_row(
                    row_data,
                    tags,
                    {
                        "mode": "exploration",
                        "row_index": row_index,
                        "route_index": row["route_index"],
                        "is_total": is_total,
                        "no_done": row["no_done"],
                    },
                )
                if (
                    not is_total
                    and viewer_model["current_index"] == -1
                    and row.get("route_index") == target_route_index
                ):
                    viewer_model["current_index"] = row_index
            return viewer_model

        if self.fleetcarrier and self.fleet_carrier_data:
            total_distance = 0.0
            total_fuel_used = 0.0
            total_restock_amount = 0.0
            total_jumps = self._route_total_jumps(len(self.fleet_carrier_data))

            for i, jump in enumerate(self.fleet_carrier_data):
                distance = self._safe_float(jump.get("distance"), 0) or 0
                remaining = self._safe_float(jump.get("distance_to_destination"), 0) or 0
                fuel_left = self._safe_int(jump.get("fuel_in_tank"), 0)
                tritium_market = self._safe_int(jump.get("tritium_in_market"), 0)
                fuel_used = self._safe_int(jump.get("fuel_used"), 0)
                restock_amount = self._safe_int(jump.get("restock_amount"), 0)
                total_distance += distance
                total_fuel_used += fuel_used
                total_restock_amount += restock_amount

                add_model_row(
                    [
                        self._done_cell_value(jump.get("done", False)),
                        jump.get("name", ""),
                        self._format_decimal_number(distance, decimals=2),
                        self._format_decimal_number(remaining, decimals=2),
                        max(total_jumps - i, 0),
                        self._format_whole_number(fuel_left),
                        self._format_whole_number(tritium_market),
                        self._format_whole_number(fuel_used),
                        self._fleet_icy_ring_text(jump),
                        self._yes_if(jump.get("must_restock")),
                        self._format_whole_number(restock_amount) if restock_amount else "",
                    ],
                    self._viewer_row_tags(i, is_waypoint=bool(jump.get("is_waypoint"))),
                    {"mode": "fleet", "row_index": i, "is_total": False},
                )

            add_model_row(
                [
                    "",
                    "Total",
                    self._format_decimal_number(total_distance, decimals=2),
                    "",
                    total_jumps,
                    "",
                    "",
                    self._format_whole_number(total_fuel_used),
                    "",
                    "",
                    self._format_whole_number(total_restock_amount),
                ],
                ("total",),
                {"mode": "fleet", "row_index": -1, "is_total": True, "no_done": True},
            )
            return viewer_model

        if self.exact_plotter and self.exact_route_data:
            total_distance = 0.0
            total_fuel_used = 0.0
            total_jumps = self._route_total_jumps(len(self.exact_route_data))

            for i, jump in enumerate(self.exact_route_data):
                distance = self._safe_float(jump.get("distance"), 0) or 0
                remaining = self._safe_float(jump.get("distance_to_destination"), 0) or 0
                fuel_left = self._safe_float(jump.get("fuel_in_tank"), 0) or 0
                fuel_used = self._safe_float(jump.get("fuel_used"), 0) or 0
                total_distance += distance
                total_fuel_used += fuel_used

                add_model_row(
                    [
                        self._done_cell_value(jump.get("done", False)),
                        jump.get("name", ""),
                        self._format_decimal_number(distance, decimals=2),
                        self._format_decimal_number(remaining, decimals=2),
                        max(total_jumps - i, 0),
                        self._format_decimal_number(fuel_left, decimals=2),
                        self._format_decimal_number(fuel_used, decimals=2),
                        self._yes_if(jump.get("must_refuel")),
                        self._yes_if(jump.get("has_neutron")),
                    ],
                    self._viewer_row_tags(i, is_refuel=bool(jump.get("must_refuel")), is_destination=i == len(self.exact_route_data) - 1),
                    {"mode": "exact", "row_index": i, "is_total": False},
                )

            add_model_row(
                [
                    "",
                    "Total",
                    self._format_decimal_number(total_distance, decimals=2),
                    "",
                    total_jumps,
                    "",
                    self._format_decimal_number(total_fuel_used, decimals=2),
                    "",
                    "",
                ],
                ("total",),
                {"mode": "exact", "row_index": -1, "is_total": True, "no_done": True},
            )
            return viewer_model

        if self._is_neutron_route_active():
            total_distance = 0.0
            total_jumps = 0
            highlighted_names = self._neutron_highlight_names()
            for i in range(len(self.route)):
                row_state = self._route_row_state_at(i)
                distance = self._safe_float(row_state.get("distance_to_arrival"), 0) or 0
                remaining = self._safe_float(row_state.get("remaining_distance"), 0) or 0
                jumps = row_state.get("progress", 0)
                total_distance += distance
                total_jumps = self._add_int_value(total_jumps, jumps)
                system_name = str(row_state.get("name", "")).strip().lower()
                add_model_row(
                    [
                        self._done_cell_value(self._route_done_at(i)),
                        row_state.get("name", ""),
                        self._format_decimal_number(distance, decimals=2),
                        self._format_decimal_number(remaining, decimals=2),
                        self._yes_if(row_state.get("has_neutron")),
                        jumps,
                    ],
                    self._viewer_row_tags(i, is_destination=i == len(self.route) - 1 or system_name in highlighted_names),
                    {"mode": "route", "row_index": i, "is_total": False},
                )

            add_model_row(
                [
                    "",
                    "Total",
                    self._format_decimal_number(total_distance, decimals=2),
                    "",
                    "",
                    total_jumps,
                ],
                ("total",),
                {"mode": "route", "row_index": -1, "is_total": True, "no_done": True},
            )
            return viewer_model

        for i, row_data in enumerate(self.route):
            values = []
            for j in range(len(columns)):
                if j == 0:
                    values.append(self._done_cell_value(self.route_done[i] if i < len(self.route_done) else False))
                    continue
                row_index = j - 1
                if row_index < len(row_data):
                    value = row_data[row_index]
                    if row_index in (2, 3):
                        value = self._format_decimal_number(value, decimals=2)
                    values.append(value)
                else:
                    values.append("")
            is_total = bool(values and len(values) > 1 and values[1] == "Total")
            refuel_index = 2 if self.galaxy else -1
            is_refuel = bool(self.galaxy and not is_total and len(values) > refuel_index and str(values[refuel_index]).strip().lower() == "yes")
            add_model_row(
                values,
                self._viewer_row_tags(i, is_total=is_total, is_refuel=is_refuel),
                {"mode": "route", "row_index": i, "is_total": is_total},
            )
        return viewer_model

    def show(self, force_refresh=False, restore_geometry=None):
        """Open a window showing the current route as a table."""
        if not self.route and not self.exploration_route_data:
            if self.csv_viewer_win:
                try:
                    self.csv_viewer_win.destroy()
                except Exception:
                    pass
                self._close_csv_viewer()
            return
        columns, viewer_model, signature = self._build_viewer_state()
        measured_widths = list(self._csv_viewer_width_cache.get(signature, []))
        if not measured_widths:
            measured_widths = self._measure_viewer_widths(
                list(columns[1:]),
                viewer_model["rows"],
                self._csv_viewer_text_size,
            )
            self._csv_viewer_width_cache[signature] = list(measured_widths)
        if force_refresh and self._refresh_existing_sheet(columns, viewer_model, signature):
            return
        win = self._open_viewer_window(signature, force_refresh=force_refresh, restore_geometry=restore_geometry)
        if win is None:
            return
        if not restore_geometry:
            try:
                target_width = self._viewer_target_width(measured_widths)
                win.geometry(f"{target_width}x360")
            except Exception:
                pass

        sheet_state = self._initial_sheet_state()

        dark_mode_var = tk.BooleanVar(value=self._csv_viewer_dark_mode)

        def apply_csv_theme():
            self._csv_viewer_dark_mode = bool(dark_mode_var.get())
            colors = self._csv_theme_colors(self._csv_viewer_dark_mode)
            try:
                config.set('spansh_csv_dark_mode', int(self._csv_viewer_dark_mode))
            except Exception:
                pass
            if sheet_state["widget"]:
                try:
                    sheet_state["widget"].set_options(
                        alternate_color=colors["alternate_bg"],
                        table_grid_fg=colors["table_grid_fg"],
                        header_grid_fg=colors["header_grid_fg"],
                        table_bg=colors["table_bg"],
                        header_bg=colors["header_bg"],
                        table_fg=colors["table_fg"],
                        header_fg=colors["header_fg"],
                        index_bg=colors["index_bg"],
                        index_fg=colors["index_fg"],
                        table_selected_cells_bg=colors["selected_bg"],
                        table_selected_rows_bg=colors["selected_bg"],
                        table_selected_cells_fg=colors["selected_fg"],
                        table_selected_rows_fg=colors["selected_fg"],
                        header_selected_cells_bg=colors["selected_bg"],
                        header_selected_cells_fg=colors["selected_fg"],
                        redraw=False,
                    )
                    if sheet_state["done_header_label"] is not None:
                        sheet_state["done_header_label"].configure(
                            bg=colors["header_bg"],
                            fg=colors["header_fg"],
                        )
                    if callable(sheet_state.get("refresh_theme")):
                        sheet_state["refresh_theme"]()
                    else:
                        sheet_state["widget"].refresh()
                except Exception:
                    pass

        def apply_csv_text_size(size):
            self._csv_viewer_text_size = size
            try:
                text_size_var.set(size)
            except Exception:
                pass
            try:
                config.set('spansh_csv_text_size', size)
            except Exception:
                pass
            row_height = max(30, size + 20)
            header_height = max(34, size + 20)
            try:
                apply_csv_theme()
            except Exception:
                pass
            if sheet_state["widget"]:
                try:
                    sheet_state["widget"].set_options(
                        font=("TkDefaultFont", size, "normal"),
                        header_font=("TkDefaultFont", size, "bold"),
                        index_font=("TkDefaultFont", 11, "bold"),
                        popup_menu_font=("TkDefaultFont", size, "normal"),
                        row_height=row_height,
                        header_height=header_height,
                        redraw=True,
                    )
                    if sheet_state["done_header_label"] is not None:
                        sheet_state["done_header_label"].configure(font=("TkDefaultFont", size, "bold"))
                        sheet_state["done_header_label"].place_configure(height=header_height)
                    apply_sheet_column_widths(remeasure=True, adjust_window=True)
                except Exception:
                    pass

        text_size_var = tk.IntVar(value=self._csv_viewer_text_size)
        menubar = tk.Menu(win)
        file_menu = tk.Menu(menubar, tearoff=0)
        view_menu = tk.Menu(menubar, tearoff=0)
        text_size_menu = tk.Menu(view_menu, tearoff=0)
        for size in (9, 10, 11, 12, 14, 16):
            text_size_menu.add_radiobutton(
                label=f"Text Size {size}",
                value=size,
                variable=text_size_var,
                command=lambda s=size: apply_csv_text_size(s),
            )
        view_menu.add_cascade(label="Text Size", menu=text_size_menu)
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Dark mode",
            variable=dark_mode_var,
            command=apply_csv_theme,
        )
        view_menu.add_command(
            label="Clear Done",
            command=lambda: (
                self._clear_all_done_state()
                and (
                    self._refresh_viewer_in_place(preserve_view=True)
                    or self.show(force_refresh=True, restore_geometry=win.geometry())
                )
            ),
        )
        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_cascade(label="View", menu=view_menu)
        win.config(menu=menubar)
        text_size_var.set(self._csv_viewer_text_size)
        apply_csv_text_size(self._csv_viewer_text_size)

        columns_state = {"value": columns}

        def _sheet_current_cell():
            sheet = sheet_state["widget"]
            if not sheet:
                return None, None
            try:
                selected = sheet.get_currently_selected()
            except Exception:
                return None, None
            if not selected:
                return None, None
            row = getattr(selected, "row", None)
            column = getattr(selected, "column", None)
            if row is None or column is None:
                if isinstance(selected, (tuple, list)) and len(selected) >= 2:
                    row, column = selected[0], selected[1]
            try:
                return int(row), int(column)
            except Exception:
                return None, None

        def _sheet_display_value(value):
            if isinstance(value, bool):
                return self._done_cell_value(value)
            return value

        def _non_empty_display_values(values):
            normalized = []
            for value in values:
                text = str(_sheet_display_value(value)).strip()
                if text:
                    normalized.append(text)
            return normalized

        win.grid_rowconfigure(0, weight=1)
        win.grid_columnconfigure(0, weight=1)

        def resize_csv_viewer_window(target_width, minimum_height=360):
            try:
                current_x = win.winfo_x()
                current_y = win.winfo_y()
                current_height = max(win.winfo_height(), minimum_height)
                if current_x > 1 or current_y > 1:
                    win.geometry(f"{int(target_width)}x{int(current_height)}+{int(current_x)}+{int(current_y)}")
                else:
                    win.geometry(f"{int(target_width)}x{int(current_height)}")
            except Exception:
                pass

        def viewer_export_rows():
            return self._viewer_export_rows()

        def spansh_export_payload():
            return self._spansh_export_payload()

        def export_viewer_csv():
            filename = filedialog.asksaveasfilename(
                filetypes=[("CSV file", "*.csv"), ("All files", "*.*")],
                defaultextension=".csv",
                initialdir=self._dialog_initial_directory("export"),
                initialfile=self._default_export_filename(".csv"),
                parent=win,
            )
            if not filename:
                return
            try:
                self._remember_dialog_directory("export", filename)
                with open(filename, "w", newline="") as csvfile:
                    writer = csv.writer(csvfile)
                    export_payload = spansh_export_payload()
                    if export_payload is not None:
                        export_header, export_rows = export_payload
                        writer.writerow(export_header)
                        for row in export_rows:
                            writer.writerow(row)
                    else:
                        writer.writerow(columns_state["value"])
                        export_rows = viewer_export_rows()
                        if export_rows is not None:
                            for row in export_rows:
                                writer.writerow(row)
                        elif sheet_state["widget"]:
                            for row in sheet_state["rows"]:
                                writer.writerow([_sheet_display_value(value) for value in row])
            except Exception as e:
                self.show_error(f"CSV export failed: {e}")

        file_menu.add_command(label="Export CSV...", command=export_viewer_csv)

        def export_viewer_json():
            filename = filedialog.asksaveasfilename(
                filetypes=[("JSON file", "*.json"), ("All files", "*.*")],
                defaultextension=".json",
                initialdir=self._dialog_initial_directory("export"),
                initialfile=self._default_export_filename(".json"),
                parent=win,
            )
            if not filename:
                return
            try:
                self._remember_dialog_directory("export", filename)
                payload = self._spansh_json_export_payload()
                if payload is None:
                    raise ValueError("JSON export is not available for this route.")
                with open(filename, "w", encoding="utf-8") as jsonfile:
                    json.dump(payload, jsonfile, indent=2)
            except Exception as e:
                self.show_error(f"JSON export failed: {e}")

        file_menu.add_command(label="Export JSON...", command=export_viewer_json)
        if self._spansh_json_export_payload() is None:
            try:
                file_menu.entryconfigure("Export JSON...", state=tk.DISABLED)
            except Exception:
                pass

        def copy_selected_row():
            row_index, _column_index = _sheet_current_cell()
            if row_index is None or row_index >= len(sheet_state["rows"]):
                return
            self._copy_to_clipboard("\t".join(_non_empty_display_values(sheet_state["rows"][row_index])))

        def copy_selected_column():
            row_index, column_index = _sheet_current_cell()
            if row_index is None or column_index is None:
                return
            try:
                values = sheet_state["widget"].get_column_data(
                    int(column_index),
                    get_displayed=True,
                    get_header=True,
                )
            except Exception:
                return
            self._copy_to_clipboard("\n".join(_non_empty_display_values(values)))

        def copy_table():
            lines = ["\t".join(columns_state["value"])]
            for row in sheet_state["rows"]:
                row_values = _non_empty_display_values(row)
                if row_values:
                    lines.append("\t".join(row_values))
            self._copy_to_clipboard("\n".join(lines))

        def current_selected_meta():
            row_index, _column_index = _sheet_current_cell()
            if row_index is None or row_index >= len(sheet_state["meta"]):
                return None
            return sheet_state["meta"][row_index]

        def set_current_waypoint_from_meta(meta):
            self._set_current_waypoint_from_meta(meta)

        def set_current_waypoint():
            set_current_waypoint_from_meta(current_selected_meta())

        def toggle_done_for_meta(meta):
            return self._toggle_done_for_meta(meta)

        sheet_state["rows"] = viewer_model["rows"]
        sheet_state["meta"] = viewer_model["meta"]
        sheet_state["tags"] = viewer_model["tags"]
        sheet_state["measured_widths"] = list(measured_widths)

        theme = self._csv_theme_colors(self._csv_viewer_dark_mode)
        sheet = TkSheet(
            win,
            headers=list(columns_state["value"][1:]),
            data=[row[1:] for row in sheet_state["rows"]],
            row_index=[row[0] for row in sheet_state["rows"]],
            show_row_index=True,
            show_header=True,
            show_top_left=True,
            show_default_index_for_empty=False,
            show_horizontal_grid=True,
            show_vertical_grid=True,
            horizontal_grid_to_end_of_window=True,
            vertical_grid_to_end_of_window=True,
            rounded_boxes=False,
            alternate_color=theme["alternate_bg"],
            empty_horizontal=0,
            empty_vertical=0,
            table_grid_fg=theme["table_grid_fg"],
            header_grid_fg=theme["header_grid_fg"],
            table_bg=theme["table_bg"],
            header_bg=theme["header_bg"],
            table_fg=theme["table_fg"],
            header_fg=theme["header_fg"],
            index_bg=theme["index_bg"],
            index_fg=theme["index_fg"],
            table_selected_cells_bg=theme["selected_bg"],
            table_selected_rows_bg=theme["selected_bg"],
            table_selected_cells_fg=theme["selected_fg"],
            table_selected_rows_fg=theme["selected_fg"],
            header_selected_cells_bg=theme["selected_bg"],
            header_selected_cells_fg=theme["selected_fg"],
            show_selected_cells_border=True,
            font=("TkDefaultFont", self._csv_viewer_text_size, "normal"),
            header_font=("TkDefaultFont", self._csv_viewer_text_size, "bold"),
            index_font=("TkDefaultFont", 11, "bold"),
            popup_menu_font=("TkDefaultFont", self._csv_viewer_text_size, "normal"),
            row_height=max(30, self._csv_viewer_text_size + 20),
            header_height=max(34, self._csv_viewer_text_size + 20),
            width=max(700, self._viewer_target_width(measured_widths)),
            height=max(360, win.winfo_height()),
        )
        sheet_state["widget"] = sheet
        sheet.grid(row=0, column=0, sticky=tk.NSEW)
        try:
            sheet.enable_bindings(
                (
                    "single_select",
                    "arrowkeys",
                    "right_click_popup_menu",
                    "rc_select",
                    "column_width_resize",
                    "copy",
                )
            )
        except Exception:
            self._log_unexpected("Failed to enable route viewer sheet bindings")
        try:
            sheet.headers(list(columns_state["value"][1:]), reset_col_positions=True, redraw=False)
            sheet.row_index([row[0] for row in sheet_state["rows"]], reset_row_positions=True, redraw=False)
            sheet.display_columns("all", all_columns_displayed=True, reset_col_positions=True, redraw=False)
            sheet.set_options(column_drag_and_drop_perform=False, row_index_width=72, redraw=False)
            sheet.set_index_width(72, redraw=False)
            sheet.index_align("center", redraw=False)
        except Exception:
            self._log_unexpected("Failed to configure route viewer sheet")

        def done_value_for_meta(meta):
            return self._done_value_for_meta(meta)

        def base_row_style(row_index):
            tags = sheet_state["tags"][row_index] if row_index < len(sheet_state["tags"]) else ()
            if "total" in tags:
                return "#11b98f", "white", tags
            if "destination" in tags:
                return "#3da0e3", "white", tags
            if "waypoint" in tags:
                return "#eb5a46", "white", tags
            if "refuel" in tags:
                return "#ffd7a8", "black", tags
            bg, fg = self._viewer_zebra_row_style(row_index)
            return bg, fg, tags

        def update_sheet_done_cell(row_index, checked, redraw=False):
            symbol = "■" if checked else "□"
            if row_index >= len(sheet_state["rows"]):
                return
            sheet_state["rows"][row_index][0] = symbol
            bg, fg, _tags = base_row_style(row_index)
            try:
                sheet.highlight_rows(
                    row_index,
                    bg=bg,
                    fg=fg,
                    redraw=False,
                )
                sheet.set_index_data(symbol, r=row_index, redraw=False)
                sheet.highlight_cells(
                    row=row_index,
                    column=0,
                    canvas="index",
                    bg=bg,
                    fg="#1ea55b" if checked else self._csv_theme_colors(self._csv_viewer_dark_mode)["index_empty_fg"],
                    redraw=False,
                    overwrite=True,
                )
                if redraw:
                    sheet.refresh()
            except Exception:
                pass

        def apply_special_row_highlights():
            total_rows = []
            destination_rows = []
            waypoint_rows = []
            refuel_rows = []
            for row_index, tags in enumerate(sheet_state["tags"]):
                if "total" in tags:
                    total_rows.append(row_index)
                elif "destination" in tags:
                    destination_rows.append(row_index)
                elif "waypoint" in tags:
                    waypoint_rows.append(row_index)
                elif "refuel" in tags:
                    meta = sheet_state["meta"][row_index] if row_index < len(sheet_state["meta"]) else {}
                    if meta and not meta.get("is_total") and done_value_for_meta(meta):
                        continue
                    refuel_rows.append(row_index)
            try:
                sheet.dehighlight_all(cells=False, rows=True, columns=False, header=False, index=True, redraw=False)
            except Exception:
                pass
            if total_rows:
                sheet.highlight_rows(total_rows, bg="#11b98f", fg="white", redraw=False)
            if destination_rows:
                sheet.highlight_rows(destination_rows, bg="#3da0e3", fg="white", redraw=False)
            if waypoint_rows:
                sheet.highlight_rows(waypoint_rows, bg="#eb5a46", fg="white", redraw=False)
            if refuel_rows:
                sheet.highlight_rows(refuel_rows, bg="#ffd7a8", fg="black", redraw=False)

        def apply_checked_done_cells():
            for row_index, meta in enumerate(sheet_state["meta"]):
                if not meta or meta.get("is_total") or meta.get("no_done"):
                    continue
                if done_value_for_meta(meta):
                    update_sheet_done_cell(row_index, True, redraw=False)

        def adjust_sheet_window_width(measured_widths, done_width):
            if not measured_widths:
                return
            target_width = self._viewer_target_width(measured_widths)
            try:
                if win.winfo_width() < target_width:
                    resize_csv_viewer_window(target_width)
            except Exception:
                pass

        def remeasure_sheet_widths():
            headers = list(columns_state["value"][1:])
            measured = self._measure_viewer_widths(headers, sheet_state["rows"], self._csv_viewer_text_size)
            self._csv_viewer_width_cache[signature] = list(measured)
            return measured

        def apply_sheet_column_widths(remeasure=False, adjust_window=False):
            done_width = 72
            if remeasure:
                sheet_state["measured_widths"] = remeasure_sheet_widths()
            measured_widths = list(sheet_state.get("measured_widths", []))
            if not measured_widths:
                return
            if adjust_window:
                adjust_sheet_window_width(measured_widths, done_width)
            available_width = max(sheet.winfo_width() - done_width - 20, 0)
            final_widths = list(measured_widths)
            total_measured = sum(measured_widths)
            if total_measured > 0 and available_width > total_measured:
                extra = available_width - total_measured
                add_each, remainder = divmod(extra, len(final_widths))
                for i in range(len(final_widths)):
                    final_widths[i] += add_each + (1 if i < remainder else 0)
            for col_index, width in enumerate(final_widths):
                try:
                    sheet.column_width(col_index, width=width, redraw=False)
                except Exception:
                    pass
            try:
                sheet.set_index_width(done_width, redraw=False)
            except Exception:
                pass
            if sheet_state["done_header_label"] is not None:
                try:
                    sheet_state["done_header_label"].place(
                        in_=sheet,
                        x=0,
                        y=0,
                        width=done_width,
                        height=max(34, self._csv_viewer_text_size + 20),
                    )
                except Exception:
                    pass
            try:
                sheet.refresh()
            except Exception:
                pass

        def enforce_sheet_done_width(_event=None):
            done_width = 72
            try:
                sheet.set_index_width(done_width, redraw=False)
                sheet.refresh()
            except Exception:
                pass

        def handle_sheet_click(event=None):
            if event is None or sheet.identify_region(event) != "index":
                return
            row_index = sheet.identify_row(event)
            if row_index is None:
                return
            if row_index >= len(sheet_state["meta"]):
                return
            meta = sheet_state["meta"][row_index]
            if not meta or meta.get("is_total") or meta.get("no_done"):
                return
            if toggle_done_for_meta(meta):
                checked = done_value_for_meta(meta)
                update_sheet_done_cell(row_index, checked, redraw=True)
                self.save_all_route()

        def schedule_sheet_resize(_event=None):
            if not sheet_state["ready_for_resize"]:
                return
            if sheet_state["resize_after_id"] is not None:
                try:
                    win.after_cancel(sheet_state["resize_after_id"])
                except Exception:
                    pass
            sheet_state["resize_after_id"] = win.after(60, run_sheet_resize)

        def run_sheet_resize():
            sheet_state["resize_after_id"] = None
            apply_sheet_column_widths(remeasure=False, adjust_window=False)

        def refresh_sheet_theme():
            apply_special_row_highlights()
            apply_checked_done_cells()
            try:
                sheet.refresh()
            except Exception:
                pass

        sheet_state["refresh_theme"] = refresh_sheet_theme

        readonly_columns = list(range(len(columns_state["value"]) - 1))
        if readonly_columns:
            try:
                sheet.readonly_columns(readonly_columns, readonly=True, redraw=False)
            except Exception:
                pass

        apply_special_row_highlights()
        apply_checked_done_cells()

        def handle_sheet_release(event=None):
            handle_sheet_click(event)
            enforce_sheet_done_width(event)

        def finalize_sheet_paint():
            try:
                win.update_idletasks()
                sheet_state["ready_for_resize"] = True
                apply_sheet_column_widths(remeasure=False, adjust_window=False)
                sheet.refresh()
                if sheet_state["resize_after_id"] is not None:
                    try:
                        win.after_cancel(sheet_state["resize_after_id"])
                    except Exception:
                        pass
                sheet_state["resize_after_id"] = win.after(0, run_sheet_resize)
            except Exception:
                self._log_unexpected("Failed to finalize route viewer paint")

        try:
            sheet.popup_menu_add_command("📋 Copy row", copy_selected_row, table_menu=True, index_menu=False, header_menu=False, empty_space_menu=False)
            sheet.popup_menu_add_command("📋 Copy column", copy_selected_column, table_menu=True, index_menu=False, header_menu=False, empty_space_menu=False)
            sheet.popup_menu_add_command("📋 Copy table", copy_table, table_menu=True, index_menu=False, header_menu=False, empty_space_menu=False)
            sheet.popup_menu_add_command("Set as current waypoint", set_current_waypoint, table_menu=True, index_menu=False, header_menu=False, empty_space_menu=False)
            try:
                sheet.MT.bind("<ButtonRelease-1>", handle_sheet_release, add="+")
            except Exception:
                pass
            try:
                sheet.RI.bind("<ButtonRelease-1>", handle_sheet_release, add="+")
            except Exception:
                pass
            sheet_state["done_header_label"] = tk.Label(
                sheet,
                text="Done",
                font=("TkDefaultFont", self._csv_viewer_text_size, "bold"),
                bg=theme["header_bg"],
                fg=theme["header_fg"],
                relief="flat",
                bd=0,
                anchor="center",
            )
            apply_sheet_column_widths(remeasure=False, adjust_window=False)
            if 0 <= viewer_model["current_index"] < len(sheet_state["rows"]):
                try:
                    sheet.see(
                        viewer_model["current_index"],
                        0,
                        bottom_right_corner=False,
                        check_cell_visibility=False,
                        redraw=False,
                    )
                except Exception:
                    pass
            sheet.refresh()
            self._csv_viewer_runtime = {
                "win": win,
                "sheet": sheet,
                "sheet_state": sheet_state,
                "columns_state": columns_state,
                "apply_sheet_column_widths": apply_sheet_column_widths,
                "refresh_theme": refresh_sheet_theme,
            }
            win.bind("<Configure>", schedule_sheet_resize, add="+")
            try:
                win.after_idle(finalize_sheet_paint)
            except AttributeError:
                win.after(0, finalize_sheet_paint)
        except Exception:
            self._handle_viewer_setup_failure("Failed to initialize route viewer", win)
            return
