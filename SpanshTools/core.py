import json
import math
import os
import re
import shlex
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
import tkinter.messagebox as confirmDialog
import threading

import requests
from config import config
from monitor import monitor

from .constants import (
    ROUTE_PLANNERS,
    SEARCH_OPTIONS,
    logger,
)
from .overlay import OverlayMixin
from .plotters import PlottersMixin
from .route_io import RouteIOMixin
from .route_viewer import CsvViewerWindow
from .widgets import (
    Tooltip,
    bind_live_spinbox_clamp,
    clamp_numeric_input,
    clamp_spinbox_input,
    live_clamp_spinbox_input,
    make_spinbox_validator,
    validate_decimal_input,
    validate_integer_input,
    validate_spinbox_input,
)

from .updater import SpanshUpdater

class SpanshTools(OverlayMixin, PlottersMixin, RouteIOMixin):
    # -- Route type properties (backed by self.route_type) --
    # These keep the public boolean API while delegating to a single string.

    def _is_route_type(self, route_type):
        return self.route_type == route_type

    def _set_route_type_flag(self, route_type, value):
        if value:
            self.route_type = route_type
        elif self.route_type == route_type:
            self.route_type = None

    @property
    def exact_plotter(self):
        return self._is_route_type("exact")

    @exact_plotter.setter
    def exact_plotter(self, value):
        self._set_route_type_flag("exact", value)

    @property
    def galaxy(self):
        return self._is_route_type("galaxy")

    @galaxy.setter
    def galaxy(self, value):
        self._set_route_type_flag("galaxy", value)

    @property
    def fleetcarrier(self):
        return self._is_route_type("fleet_carrier")

    @fleetcarrier.setter
    def fleetcarrier(self, value):
        self._set_route_type_flag("fleet_carrier", value)

    @property
    def exploration_plotter(self):
        return self._is_route_type("exploration")

    @exploration_plotter.setter
    def exploration_plotter(self, value):
        self._set_route_type_flag("exploration", value)

    def __init__(self, plugin_dir):
        version_file = os.path.join(plugin_dir, "version.json")
        with open(version_file, 'r') as version_fd:
            self.plugin_version = json.load(version_fd).get("version", "0.0.0")

        self.update_available = False
        self.spansh_updater = None
        staged_update = SpanshUpdater.load_staged_metadata(plugin_dir)
        if staged_update:
            self.spansh_updater = SpanshUpdater(
                staged_update["version"],
                staged_update.get("download_url", ""),
                "",
                plugin_dir,
            )
            self.update_available = True
        self.route_type = None  # "exact", "galaxy", "fleet_carrier", "exploration", "neutron", "simple", or None
        self.exploration_mode = None
        self.exploration_route_data = []
        self.next_stop = "No route planned"
        self.route = []
        self.route_rows = []
        self._route_rows_state = None
        self._route_rows_dirty = True
        self._route_rows_signature_cache = None
        self.route_done = []
        self.next_wp_label = "Next waypoint: "
        self.jumpcountlbl_txt = "Estimated jumps left: "
        self.bodieslbl_txt = "Bodies to scan at: "
        self.fleetstocklbl_txt = "Time to stock Tritium"
        self.refuellbl_txt = "Time to scoop some fuel"
        self.bodies = ""
        self.parent = None
        self.plugin_dir = plugin_dir
        self.save_route_path = os.path.join(plugin_dir, 'route.csv')
        self.offset_file_path = os.path.join(plugin_dir, 'offset')
        self.route_state_filename = 'route_state.json'
        self.exact_settings_path = os.path.join(plugin_dir, 'exact_settings.json')
        self.plotter_settings_path = os.path.join(plugin_dir, 'plotter_settings.json')
        self.offset = 0
        self.jumps_left = 0
        self.error_txt = tk.StringVar()
        self.plot_error = "Error while trying to plot a route, please try again."
        self.system_header = "System Name"
        self.bodyname_header = "Body Name"
        self.bodysubtype_header = "Body Subtype"
        self.jumps_header = "Jumps"
        self.restocktritium_header = "Restock Tritium"
        self.refuel_header = "Refuel"
        self.pleaserefuel = False
        # distance tracking
        self.dist_next = ""
        self.dist_prev = ""
        self.dist_remaining = ""
        # Supercharge mode (Spansh neutron routing)
        self.supercharge_multiplier = tk.IntVar(value=4)

        # Plotter state
        self.current_plotter_name = None
        self.current_coords = None          # [x, y, z] from FSDJump/Location StarPos
        self.current_system = None          # system name from last FSDJump/Location
        self.current_fuel_main = None       # live main tank fuel from Status.json/dashboard_entry
        self.current_fuel_reservoir = None  # live reservoir fuel from Status.json/dashboard_entry
        self.ship_fsd_data = None           # dict with FSD params for exact plotter
        self.exact_route_data = []          # full API response per waypoint (fuel info)
        self.fleet_carrier_data = []        # full API response per carrier waypoint
        self._exact_settings = None         # saved exact plotter window settings
        self._plotter_settings = {}
        self._exact_plot_cancelled = False  # cancel flag for exact plotter worker
        self._plot_cancelled = False        # cancel flag for neutron plotter worker
        self._plotting = False              # True while any plotter is computing
        self._plot_token = 0
        self._plot_state_lock = threading.RLock()
        self._current_location_lock = threading.RLock()
        self._waypoint_reached = False
        self._waypoint_reached_restock = False
        self._host_window_resize_ready = False
        self._host_resize_job = None
        self._host_resize_retry_job = None
        self._host_resize_retry_count = 0
        self._host_resize_shrink = False
        self._host_resize_preserve_position = False
        self._host_resize_anchor_x = None
        self._host_resize_anchor_y = None
        self._host_base_req_width = None
        self._host_base_extra_width = None
        self._host_base_extra_height = None
        self._clipboard_error_reported = False
        self._staging_update = False
        self.exact_win = None               # exact plotter Toplevel window
        self._last_source_system = None     # last known system for pre-filling plotter
        self.is_supercharged = False        # True after JetConeBoost, reset on FSDJump
        self._supercharge_state_known = False
        self._overlay_route_complete_announced = False
        self._plotter_window_kind = None
        self.csv_viewer_win = None
        self._csv_viewer_signature = None
        self._csv_viewer_runtime = None
        self._csv_viewer_width_cache = {}
        self._pending_journal_event = None
        self._pending_dashboard_event = None
        self._static_layout_width_cache = {}
        self._route_button_width_cache_key = None
        self._route_button_width_chars = 24
        try:
            self._csv_viewer_text_size = max(9, min(16, config.get_int('spansh_csv_text_size', default=12)))
        except Exception:
            self._csv_viewer_text_size = 12
        try:
            self._csv_viewer_dark_mode = bool(config.get_int('spansh_csv_dark_mode', default=0))
        except Exception:
            self._csv_viewer_dark_mode = False

        # Overlay support
        self.overlay = None
        try:
            from EDMCOverlay import edmcoverlay
            self.overlay = edmcoverlay.Overlay()
        except ImportError:
            try:
                from edmcoverlay import edmcoverlay
                self.overlay = edmcoverlay.Overlay()
            except ImportError:
                self.overlay = None

    #   -- GUI part --
    def init_gui(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent, borderwidth=2)
        self.frame.grid(sticky=tk.NSEW, columnspan=2)

        # Title row — label centered, update button anchored right
        self.title_frame = tk.Frame(self.frame)
        self.title_lbl = tk.Label(self.title_frame, text=f"Spansh Tools v{self.plugin_version.strip()}", font=("", 10, "bold"))
        self.title_lbl.pack(side=tk.LEFT, expand=True)
        self.update_btn = tk.Button(self.title_frame, text="\u26A0", font=("", 9), fg="orange",
                                     relief=tk.FLAT, cursor="hand2", command=self._show_update_popup)
        # Hidden by default — shown when update is available
        self._update_btn_visible = False
        if self.update_available:
            self._show_update_button()

        # Route info
        self.waypoint_prev_btn = tk.Button(self.frame, text="^", command=self.goto_prev_waypoint, width=3)
        self.waypoint_btn = tk.Button(self.frame, text=self.next_wp_label + '\n' + self.next_stop, command=self.copy_waypoint, width=24)
        self.waypoint_next_btn = tk.Button(self.frame, text="v", command=self.goto_next_waypoint, width=3)
        self.jumpcounttxt_lbl = tk.Label(self.frame, text=self.jumpcountlbl_txt + str(self.jumps_left))
        self.dist_prev_lbl = tk.Label(self.frame, text="")
        self.dist_next_lbl = tk.Label(self.frame, text="")
        self.dist_remaining_lbl = tk.Label(self.frame, text="")
        self.bodies_lbl = tk.Label(self.frame, justify=tk.LEFT, text=self.bodieslbl_txt + self.bodies)
        self.fleetrestock_lbl = tk.Label(self.frame, justify=tk.CENTER, text=self.fleetstocklbl_txt)

        # Collapse/expand toggle for the controls section
        self._controls_collapsed = bool(config.get_int('spansh_controls_collapsed', default=0))
        self._collapse_btn = tk.Button(
            self.frame,
            text="⏵" if self._controls_collapsed else "⏷",
            font=("", 8),
            width=2,
            padx=1,
            pady=0,
            bd=1,
            relief=tk.GROOVE,
            cursor="hand2",
            command=self._toggle_collapse,
        )
        self._collapse_tooltip = Tooltip(self._collapse_btn, "Expand" if self._controls_collapsed else "Collapse")
        self.refuel_lbl = tk.Label(self.frame, justify=tk.LEFT, text=self.refuellbl_txt)
        self.error_lbl = tk.Label(self.frame, textvariable=self.error_txt)

        # Plotter window reference (created on demand)
        self.plotter_win = None

        # Button frame — isolates button columns from waypoint layout
        self.btn_frame = tk.Frame(self.frame)
        self.btn_frame.columnconfigure(0, weight=1, uniform="top_controls")
        self.btn_frame.columnconfigure(1, weight=1, uniform="top_controls")
        self._main_dropdown_width = max(1, max(len(option) for option in ROUTE_PLANNERS) - 1)
        self._main_button_width = max(
            len(text) for text in (
                "Plot route",
                "Search",
                "Import file",
                "Clear route",
                "Show route",
            )
        ) + 2
        self._compact_button_width = max(
            len(text) for text in (
                "Plot route",
                "Search",
                "Import file",
            )
        ) + 1

        # Route planner dropdown
        saved_planner_name = ""
        try:
            saved_planner_name = config.get_str('spansh_route_planner_name')
        except Exception:
            saved_planner_name = ""
        if saved_planner_name not in ROUTE_PLANNERS:
            saved_planner = config.get_int('spansh_route_planner', default=0)
            if 0 <= saved_planner < len(ROUTE_PLANNERS):
                saved_planner_name = ROUTE_PLANNERS[saved_planner]
            else:
                saved_planner_name = ROUTE_PLANNERS[0]
        self.planner_var = tk.StringVar(value=saved_planner_name)
        self.planner_dropdown = ttk.Combobox(self.btn_frame, textvariable=self.planner_var,
                                              values=ROUTE_PLANNERS, state="readonly", width=self._main_dropdown_width)
        self.planner_dropdown.bind("<<ComboboxSelected>>", self._on_planner_selected)
        self.plot_btn = tk.Button(self.btn_frame, text="Plot route", width=self._compact_button_width, command=self.show_plotter_window)
        self.search_var = tk.StringVar(value=SEARCH_OPTIONS[0])
        self.search_dropdown = ttk.Combobox(
            self.btn_frame,
            textvariable=self.search_var,
            values=SEARCH_OPTIONS,
            state="readonly",
            width=max(1, max(len(option) for option in SEARCH_OPTIONS) - 1),
        )

        self.csv_route_btn = tk.Button(self.btn_frame, text="Import file", width=self._compact_button_width, command=self.plot_file)
        # Overlay controls — grid layout: 2 columns, 2 rows
        self.overlay_cb_frame = tk.Frame(self.frame)

        # Row 0: checkboxes
        self.overlay_var = tk.BooleanVar(value=False)
        self.overlay_cb = tk.Checkbutton(self.overlay_cb_frame, text="Fuel Overlay", variable=self.overlay_var, command=self.toggle_overlay)
        self.overlay_cb.grid(row=0, column=0, sticky=tk.W)
        self.neutron_overlay_var = tk.BooleanVar(value=False)
        self.neutron_overlay_cb = tk.Checkbutton(self.overlay_cb_frame, text="Supercharge Overlay", variable=self.neutron_overlay_var, command=self.toggle_neutron_overlay)
        self.neutron_overlay_cb.grid(row=0, column=1, sticky=tk.W, padx=(15, 0))

        # Row 1: fuel position controls
        self.overlay_pos_frame = tk.Frame(self.overlay_cb_frame)
        self.overlay_pos_frame.grid(row=1, column=0, sticky=tk.W)
        self.overlay_x_var = tk.IntVar(value=590)
        tk.Label(self.overlay_pos_frame, text="X:").pack(side=tk.LEFT)
        self.overlay_x_spin = tk.Spinbox(self.overlay_pos_frame, from_=0, to=1280, width=5, textvariable=self.overlay_x_var,
                                         validate="key")
        self.overlay_x_spin.configure(validatecommand=self._spinbox_validator(self.overlay_x_spin))
        self.overlay_x_spin.pack(side=tk.LEFT, padx=(0, 5))
        self.overlay_y_var = tk.IntVar(value=675)
        tk.Label(self.overlay_pos_frame, text="Y:").pack(side=tk.LEFT)
        self.overlay_y_spin = tk.Spinbox(self.overlay_pos_frame, from_=0, to=960, width=5, textvariable=self.overlay_y_var,
                                         validate="key")
        self.overlay_y_spin.configure(validatecommand=self._spinbox_validator(self.overlay_y_spin))
        self.overlay_y_spin.pack(side=tk.LEFT)
        self.overlay_pos_frame.grid_remove()

        # Row 1: supercharge position controls
        self.neutron_pos_frame = tk.Frame(self.overlay_cb_frame)
        self.neutron_pos_frame.grid(row=1, column=1, sticky=tk.W, padx=(15, 0))
        self.neutron_x_var = tk.IntVar(value=600)
        tk.Label(self.neutron_pos_frame, text="X:").pack(side=tk.LEFT)
        self.neutron_x_spin = tk.Spinbox(self.neutron_pos_frame, from_=0, to=1280, width=5, textvariable=self.neutron_x_var,
                                         validate="key")
        self.neutron_x_spin.configure(validatecommand=self._spinbox_validator(self.neutron_x_spin))
        self.neutron_x_spin.pack(side=tk.LEFT, padx=(0, 5))
        self.neutron_y_var = tk.IntVar(value=675)
        tk.Label(self.neutron_pos_frame, text="Y:").pack(side=tk.LEFT)
        self.neutron_y_spin = tk.Spinbox(self.neutron_pos_frame, from_=0, to=960, width=5, textvariable=self.neutron_y_var,
                                         validate="key")
        self.neutron_y_spin.configure(validatecommand=self._spinbox_validator(self.neutron_y_spin))
        self.neutron_y_spin.pack(side=tk.LEFT)
        self.neutron_pos_frame.grid_remove()

        # Save overlay settings when X/Y values change (guard to skip during init load)
        self._overlay_loading = False
        self.overlay_x_var.trace_add('write', lambda *_: self._save_overlay_settings())
        self.overlay_y_var.trace_add('write', lambda *_: self._save_overlay_settings())
        self.neutron_x_var.trace_add('write', lambda *_: self._save_overlay_settings())
        self.neutron_y_var.trace_add('write', lambda *_: self._save_overlay_settings())

        self.search_btn = tk.Button(self.btn_frame, text="Search", width=self._compact_button_width, command=self.run_search_action)
        self.clear_route_btn = tk.Button(self.btn_frame, text="Clear route", command=self.clear_route)
        self.show_csv_btn = tk.Button(self.btn_frame, text="Show route", command=self.show_csv_viewer)

        # Configure column weights for centered layout
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)

        row = 0
        self.title_frame.grid(row=row, column=0, columnspan=3, pady=(5, 2), sticky=tk.EW)
        row += 1
        self.waypoint_prev_btn.grid(row=row, column=0, columnspan=2, padx=5, pady=10)
        self.dist_remaining_lbl.grid(row=row, column=2, padx=5, pady=10, sticky=tk.W)
        row += 1
        self.waypoint_btn.grid(row=row, column=0, columnspan=2, padx=5, pady=10)
        self.dist_prev_lbl.grid(row=row, column=2, padx=5, pady=10, sticky=tk.W)
        row += 1
        self.waypoint_next_btn.grid(row=row, column=0, columnspan=2, padx=5, pady=10)
        self.dist_next_lbl.grid(row=row, column=2, padx=5, pady=10, sticky=tk.W)
        row += 1
        self._collapse_btn.grid(row=row, column=0, sticky=tk.W, padx=5, pady=(2, 0))
        row += 1
        self.bodies_lbl.grid(row=row, columnspan=3, sticky=tk.EW)
        row += 1
        self.fleetrestock_lbl.grid(row=row, columnspan=3, sticky=tk.EW)
        row += 1
        self.refuel_lbl.grid(row=row, columnspan=3, sticky=tk.EW)
        row += 1
        # Button frame
        self.btn_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, padx=5)
        row += 1
        # Route view: Overlay controls (fuel + supercharge columns)
        self.overlay_cb_frame.grid(row=row, column=0, columnspan=3, pady=(5, 5), sticky=tk.EW, padx=5)
        self.overlay_cb_frame.columnconfigure(0, weight=1)
        self.overlay_cb_frame.columnconfigure(1, weight=1)
        self.overlay_cb_frame.grid_remove()
        row += 1
        self.jumpcounttxt_lbl.grid(row=row, column=0, columnspan=3, pady=5)
        row += 1
        self.error_lbl.grid(row=row, columnspan=3)
        self.error_lbl.grid_remove()
        row += 1

        # Restore settings
        self._load_overlay_settings()
        self._load_exact_settings()
        self._load_plotter_settings()

        self.update_gui()
        self._capture_host_window_base_size()
        self._replay_buffered_startup_events()

        return self.frame

    def set_source_ac(self, text):
        """Store current system for pre-filling plotter windows."""
        self._last_source_system = text

    def _is_neutron_route_active(self):
        return self.route_type == "neutron"

    def _buffer_startup_journal_event(self, system, entry, state):
        self._pending_journal_event = (
            system or "",
            dict(entry or {}),
            dict(state or {}),
        )

    def _buffer_startup_dashboard_event(self, entry):
        self._pending_dashboard_event = dict(entry or {})

    def _replay_buffered_startup_events(self):
        pending_dashboard = self._pending_dashboard_event
        pending_journal = self._pending_journal_event
        self._pending_dashboard_event = None
        self._pending_journal_event = None

        if pending_dashboard:
            self._handle_dashboard_entry_ui(pending_dashboard)
        if pending_journal:
            system, entry, state = pending_journal
            self._handle_journal_entry_ui(system, entry, state)

    def _cached_static_layout_width(self, key, factory):
        if key not in self._static_layout_width_cache:
            self._static_layout_width_cache[key] = factory()
        return self._static_layout_width_cache[key]

    def _no_route_top_width(self):
        return self._cached_static_layout_width(
            "no_route_top_width",
            lambda: max(
                self._dropdown_pixel_width(*ROUTE_PLANNERS),
                self._dropdown_pixel_width(*SEARCH_OPTIONS),
                self._button_pixel_width("Plot route", "Search"),
            ),
        )

    def _route_top_width(self):
        return self._cached_static_layout_width(
            "route_top_width",
            lambda: max(
                self._dropdown_pixel_width(*ROUTE_PLANNERS),
                self._dropdown_pixel_width(*SEARCH_OPTIONS),
                self._button_pixel_width("Plot route", "Search"),
                self._button_pixel_width("Clear route", "Import file", "Show route"),
            ),
        )

    def _route_button_width_chars_for_current_route(self):
        route_key = (
            self.next_wp_label,
            tuple(str(stop[0] or "") for stop in self.route if isinstance(stop, (list, tuple)) and stop),
        )
        if route_key == self._route_button_width_cache_key:
            return self._route_button_width_chars

        width_chars = 24
        try:
            import tkinter.font as tkfont

            longest_name = max(route_key[1], key=len, default="")
            btn_font = tkfont.nametofont(self.waypoint_btn.cget("font"))
            longest_px = btn_font.measure(longest_name)
            label_px = btn_font.measure(self.next_wp_label)
            char_w = btn_font.measure("0")
            width_chars = max(24, int((max(longest_px, label_px) + 36 + max(char_w - 1, 0)) / max(char_w, 1)))
        except Exception:
            width_chars = 24

        self._route_button_width_cache_key = route_key
        self._route_button_width_chars = width_chars
        return width_chars

    def _layout_no_route_controls(self):
        self.btn_frame.grid()
        top_width = self._no_route_top_width()
        self.btn_frame.columnconfigure(0, minsize=top_width)
        self.btn_frame.columnconfigure(1, minsize=top_width)
        self.csv_route_btn.config(width=self._compact_button_width)
        self.planner_dropdown.grid(row=0, column=0, pady=2, padx=2, sticky=tk.EW)
        self.plot_btn.grid(row=0, column=1, pady=2, padx=2, sticky=tk.EW)
        self.search_dropdown.grid(row=1, column=0, pady=2, padx=2, sticky=tk.EW)
        self.search_btn.grid(row=1, column=1, pady=2, padx=2, sticky=tk.EW)
        self.csv_route_btn.grid(row=2, column=0, columnspan=2, pady=2, padx=2, sticky="")

    def _layout_route_controls(self):
        self.btn_frame.grid()
        top_width = self._route_top_width()
        self.btn_frame.columnconfigure(0, minsize=top_width)
        self.btn_frame.columnconfigure(1, minsize=top_width)
        self.planner_dropdown.grid(row=0, column=0, pady=2, padx=2, sticky=tk.EW)
        self.plot_btn.grid(row=0, column=1, pady=2, padx=2, sticky=tk.EW)
        self.search_dropdown.grid(row=1, column=0, pady=2, padx=2, sticky=tk.EW)
        self.search_btn.grid(row=1, column=1, pady=2, padx=2, sticky=tk.EW)
        self.clear_route_btn.grid(row=2, column=0, pady=2, padx=2, sticky=tk.EW)
        self.csv_route_btn.config(width=self._main_button_width)
        self.csv_route_btn.grid(row=2, column=1, pady=2, padx=2, sticky=tk.EW)
        self.show_csv_btn.grid(row=3, column=0, columnspan=2, pady=2, padx=2, sticky=tk.EW)

    def _update_route_widget_text(self, route_complete):
        self.waypoint_btn.config(width=self._route_button_width_chars_for_current_route())
        waypoint_text = "Route Complete!" if route_complete else self.next_stop
        self.waypoint_btn["text"] = self.next_wp_label + '\n' + waypoint_text
        if not route_complete:
            self.jumpcounttxt_lbl["text"] = self.jumpcountlbl_txt + str(self.jumps_left)
            self.dist_prev_lbl["text"] = self.dist_prev
            self.dist_next_lbl["text"] = self.dist_next
            self.dist_remaining_lbl["text"] = self.dist_remaining
        else:
            self.jumpcounttxt_lbl["text"] = "Route complete!"

    def _show_route_overlay_controls(self):
        if self.exact_plotter:
            self.overlay_cb.grid(row=0, column=0, sticky=tk.W)
            self.neutron_overlay_cb.grid(row=0, column=1, sticky=tk.W, padx=(15, 0))
            self.overlay_cb_frame.grid()
            if self.overlay_var.get():
                self.overlay_pos_frame.grid(row=1, column=0, sticky=tk.W)
            else:
                self.overlay_pos_frame.grid_remove()
            if self.neutron_overlay_var.get():
                self.neutron_pos_frame.grid(row=1, column=1, sticky=tk.W, padx=(15, 0))
            else:
                self.neutron_pos_frame.grid_remove()
            return

        if self._is_neutron_route_active():
            self.overlay_cb.grid_remove()
            self.overlay_pos_frame.grid_remove()
            self.neutron_overlay_cb.grid(row=0, column=0, columnspan=2, sticky="")
            self.overlay_cb_frame.grid()
            if self.neutron_overlay_var.get():
                self.neutron_pos_frame.grid(row=1, column=0, columnspan=2, sticky="")
            else:
                self.neutron_pos_frame.grid_remove()
            return

        self.overlay_cb.grid(row=0, column=0, sticky=tk.W)
        self.neutron_overlay_cb.grid(row=0, column=1, sticky=tk.W, padx=(15, 0))
        self.overlay_cb_frame.grid_remove()

    def show_route_gui(self, show):
        self.hide_error()
        has_route = show and len(self.route) > 0
        prev_layout = getattr(self, "_route_layout_shown", None)
        layout_changed = prev_layout != has_route
        self._route_layout_shown = has_route
        if layout_changed:
            self._capture_host_resize_anchor()

        if not has_route:
            # Hide route view elements
            self._collapse_btn.grid_remove()
            self.waypoint_prev_btn.grid_remove()
            self.waypoint_btn.grid_remove()
            self.waypoint_next_btn.grid_remove()
            self.jumpcounttxt_lbl.grid_remove()
            self.bodies_lbl.grid_remove()
            self.fleetrestock_lbl.grid_remove()
            self.refuel_lbl.grid_remove()
            self.overlay_cb_frame.grid_remove()
            self.dist_prev_lbl.grid_remove()
            self.dist_next_lbl.grid_remove()
            self.dist_remaining_lbl.grid_remove()
            # Hide route-only buttons
            self.clear_route_btn.grid_remove()
            self.show_csv_btn.grid_remove()
            # Ensure btn_frame is visible (may have been hidden by collapse)
            self._layout_no_route_controls()
            self.waypoint_btn.config(width=24)
            try:
                self.frame.columnconfigure(0, minsize=0)
                self.frame.columnconfigure(1, minsize=0)
                self.frame.columnconfigure(2, minsize=0)
                self.frame.update_idletasks()
            except Exception:
                pass
            if layout_changed:
                self._schedule_main_window_resize(shrink_current=True)
        else:
            self._collapse_btn.grid()
            route_complete = self._route_complete_for_ui()
            self._update_route_widget_text(route_complete)

            # Always-visible widgets (waypoint nav + distances)
            self.waypoint_prev_btn.grid()
            self.waypoint_btn.grid()
            self.waypoint_next_btn.grid()
            if not route_complete:
                self.dist_prev_lbl.grid()
                self.dist_next_lbl.grid()
                self.dist_remaining_lbl.grid()
            else:
                self.dist_prev_lbl.grid_remove()
                self.dist_next_lbl.grid_remove()
                self.dist_remaining_lbl.grid_remove()

            prev_disabled = self.offset == 0
            next_disabled = self.offset == len(self.route) - 1
            if self.fleetcarrier and self.route:
                prev_disabled = self._route_visible_prev_index(self.offset) == self.offset
                next_disabled = self._route_visible_next_index(self.offset) == self.offset

            self.waypoint_prev_btn.config(state=tk.DISABLED if prev_disabled else tk.NORMAL)
            self.waypoint_next_btn.config(state=tk.DISABLED if next_disabled else tk.NORMAL)

            # Collapsible section — only grid widgets when not collapsed
            if not self._controls_collapsed:
                if not route_complete:
                    self.jumpcounttxt_lbl.grid()
                else:
                    self.jumpcounttxt_lbl.grid()

                self.bodies_lbl.grid_remove()

                self.fleetrestock_lbl.grid_remove()
                if self.fleetcarrier:
                    fleet_msgs = []
                    if self._waypoint_reached:
                        fleet_msgs.append("Waypoint reached!")
                        if self._waypoint_reached_restock:
                            fleet_msgs.append(self._fleet_group_restock_text(self.offset))
                    elif 0 <= self.offset < len(self.route):
                        if self._fleet_group_has_restock(self.offset):
                            fleet_msgs.append(self._fleet_group_restock_text(self.offset))
                    if fleet_msgs:
                        self.fleetrestock_lbl["text"] = "\n".join(fleet_msgs)
                        self.fleetrestock_lbl.grid()

                if self.galaxy or self.exact_plotter:
                    if self.pleaserefuel:
                        self.refuel_lbl['text'] = self.refuellbl_txt
                        self.refuel_lbl.grid()
                    else:
                        self.refuel_lbl.grid_remove()

                self._layout_route_controls()
                self._show_route_overlay_controls()
            else:
                # Collapsed — ensure all collapsible widgets are hidden
                # (they may have been gridded by a prior no-route layout)
                for w in (self.bodies_lbl, self.fleetrestock_lbl, self.refuel_lbl,
                          self.btn_frame, self.overlay_cb_frame,
                          self.jumpcounttxt_lbl, self.error_lbl):
                    w.grid_remove()

            self._update_main_panel_widths()
            if layout_changed:
                self._schedule_main_window_resize()

    def update_gui(self):
        self.show_route_gui(True)

    def _toggle_collapse(self):
        self._controls_collapsed = not self._controls_collapsed
        try:
            config.set('spansh_controls_collapsed', int(self._controls_collapsed))
        except Exception:
            pass
        self._collapse_btn.config(text="⏵" if self._controls_collapsed else "⏷")
        self._collapse_tooltip.text = "Expand" if self._controls_collapsed else "Collapse"
        self._capture_host_resize_anchor()
        self._apply_collapse_state()
        self._schedule_main_window_resize(
            shrink_current=self._controls_collapsed,
            preserve_position=True,
        )

    def _apply_collapse_state(self):
        """Show or hide the collapsible controls section."""
        collapsible = [
            self.bodies_lbl,
            self.fleetrestock_lbl,
            self.refuel_lbl,
            self.btn_frame,
            self.overlay_cb_frame,
            self.jumpcounttxt_lbl,
            self.error_lbl,
        ]
        if self._controls_collapsed:
            for widget in collapsible:
                widget.grid_remove()
        else:
            # Re-run show_route_gui to restore correct visibility
            self.show_route_gui(True)

    def _route_complete_for_ui(self):
        if not self.route:
            return False

        done_values = self._route_done_values()
        if done_values and len(done_values) >= len(self.route) and all(done_values[:len(self.route)]):
            return True

        planner_name = self._current_route_planner_name()
        arrival_completion_plotters = {
            "Neutron Plotter",
            "Galaxy Plotter",
            "Road to Riches",
            "Ammonia World Route",
            "Earth-like World Route",
            "Rocky/HMC Route",
            "Exomastery",
        }

        if planner_name in arrival_completion_plotters:
            current_system = self._current_system_name().lower()
            final_system = self._route_name_at(len(self.route) - 1, "").strip().lower()
            return bool(final_system and current_system == final_system and self.jumps_left <= 0)

        if self.fleetcarrier:
            return self._route_visible_next_index(self.offset) == self.offset

        return self.offset >= len(self.route) - 1

    def _on_planner_selected(self, event=None):
        """Save selected planner to EDMC config."""
        try:
            planner = self.planner_var.get()
            idx = ROUTE_PLANNERS.index(planner)
            config.set('spansh_route_planner', idx)
            config.set('spansh_route_planner_name', planner)
        except ValueError:
            pass

    def _reset_exploration_state(self):
        self.exploration_plotter = False
        self.exploration_mode = None
        self.exploration_route_data = []

    def _route_done_values(self):
        if self.exploration_plotter and self.exploration_route_data:
            return self._exploration_system_done_values()
        if self.exact_plotter and self.exact_route_data:
            return [bool(jump.get("done", False)) for jump in self.exact_route_data]
        if self.fleetcarrier and self.fleet_carrier_data:
            return [bool(jump.get("done", False)) for jump in self.fleet_carrier_data]
        return [bool(value) for value in self.route_done]

    def _exploration_system_done_values(self):
        values = []
        for system in self.exploration_route_data:
            bodies = system.get("bodies", []) or []
            if not bodies:
                values.append(bool(system.get("done", False)))
                continue

            body_done_values = []
            for body in bodies:
                landmarks = body.get("landmarks", []) or []
                if self.exploration_mode == "Exomastery" and landmarks:
                    body_done_values.extend(bool(landmark.get("done", False)) for landmark in landmarks)
                else:
                    body_done_values.append(bool(body.get("done", False)))

            values.append(all(body_done_values) if body_done_values else bool(system.get("done", False)))
        return values

    def _invalidate_route_rows(self):
        self.route_rows = []
        self._route_rows_state = None
        self._route_rows_dirty = True
        self._route_rows_signature_cache = None

    def _sync_route_done(self):
        previous = list(self.route_done)
        if self.exact_plotter or self.fleetcarrier or self.exploration_plotter:
            self.route_done = self._route_done_values()
        elif len(self.route_done) < len(self.route):
            self.route_done.extend([False] * (len(self.route) - len(self.route_done)))
        elif len(self.route_done) > len(self.route):
            self.route_done = self.route_done[:len(self.route)]
        if self.route_done != previous:
            self._invalidate_route_rows()

    def _safe_int(self, value, default=0):
        parsed = self._parse_number(value)
        if parsed is None:
            return default
        try:
            return int(parsed)
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value, default=None):
        parsed = self._parse_number(value)
        if parsed is None:
            return default
        try:
            return float(parsed)
        except (TypeError, ValueError):
            return default

    def _validate_integer_input(self, proposed, *, signed=False):
        return validate_integer_input(proposed, signed=signed)

    def _validate_decimal_input(self, proposed, *, maximum_decimals=2):
        return validate_decimal_input(proposed, maximum_decimals=maximum_decimals)

    def _validate_spinbox_input(self, proposed, *, allow_float=False, maximum_decimals=2, signed=False, max_digits=None):
        return validate_spinbox_input(
            proposed,
            allow_float=allow_float,
            maximum_decimals=maximum_decimals,
            signed=signed,
            max_digits=max_digits,
        )

    def _spinbox_validator(self, widget, *, allow_float=False, maximum_decimals=2, signed=False):
        return make_spinbox_validator(
            widget,
            allow_float=allow_float,
            maximum_decimals=maximum_decimals,
            signed=signed,
            safe_float=self._safe_float,
        )

    def _normalize_supercharge_multiplier(self, value, default=4):
        parsed = self._safe_float(value, None)
        if parsed is None:
            return default
        return 6 if parsed >= 5 else 4

    def _normalize_fleet_carrier_type(self, value):
        normalized = str(value or "").strip().lower()
        if normalized in {"squadron", "squadron carrier"}:
            return "squadron"
        if normalized in {"fleet", "player carrier", "player", ""}:
            return "fleet"
        return "fleet"

    def _fleet_carrier_profile(self, carrier_type):
        carrier_type = self._normalize_fleet_carrier_type(carrier_type)
        if carrier_type == "squadron":
            return {
                "carrier_type": "squadron",
                "capacity": 60000,
                "mass": 15000,
            }
        return {
            "carrier_type": "fleet",
            "capacity": 25000,
            "mass": 25000,
        }

    def _infer_fleet_carrier_type(self, *, explicit_type="", capacity=None, mass=None):
        if str(explicit_type).strip():
            return self._normalize_fleet_carrier_type(explicit_type)
        capacity_value = self._safe_int(capacity, None)
        mass_value = self._safe_int(mass, None)
        if capacity_value is not None:
            # Legacy plugin exports used 50000 for player carriers.
            if capacity_value >= 60000:
                return "squadron"
            return "fleet"
        if mass_value == 15000:
            return "squadron"
        return "fleet"

    def _parse_number(self, value):
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)

        cleaned = str(value).strip()
        if not cleaned:
            return None

        cleaned = cleaned.replace(",", "")
        cleaned = cleaned.replace("Cr", "")
        cleaned = cleaned.replace("Ls", "")
        cleaned = cleaned.replace("LS", "")
        cleaned = cleaned.replace("Ly", "")
        cleaned = cleaned.replace("LY", "")
        cleaned = cleaned.strip()
        if not cleaned:
            return None

        try:
            return float(cleaned)
        except ValueError:
            return None

    def _route_raw_row_at(self, index):
        if not (0 <= index < len(self.route)):
            return []
        row = self.route[index]
        return row if isinstance(row, (list, tuple)) else []

    def _route_rows_signature(self):
        if not self._route_rows_dirty and self._route_rows_signature_cache is not None:
            return self._route_rows_signature_cache
        done_count = 0
        first_done_index = None
        last_done_index = None
        done_hash = 2166136261
        for index, done in enumerate(self._route_done_values()):
            marker = 1 if done else 0
            done_hash ^= (index + 1) * marker + marker
            done_hash = (done_hash * 16777619) & 0xFFFFFFFF
            if not done:
                continue
            done_count += 1
            if first_done_index is None:
                first_done_index = index
            last_done_index = index
        signature = (
            len(self.route),
            len(self.exact_route_data),
            len(self.fleet_carrier_data),
            self.route_type,
            done_count,
            first_done_index,
            last_done_index,
            done_hash,
        )
        self._route_rows_signature_cache = signature
        self._route_rows_dirty = False
        return signature

    def _sync_runtime_route_rows(self):
        rows = []
        done_values = self._route_done_values()
        for index in range(len(self.route)):
            raw_row = self._route_raw_row_at(index)
            exact_data = self.exact_route_data[index] if self.exact_plotter and index < len(self.exact_route_data) else {}
            progress = 1 if self.galaxy else self._safe_int(raw_row[1] if len(raw_row) > 1 else None, 0)
            restock_required = len(raw_row) > 4 and str(raw_row[4]).strip().lower() == "yes"
            rows.append({
                "name": str(raw_row[0] or "") if raw_row else "",
                "progress": progress if progress is not None else 0,
                "distance_to_arrival": self._safe_float(raw_row[2] if len(raw_row) > 2 else None, None),
                "remaining_distance": self._safe_float(raw_row[3] if len(raw_row) > 3 else None, None),
                "refuel_required": (
                    (len(raw_row) > 1 and str(raw_row[1]).strip().lower() == "yes")
                    if self.galaxy else bool(exact_data.get("must_refuel", False))
                ),
                "has_neutron": (
                    bool(exact_data.get("has_neutron", False))
                    if self.exact_plotter else (
                        len(raw_row) > 4 and str(raw_row[4]).strip().lower() == "yes" and not self.fleetcarrier
                    )
                ),
                "restock_required": restock_required if self.fleetcarrier else False,
                "done": done_values[index] if index < len(done_values) else False,
            })
        self.route_rows = rows
        self._route_rows_state = self._route_rows_signature()

    def _ensure_runtime_route_rows(self):
        if self._route_rows_state != self._route_rows_signature() or len(self.route_rows) != len(self.route):
            self._sync_runtime_route_rows()

    def _route_row_at(self, index):
        self._ensure_runtime_route_rows()
        if not (0 <= index < len(self.route_rows)):
            return {}
        row = self.route_rows[index]
        return row if isinstance(row, dict) else {}

    def _route_name_at(self, index, default=""):
        row = self._route_row_at(index)
        if not row:
            return default
        return str(row.get("name") or default)

    def _route_source_name(self, default=""):
        return self._route_name_at(0, default)

    def _route_destination_name(self, default=""):
        return self._route_name_at(len(self.route) - 1, default) if self.route else default

    def _current_route_row_name(self, default=""):
        return self._route_name_at(self.offset, default)

    def _route_starts_at_current_system(self):
        if len(self.route) <= 1:
            return False
        route_start = self._route_source_name("").strip().lower()
        current_system = self._current_system_name().lower()
        return bool(route_start and current_system and route_start == current_system)

    def _reset_offset_from_current_system(self):
        if not self.route:
            self.offset = 0
            self.next_stop = ""
            return
        starts_at_current_system = self._route_starts_at_current_system()
        self.offset = 1 if starts_at_current_system else 0
        if starts_at_current_system:
            self._mark_waypoint_done(0)
        self.next_stop = self._route_name_at(self.offset, self._route_source_name(""))

    def _route_progress_value_at(self, index, default=0):
        row = self._route_row_at(index)
        if not row:
            return default
        parsed = self._safe_int(row.get("progress"), default)
        return parsed if parsed is not None else default

    def _route_distance_to_arrival_at(self, index):
        row = self._route_row_at(index)
        if not row:
            return None
        return self._safe_float(row.get("distance_to_arrival"), None)

    def _route_remaining_distance_at(self, index):
        row = self._route_row_at(index)
        if not row:
            return None
        return self._safe_float(row.get("remaining_distance"), None)

    def _route_refuel_required_at(self, index):
        row = self._route_row_at(index)
        return bool(row.get("refuel_required", False)) if row else False

    def _route_has_neutron_at(self, index):
        row = self._route_row_at(index)
        return bool(row.get("has_neutron", False)) if row else False

    def _route_row_state_at(self, index):
        row = self._route_row_at(index)
        return dict(row) if row else {
            "name": "",
            "progress": 0,
            "distance_to_arrival": None,
            "remaining_distance": None,
            "refuel_required": False,
            "has_neutron": False,
            "restock_required": False,
            "done": False,
        }

    def _route_done_at(self, index):
        row = self._route_row_at(index)
        return bool(row.get("done", False)) if row else False

    def _overlay_current_system_index(self):
        if not self.route:
            return None
        anchor_index = self.offset - 1 if self.offset > 0 else 0
        current_system = self._current_system_name().strip().lower()
        if current_system:
            matching_indices = [
                index
                for index in range(len(self.route))
                if self._route_name_at(index, "").strip().lower() == current_system
            ]
            if matching_indices:
                return min(matching_indices, key=lambda index: abs(index - anchor_index))
        return anchor_index if 0 <= anchor_index < len(self.route) else None

    def _has_live_location_state(self):
        current_coords, current_system = self._get_current_location()
        if current_coords is not None:
            return True
        if current_system:
            return True
        try:
            state = getattr(monitor, "state", {}) or {}
            return state.get("StarPos") is not None or bool(state.get("SystemName"))
        except Exception:
            return False

    def _mark_waypoint_done(self, index):
        if not (0 <= index < len(self.route)):
            return
        if self.exact_plotter and index < len(self.exact_route_data):
            self.exact_route_data[index]["done"] = True
            self._invalidate_route_rows()
            return
        if self.fleetcarrier and self.fleet_carrier_data:
            start, end = self._fleet_group_bounds(index)
            for row_index in range(start, min(end + 1, len(self.fleet_carrier_data))):
                self.fleet_carrier_data[row_index]["done"] = True
            self.route_done = self._route_done_values()
            self._invalidate_route_rows()
            return
        if index < len(self.route_done):
            self.route_done[index] = True
            self._invalidate_route_rows()

    def _recalculate_jumps_left_from_offset(self):
        if not self.route or not (0 <= self.offset < len(self.route)):
            self.jumps_left = 0
            return
        if self.fleetcarrier:
            self.jumps_left = self._route_progress_value_at(self.offset)
            return
        self.jumps_left = sum(self._route_progress_value_at(i) for i in range(self.offset, len(self.route)))

    def _fleet_group_bounds(self, index):
        if not self.fleetcarrier or not self.route or not (0 <= index < len(self.route)):
            return index, index
        name = self._route_name_at(index, "").strip().lower()
        start = index
        end = index
        while start > 0 and self._route_name_at(start - 1, "").strip().lower() == name:
            start -= 1
        while end + 1 < len(self.route) and self._route_name_at(end + 1, "").strip().lower() == name:
            end += 1
        return start, end

    def _fleet_group_has_restock(self, index):
        if not self.fleetcarrier or not self.route or not (0 <= index < len(self.route)):
            return False
        start, end = self._fleet_group_bounds(index)
        for row_index in range(start, end + 1):
            row = self._route_row_at(row_index)
            if row.get("restock_required", False):
                return True
        return False

    def _fleet_group_is_waypoint(self, index):
        if not self.fleetcarrier or not self.route or not (0 <= index < len(self.route)):
            return False
        start, end = self._fleet_group_bounds(index)
        if self.fleet_carrier_data:
            for jump in self.fleet_carrier_data[start:end + 1]:
                if jump.get("is_waypoint") or jump.get("is_desired_destination"):
                    return True
        if start == 0 or end == len(self.route) - 1:
            return True
        if end > start:
            return True
        return False

    def _fleet_group_restock_text(self, index):
        if not self.fleetcarrier or not self.route or not (0 <= index < len(self.route)):
            return ""
        if not self._fleet_group_has_restock(index):
            return ""

        amount = None
        start, end = self._fleet_group_bounds(index)
        if self.fleet_carrier_data:
            for jump in self.fleet_carrier_data[start:end + 1]:
                parsed = self._safe_int(jump.get("restock_amount", ""), default=0)
                if parsed:
                    amount = parsed
                    break

        if amount:
            return f"{self.fleetstocklbl_txt}: {amount:,}"
        return self.fleetstocklbl_txt

    def _format_whole_number(self, value, suffix=""):
        parsed = self._parse_number(value)
        if parsed is None:
            return ""
        text = f"{int(parsed):,}"
        return f"{text} {suffix}".strip()

    def _format_decimal_number(self, value, suffix="", decimals=2):
        parsed = self._parse_number(value)
        if parsed is None:
            return ""
        text = f"{parsed:,.{decimals}f}"
        return f"{text} {suffix}".strip()

    def _button_pixel_width(self, *labels):
        try:
            import tkinter.font as tkfont
            btn_font = tkfont.nametofont(self.plot_btn.cget("font"))
            return max(btn_font.measure(str(label)) for label in labels if label) + 40
        except Exception:
            fallback = max((len(str(label)) for label in labels if label), default=1)
            return fallback * 8 + 40

    def _dropdown_pixel_width(self, *labels):
        try:
            import tkinter.font as tkfont
            combo_font = tkfont.nametofont("TkDefaultFont")
            return max(combo_font.measure(str(label)) for label in labels if label) + 28
        except Exception:
            fallback = max((len(str(label)) for label in labels if label), default=1)
            return fallback * 8 + 28

    def _text_pixel_width(self, widget, *labels, padding=0):
        try:
            import tkinter.font as tkfont
            font = tkfont.nametofont(widget.cget("font"))
            return max((font.measure(str(label)) for label in labels if label), default=0) + padding
        except Exception:
            fallback = max((len(str(label)) for label in labels if label), default=0)
            return fallback * 8 + padding

    def _update_main_panel_widths(self):
        try:
            self.frame.update_idletasks()
        except Exception:
            return

        left_group_width = max(
            getattr(self.waypoint_btn, "winfo_reqwidth", lambda: 0)(),
            self._text_pixel_width(
                self.waypoint_btn,
                self.next_wp_label,
                self.next_stop,
                padding=52,
            ),
        )
        left_column_width = max(95, int((left_group_width + 1) / 2))

        right_group_width = max(
            160,
            self._text_pixel_width(
                self.dist_prev_lbl,
                getattr(self.dist_prev_lbl, "cget", lambda _k: "")("text"),
                getattr(self.dist_next_lbl, "cget", lambda _k: "")("text"),
                getattr(self.dist_remaining_lbl, "cget", lambda _k: "")("text"),
                padding=22,
            ),
        )

        try:
            self.frame.columnconfigure(0, minsize=left_column_width)
            self.frame.columnconfigure(1, minsize=left_column_width)
            self.frame.columnconfigure(2, minsize=right_group_width)
        except Exception:
            pass

    def _capture_host_window_base_size(self):
        try:
            if not getattr(self, "frame", None):
                return
            self.frame.update_idletasks()
            toplevel = self.frame.winfo_toplevel()
            toplevel.update_idletasks()
            host_req_width = max(1, int(toplevel.winfo_reqwidth()))
            host_req_height = max(1, int(toplevel.winfo_reqheight()))
            self._host_base_req_width = host_req_width
            self._host_base_extra_width = 0
            self._host_base_extra_height = 0
        except Exception:
            self._host_base_req_width = 300
            self._host_base_extra_width = 0
            self._host_base_extra_height = 0

    def _capture_host_resize_anchor(self):
        if self._host_resize_anchor_x is not None and self._host_resize_anchor_y is not None:
            return
        try:
            if not getattr(self, "frame", None):
                return
            toplevel = self.frame.winfo_toplevel()
            self._host_resize_anchor_x = int(toplevel.winfo_x())
            self._host_resize_anchor_y = int(toplevel.winfo_y())
        except Exception:
            self._host_resize_anchor_x = None
            self._host_resize_anchor_y = None

    def _schedule_main_window_resize(self, *, shrink_current=False, preserve_position=False):
        if not getattr(self, "_host_window_resize_ready", True):
            return
        if not getattr(self, "frame", None):
            return
        self._host_resize_shrink = shrink_current
        self._host_resize_preserve_position = preserve_position
        self._host_resize_retry_count = 1 if preserve_position else 0
        if preserve_position:
            self._capture_host_resize_anchor()
        else:
            self._host_resize_anchor_x = None
            self._host_resize_anchor_y = None
        if self._host_resize_job is not None:
            try:
                self.frame.after_cancel(self._host_resize_job)
            except Exception:
                pass
        if self._host_resize_retry_job is not None:
            try:
                self.frame.after_cancel(self._host_resize_retry_job)
            except Exception:
                pass
            self._host_resize_retry_job = None
        try:
            self._host_resize_job = self.frame.after_idle(self._apply_main_window_resize)
        except Exception:
            self._host_resize_job = None

    def _apply_main_window_resize(self):
        self._host_resize_job = None
        try:
            if not getattr(self, "_host_window_resize_ready", True):
                return
            if not getattr(self, "frame", None):
                return
            self.frame.update_idletasks()
            toplevel = self.frame.winfo_toplevel()
            try:
                toplevel.update_idletasks()
            except Exception:
                pass
            target_width = max(300, int(toplevel.winfo_reqwidth() or 300))
            target_height = max(1, int(toplevel.winfo_reqheight() or 1))
            current_width = max(1, int(toplevel.winfo_width()))
            current_height = max(1, int(toplevel.winfo_height()))
            actual_x = int(toplevel.winfo_x())
            actual_y = int(toplevel.winfo_y())
            shrink_current = self._host_resize_shrink
            # Only set minsize for width — never constrain height so the
            # window manager can freely shrink the window vertically.
            try:
                toplevel.minsize(target_width, 0)
            except Exception:
                pass
            try:
                desired_width = current_width
                desired_height = current_height
                preserve_position = bool(self._host_resize_preserve_position)
                current_x = self._host_resize_anchor_x if preserve_position else None
                current_y = self._host_resize_anchor_y if preserve_position else None

                if shrink_current:
                    desired_width = target_width
                    desired_height = target_height
                else:
                    desired_width = max(current_width, target_width)
                    desired_height = max(current_height, target_height)

                if current_width <= 1:
                    desired_width = target_width
                if current_height <= 1:
                    desired_height = target_height

                size_changed = desired_width != current_width or desired_height != current_height
                position_changed = preserve_position and (current_x != actual_x or current_y != actual_y)

                if size_changed or position_changed:
                    if preserve_position and current_x is not None and current_y is not None:
                        toplevel.geometry(f"{desired_width}x{desired_height}+{current_x}+{current_y}")
                    else:
                        toplevel.geometry(f"{desired_width}x{desired_height}")
            except Exception:
                pass
        except Exception:
            pass
        finally:
            scheduled_retry = False
            if self._host_resize_retry_count > 0 and getattr(self, "frame", None):
                self._host_resize_retry_count -= 1
                try:
                    self._host_resize_retry_job = self.frame.after(45, self._apply_main_window_resize)
                    scheduled_retry = True
                except Exception:
                    self._host_resize_retry_job = None
            if not scheduled_retry:
                self._host_resize_retry_job = None
                self._host_resize_preserve_position = False
                self._host_resize_anchor_x = None
                self._host_resize_anchor_y = None

    def _host_toplevel(self):
        parent = getattr(self, "parent", None)
        if parent is None:
            return None
        try:
            return parent.winfo_toplevel()
        except Exception:
            return None

    def _raise_child_window(self, window):
        if not window:
            return
        try:
            window.lift()
            window.focus_force()
        except Exception:
            return
        try:
            window.attributes("-topmost", True)
            window.after_idle(lambda w=window: w.winfo_exists() and w.attributes("-topmost", False))
        except Exception:
            pass

    def _position_child_window_next_to_host(self, window, host):
        if not window or host is None:
            return
        try:
            window.update_idletasks()
            host.update_idletasks()
        except Exception:
            pass
        try:
            host_x = int(host.winfo_rootx())
            host_y = int(host.winfo_rooty())
            host_width = max(1, int(host.winfo_width()))
            host_height = max(1, int(host.winfo_height()))
            child_width = max(1, int(window.winfo_reqwidth() or window.winfo_width()))
            child_height = max(1, int(window.winfo_reqheight() or window.winfo_height()))
            screen_width = max(1, int(window.winfo_screenwidth()))
            screen_height = max(1, int(window.winfo_screenheight()))
        except Exception:
            return

        margin = 12
        desired_x = host_x + host_width + margin
        if desired_x + child_width > screen_width:
            desired_x = max(0, host_x - child_width - margin)
        desired_y = host_y
        if desired_y + child_height > screen_height:
            desired_y = max(0, screen_height - child_height - margin)

        try:
            window.geometry(f"+{int(desired_x)}+{int(desired_y)}")
        except Exception:
            pass

    def _configure_child_window(self, window):
        if not window:
            return
        host = self._host_toplevel()
        if host is not None:
            try:
                window.transient(host)
            except Exception:
                pass
            self._position_child_window_next_to_host(window, host)
            try:
                window.after_idle(lambda w=window, h=host: self._position_child_window_next_to_host(w, h))
            except Exception:
                pass
            try:
                window.after(30, lambda w=window, h=host: self._position_child_window_next_to_host(w, h))
            except Exception:
                pass
        self._raise_child_window(window)

    def _set_neutron_error(self, message):
        target = getattr(self, "neutron_error_txt", None)
        if target is None:
            target = self.error_txt
        try:
            target.set(message)
        except Exception:
            pass

    def _set_main_controls_enabled(self, enable):
        button_state = tk.NORMAL if enable else tk.DISABLED
        combo_state = "readonly" if enable else tk.DISABLED

        for widget in (
            getattr(self, "planner_dropdown", None),
            getattr(self, "search_dropdown", None),
            getattr(self, "plot_btn", None),
            getattr(self, "csv_route_btn", None),
            getattr(self, "search_btn", None),
            getattr(self, "clear_route_btn", None),
            getattr(self, "show_csv_btn", None),
            getattr(self, "waypoint_prev_btn", None),
            getattr(self, "waypoint_btn", None),
            getattr(self, "waypoint_next_btn", None),
            getattr(self, "overlay_cb", None),
            getattr(self, "neutron_overlay_cb", None),
            getattr(self, "overlay_x_spin", None),
            getattr(self, "overlay_y_spin", None),
            getattr(self, "neutron_x_spin", None),
            getattr(self, "neutron_y_spin", None),
            getattr(self, "update_btn", None),
        ):
            if widget is None:
                continue
            if isinstance(widget, ttk.Combobox):
                try:
                    widget.config(state=combo_state)
                except Exception:
                    pass
                continue
            try:
                widget.config(state=button_state)
            except Exception:
                pass

    def _set_window_widgets_enabled(self, window, enable):
        try:
            if not window or not window.winfo_exists():
                return
        except tk.TclError:
            return

        default_state = tk.NORMAL if enable else tk.DISABLED
        combo_state = "readonly" if enable else tk.DISABLED

        def walk(widget):
            try:
                children = list(widget.winfo_children())
            except Exception:
                children = []

            for child in children:
                walk(child)
                try:
                    if isinstance(child, tk.Button) and child.cget("text") == "Cancel":
                        child.config(state=tk.NORMAL)
                        continue
                except Exception:
                    pass

                try:
                    if isinstance(child, ttk.Combobox):
                        child.config(state=combo_state)
                    else:
                        child.config(state=default_state)
                except Exception:
                    pass

        walk(window)

    def _set_plotter_windows_enabled(self, enable):
        self._set_window_widgets_enabled(getattr(self, "plotter_win", None), enable)
        self._set_window_widgets_enabled(getattr(self, "exact_win", None), enable)

    def _csv_row_value(self, row, *keys):
        for key in keys:
            if key in row:
                return row.get(key, "")
        return ""

    def _is_done_value(self, value):
        return str(value).strip().lower() in {"1", "true", "yes", "done", "checked", "x", "☑", "☒", "■", "▣", "✓", "✔", "🟩"}

    def _done_cell_value(self, done):
        return "🟩" if done else "□"

    def _log_unexpected(self, context, *, level="warning"):
        getattr(logger, level, logger.warning)(context, exc_info=True)

    def _next_plot_token(self):
        with self._plot_state_lock:
            self._plot_token += 1
            return self._plot_token

    def _current_plot_token(self):
        with self._plot_state_lock:
            return self._plot_token

    def _invalidate_plot_token(self):
        with self._plot_state_lock:
            self._plot_token += 1

    def _set_plot_state(self, *, plotting=None, plot_cancelled=None, exact_plot_cancelled=None):
        with self._plot_state_lock:
            if plotting is not None:
                self._plotting = plotting
            if plot_cancelled is not None:
                self._plot_cancelled = plot_cancelled
            if exact_plot_cancelled is not None:
                self._exact_plot_cancelled = exact_plot_cancelled

    def _is_plotting(self):
        with self._plot_state_lock:
            return bool(self._plotting)

    def _is_plot_cancelled(self, *, exact=False):
        with self._plot_state_lock:
            return bool(self._exact_plot_cancelled if exact else self._plot_cancelled)

    def _mark_plot_started(self, *, exact=False):
        self._set_plot_state(
            plotting=True,
            plot_cancelled=False if not exact else None,
            exact_plot_cancelled=False if exact else None,
        )

    def _mark_plot_stopped(self, *, cancelled=False, exact=False):
        self._set_plot_state(
            plotting=False,
            plot_cancelled=bool(cancelled) if not exact else None,
            exact_plot_cancelled=bool(cancelled) if exact else None,
        )

    def _cancel_flag_from_attr(self, cancel_attr):
        if cancel_attr == "_exact_plot_cancelled":
            return self._is_plot_cancelled(exact=True)
        if cancel_attr == "_plot_cancelled":
            return self._is_plot_cancelled(exact=False)
        with self._plot_state_lock:
            return bool(getattr(self, cancel_attr, False))

    def _set_current_location(self, *, coords=None, system=None, clear_coords=False):
        with self._current_location_lock:
            if clear_coords:
                self.current_coords = None
            elif coords is not None:
                if isinstance(coords, (list, tuple)):
                    self.current_coords = list(coords)
                else:
                    self.current_coords = coords
            if system is not None:
                self.current_system = system or ""

    def _get_current_location(self):
        with self._current_location_lock:
            if isinstance(self.current_coords, list):
                coords = list(self.current_coords)
            elif isinstance(self.current_coords, tuple):
                coords = tuple(self.current_coords)
            else:
                coords = self.current_coords
            return coords, self.current_system

    def _current_system_name(self):
        _coords, current_system = self._get_current_location()
        if current_system:
            return str(current_system).strip()
        try:
            return str(monitor.state.get("SystemName") or "").strip()
        except Exception:
            return ""

    def _call_on_ui_thread_sync(self, callback, *args, timeout=1.0):
        frame = getattr(self, "frame", None)
        if threading.current_thread() is threading.main_thread():
            return callback(*args)
        if frame is None:
            raise RuntimeError("UI frame is not available for synchronous callback")
        try:
            if not frame.winfo_exists():
                raise RuntimeError("UI frame is not available for synchronous callback")
        except Exception as exc:
            raise RuntimeError("UI frame is not available for synchronous callback") from exc

        done = threading.Event()
        result = {"value": None, "error": None}

        def runner():
            try:
                result["value"] = callback(*args)
            except Exception as exc:
                result["error"] = exc
            finally:
                done.set()

        try:
            frame.after(0, runner)
        except Exception as exc:
            raise RuntimeError("Failed to schedule synchronous callback on UI thread") from exc

        if not done.wait(timeout):
            raise TimeoutError(f"UI callback timed out after {timeout:.1f}s")
        if result["error"] is not None:
            raise result["error"]
        return result["value"]

    def _shutdown_close_windows(self):
        try:
            if self.csv_viewer_win:
                self.csv_viewer_win.destroy()
        except Exception:
            pass
        finally:
            self._close_csv_viewer()

        for attr in ("plotter_win", "exact_win"):
            win = getattr(self, attr, None)
            if not win:
                continue
            try:
                win.destroy()
            except Exception:
                pass
            finally:
                setattr(self, attr, None)
        self._plotter_window_kind = None

    def shutdown(self):
        self._invalidate_plot_token()
        self._mark_plot_stopped(cancelled=True)
        self._mark_plot_stopped(cancelled=True, exact=True)
        ok = True
        for label, callback in (
            ("close auxiliary windows", self._shutdown_close_windows),
            ("save route state", self.save_all_route),
            ("clear overlay", self._clear_overlay),
            ("clear neutron overlay", self._clear_neutron_overlay),
        ):
            try:
                self._call_on_ui_thread_sync(callback)
            except Exception:
                ok = False
                self._log_unexpected(f"Shutdown failed to {label}")
        return ok

    def _ui_call(self, callback, *args, token=None):
        frame = getattr(self, "frame", None)
        if frame is None:
            return
        try:
            if not frame.winfo_exists():
                return
        except Exception:
            return

        def runner():
            try:
                if not frame.winfo_exists():
                    return
            except Exception:
                return
            if token is not None and token != self._current_plot_token():
                return
            try:
                callback(*args)
            except tk.TclError:
                pass
            except Exception:
                self._log_unexpected(
                    f"Unhandled UI callback failure in {getattr(callback, '__name__', repr(callback))}"
                )

        try:
            frame.after(0, runner)
        except Exception:
            pass

    def _window_after_if_alive(self, window, delay, callback, *args):
        if window is None:
            return False
        try:
            if not window.winfo_exists():
                return False
            window.after(delay, callback, *args)
            return True
        except Exception:
            return False

    def handle_journal_entry(self, system, entry, state):
        if not getattr(self, "frame", None):
            self._buffer_startup_journal_event(system, entry, state)
            return
        safe_entry = dict(entry or {})
        safe_state = dict(state or {})
        self._ui_call(self._handle_journal_entry_ui, system or "", safe_entry, safe_state)

    def handle_dashboard_entry(self, entry):
        if not getattr(self, "frame", None):
            self._buffer_startup_dashboard_event(entry)
            return
        safe_entry = dict(entry or {})
        self._ui_call(self._handle_dashboard_entry_ui, safe_entry)

    def _handle_dashboard_entry_ui(self, entry):
        fuel = entry.get("Fuel")
        if isinstance(fuel, dict):
            fuel_main = self._safe_float(fuel.get("FuelMain"), None)
            if fuel_main is not None and fuel_main >= 0:
                self.current_fuel_main = fuel_main
            fuel_reservoir = self._safe_float(fuel.get("FuelReservoir"), None)
            if fuel_reservoir is not None and fuel_reservoir >= 0:
                self.current_fuel_reservoir = fuel_reservoir

        # Dashboard GuiFocus updates are a safe overlay wake-up signal.
        if "GuiFocus" in entry:
            try:
                self._update_overlay()
            except Exception:
                self._log_unexpected("Failed to refresh overlay from dashboard GuiFocus")

    def _journal_star_system(self, system, entry, state):
        return (
            entry.get("StarSystem", "")
            or entry.get("SystemName", "")
            or system
            or state.get("SystemName", "")
            or monitor.state.get("SystemName", "")
        )

    def _handle_journal_entry_ui(self, system, entry, state):
        event = entry.get("event")
        route_advanced = False

        try:
            if event == 'JetConeBoost':
                self._supercharge_state_known = True
                self.is_supercharged = True
                self._update_overlay()
            elif event == 'FSDJump':
                self._supercharge_state_known = True
                self.is_supercharged = False
        except Exception:
            self._log_unexpected("Failed to process journal supercharge state")

        try:
            star_system = self._journal_star_system(system, entry, state)
        except Exception:
            star_system = ""
            self._log_unexpected("Failed to resolve journal system name")

        try:
            if star_system:
                clear_coords = event == 'CarrierJump' and 'StarPos' not in entry
                self._set_current_location(
                    coords=entry.get('StarPos') if event in ['FSDJump', 'Location', 'CarrierJump'] and 'StarPos' in entry else None,
                    system=star_system,
                    clear_coords=clear_coords,
                )
        except Exception:
            self._log_unexpected("Failed to update current location from journal")

        try:
            route_complete = self._route_complete_for_ui()
            if (
                event in ['FSDJump', 'CarrierJump', 'Location']
                and star_system and star_system.lower() == self.next_stop.lower()
                and not route_complete
            ):
                self.update_route()
                route_advanced = True
                self.set_source_ac(star_system)
        except Exception:
            self._log_unexpected("Failed to process journal route progression")

        try:
            if event == 'Loadout':
                self.process_loadout(entry)
        except Exception:
            self._log_unexpected("Failed to process journal loadout")

        try:
            current_coords, current_system = self._get_current_location()
            if current_coords is None and state.get('StarPos'):
                self._set_current_location(
                    coords=state['StarPos'],
                    system=current_system or state.get('SystemName', '') or monitor.state.get("SystemName", ""),
                )
        except Exception:
            self._log_unexpected("Failed to seed current location from journal state")

        try:
            self.try_fsd_from_state(state)
        except Exception:
            self._log_unexpected("Failed to detect FSD from journal state")

        try:
            if self._journal_event_refreshes_overlay(event) and not route_advanced:
                self._update_overlay()
        except Exception:
            self._log_unexpected("Failed to refresh overlay from journal event")

    def _journal_event_refreshes_overlay(self, event):
        return event in {
            "CarrierJump",
            "FSDJump",
            "FSSDiscoveryScan",
            "GUIFocus",
            "Location",
            "StartJump",
            "SupercruiseEntry",
            "SupercruiseExit",
        }

    def _resolve_system_record_async(self, query, *, on_success, on_not_found=None, on_error=None, token=None):
        query = (query or "").strip()
        if not query:
            return

        def worker():
            try:
                record = self._resolve_system_record(query)
                record_name = (record.get("name") or "").strip() if isinstance(record, dict) else ""
                if not record_name or record_name.lower() != query.lower():
                    if callable(on_not_found):
                        self._ui_call(on_not_found, query, token=token)
                    return
                self._ui_call(on_success, record_name, token=token)
            except Exception as exc:
                if callable(on_error):
                    self._ui_call(on_error, query, str(exc), token=token)

        threading.Thread(target=worker, daemon=True).start()

    def _terraformable_display_value(self, value):
        text = str(value).strip()
        if text == "":
            return ""
        return "✓" if text.lower() == "yes" or value is True else "✕"

    def _is_terraformable_value(self, value):
        return str(value).strip().lower() in {"yes", "true", "1", "✓", "✔"}

    def _traditional_form_data(self, params):
        encoded = []
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
                for item in value:
                    encoded.append((key, item))
            else:
                encoded.append((key, value))
        return encoded

    def _set_entry_value(self, widget, value):
        try:
            widget.delete(0, tk.END)
            widget.insert(0, str(value))
        except Exception:
            pass

    def _clamp_numeric_input(self, widget, minimum, maximum, *, integer=False, error_message="Invalid number"):
        return clamp_numeric_input(
            widget,
            minimum,
            maximum,
            integer=integer,
            error_message=error_message,
            set_entry_value=self._set_entry_value,
        )

    def _clamp_spinbox_input(self, widget, *, integer=False, error_message="Invalid number"):
        return clamp_spinbox_input(
            widget,
            integer=integer,
            error_message=error_message,
            safe_float=self._safe_float,
            set_entry_value=self._set_entry_value,
        )

    def _live_clamp_spinbox_input(self, widget, *, integer=False):
        return live_clamp_spinbox_input(
            widget,
            integer=integer,
            parse_number=self._parse_number,
            set_entry_value=self._set_entry_value,
        )

    def _bind_live_spinbox_clamp(self, widget, *, integer=False):
        def _apply(_event=None):
            try:
                widget.after_idle(lambda w=widget: self._live_clamp_spinbox_input(w, integer=integer))
            except Exception:
                try:
                    self._live_clamp_spinbox_input(widget, integer=integer)
                except Exception:
                    pass

        bind_live_spinbox_clamp(widget, _apply)

    def _close_csv_viewer(self):
        self.csv_viewer_win = None
        self._csv_viewer_signature = None
        self._csv_viewer_runtime = None

    def _current_route_planner_name(self):
        if self.current_plotter_name:
            return self.current_plotter_name
        if self.route_type == "neutron":
            return "Neutron Plotter"
        if self.route_type == "simple":
            return "Simple Route"
        if self.route_type == "exploration" and self.exploration_mode:
            return self.exploration_mode
        if self.route_type == "fleet_carrier":
            return "Fleet Carrier Router"
        if self.route_type in ("exact", "galaxy"):
            return "Galaxy Plotter"
        return ""

    def _resolve_system_record(self, query):
        query = query.strip()
        if not query:
            return None
        if query.isdigit():
            resp = requests.get(f"https://spansh.co.uk/api/system/{query}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("record", data)
            return None

        resp = requests.get("https://spansh.co.uk/api/search/systems", params={"q": query}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        results = data.get("results", data if isinstance(data, list) else [])
        if isinstance(results, dict):
            results = results.get("results", [])
        if not isinstance(results, list):
            return None
        exact = next((r for r in results if (r.get("name") or "").strip().lower() == query.lower()), None)
        return exact

    def show_csv_viewer(self):
        """Open the route viewer window."""
        return CsvViewerWindow(self).show()

    def _refresh_csv_viewer_if_open(self):
        if not self.csv_viewer_win:
            return
        try:
            if not self.csv_viewer_win.winfo_exists():
                self._close_csv_viewer()
                return
        except Exception:
            self._close_csv_viewer()
            return
        CsvViewerWindow(self).show(force_refresh=True)

    def _capture_csv_viewer_geometry(self):
        if not self.csv_viewer_win:
            return None
        try:
            if self.csv_viewer_win.winfo_exists():
                return self.csv_viewer_win.geometry()
        except Exception:
            self._close_csv_viewer()
        return None

    def _close_csv_viewer_if_open(self):
        if not self.csv_viewer_win:
            return
        try:
            if self.csv_viewer_win.winfo_exists():
                self.csv_viewer_win.destroy()
        except Exception:
            pass
        self._close_csv_viewer()

    def _restore_csv_viewer_after_route_change(self, geometry):
        if not geometry:
            return
        try:
            CsvViewerWindow(self).show(force_refresh=True, restore_geometry=geometry)
        except Exception:
            self._log_unexpected("Failed to restore route viewer")

    def show_error(self, error):
        self.error_txt.set(error)
        self.error_lbl.grid()

    def hide_error(self):
        self.error_lbl.grid_remove()

    def enable_plot_gui(self, enable):
        """Enable/disable neutron plotter widgets in the Toplevel window."""
        self._set_main_controls_enabled(enable)
        self._set_plotter_windows_enabled(enable)

    #   -- END GUI part --


    def open_last_route(self):
        try:
            self._host_window_resize_ready = False
            self._load_plotter_settings()
            route_state = self._load_route_state()
            if not route_state:
                self._host_window_resize_ready = True
                return
            self._apply_route_state(route_state)

            if not self.route:
                self._host_window_resize_ready = True
                return
            if self.offset >= len(self.route):
                self.offset = 0
            elif self.offset < 0:
                self.offset = 0

            self._sync_route_done()
            self._seed_current_location_from_monitor()
            saved_jumps_left = self._safe_int(route_state.get("jumps_left"), None)
            if saved_jumps_left is None:
                self._recalculate_jumps_left_from_offset()
            else:
                self.jumps_left = max(0, saved_jumps_left)
            if self._route_complete_for_ui():
                self.jumps_left = 0
            self.next_stop = self._route_name_at(self.offset, "")

            if (self.exact_plotter or self.galaxy) and self.offset < len(self.route):
                self.pleaserefuel = self._route_refuel_required_at(self.offset)

            self.compute_distances()
            self._host_window_resize_ready = True
            self.update_gui()
            self._update_overlay()

        except IOError:
            logger.info("No previously saved route")
        except Exception:
            self._log_unexpected("Failed to restore saved route")
        finally:
            self._host_window_resize_ready = True

    def _seed_current_location_from_monitor(self):
        try:
            state = getattr(monitor, "state", {}) or {}
            coords = state.get("StarPos")
            system = state.get("SystemName", "")
            if coords is not None or system:
                self._set_current_location(coords=coords, system=system)
        except Exception:
            pass

    def _show_clipboard_error_once(self):
        if self._clipboard_error_reported:
            return
        self._clipboard_error_reported = True
        try:
            self.show_error("Clipboard copy failed.")
        except Exception:
            logger.warning("Clipboard copy failed", exc_info=True)

    def _copy_to_clipboard_with_tk(self, text):
        parent = getattr(self, "parent", None)
        if parent is None:
            return False
        try:
            parent.clipboard_clear()
            parent.clipboard_append(text)
            update_idletasks = getattr(parent, "update_idletasks", None)
            if callable(update_idletasks):
                update_idletasks()
            else:
                update = getattr(parent, "update", None)
                if callable(update):
                    update()
            return True
        except Exception:
            return False

    def _linux_clipboard_commands(self):
        override = os.getenv("EDMC_SPANSH_TOOLS_XCLIP", "").strip()
        if override:
            try:
                return [shlex.split(override)]
            except Exception:
                return []

        def _host_or_system(binary):
            host_binary = f"/run/host/usr/bin/{binary}"
            if os.path.exists(host_binary):
                return host_binary
            return binary

        if os.environ.get("WAYLAND_DISPLAY"):
            wl_copy = _host_or_system("wl-copy")
            return [
                [wl_copy],
                [wl_copy, "--primary"],
            ]

        xclip = _host_or_system("xclip")
        return [
            [xclip, "-selection", "clipboard"],
            [xclip, "-selection", "primary"],
        ]

    def _copy_to_clipboard_linux_worker(self, text):
        for command in self._linux_clipboard_commands():
            if not command:
                continue
            try:
                proc = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc.communicate(text.encode("utf-8"), timeout=3)
                if proc.returncode == 0:
                    return
            except Exception:
                continue
        self._ui_call(self._show_clipboard_error_once)

    def _copy_to_clipboard(self, text):
        """Best-effort clipboard copy without blocking hot paths."""
        text = str(text or "")
        if not text:
            return False
        if sys.platform in ("linux", "linux2"):
            try:
                threading.Thread(
                    target=self._copy_to_clipboard_linux_worker,
                    args=(text,),
                    daemon=True,
                ).start()
                return True
            except Exception:
                self._show_clipboard_error_once()
                return False

        if threading.current_thread() is not threading.main_thread():
            self._ui_call(self._copy_to_clipboard, text)
            return True

        if self._copy_to_clipboard_with_tk(text):
            return True
        self._show_clipboard_error_once()
        return False

    def copy_waypoint(self):
        self._copy_to_clipboard(self.next_stop)

    def goto_next_waypoint(self):
        # allow manual navigation even if offset wasn't set by journal events yet
        if len(self.route) == 0:
            return

        if not hasattr(self, "offset") or self.offset is None:
            self.offset = 0

        if self.offset < len(self.route) - 1:
            self._manual_nav = True
            self.update_route(1, refresh_viewer=False)
            self._manual_nav = False
            if self.fleetcarrier:
                self._waypoint_reached = self._fleet_group_is_waypoint(self.offset)
                self._waypoint_reached_restock = self._waypoint_reached and self._fleet_group_has_restock(self.offset)
                self.update_gui()
            else:
                self._waypoint_reached = False
                self._waypoint_reached_restock = False

    def goto_prev_waypoint(self):
        # allow manual navigation even if offset wasn't set by journal events yet
        if len(self.route) == 0:
            return

        if not hasattr(self, "offset") or self.offset is None:
            self.offset = 0

        if self.offset > 0:
            self._manual_nav = True
            self.update_route(-1, refresh_viewer=False)
            self._manual_nav = False
            if self.fleetcarrier:
                self._waypoint_reached = self._fleet_group_is_waypoint(self.offset)
                self._waypoint_reached_restock = self._waypoint_reached and self._fleet_group_has_restock(self.offset)
                self.update_gui()
            else:
                self._waypoint_reached = False
                self._waypoint_reached_restock = False

    def _route_visible_next_index(self, index):
        if not self.route:
            return index
        if self.fleetcarrier:
            current_name = self._route_name_at(index, "").strip().lower()
            while index < len(self.route) - 1 and self._route_name_at(index + 1, "").strip().lower() == current_name:
                index += 1
            if index < len(self.route) - 1:
                index += 1
        elif index < len(self.route) - 1:
            index += 1
        return index

    def _route_visible_prev_index(self, index):
        if not self.route:
            return index
        if self.fleetcarrier:
            current_name = self._route_name_at(index, "").strip().lower()
            while index > 0 and self._route_name_at(index - 1, "").strip().lower() == current_name:
                index -= 1
            if index > 0:
                index -= 1
                previous_name = self._route_name_at(index, "").strip().lower()
                while index > 0 and self._route_name_at(index - 1, "").strip().lower() == previous_name:
                    index -= 1
        elif index > 0:
            index -= 1
        return index

    def compute_distances(self):
        """Compute LY from prev, to next, and total remaining.

        Correct semantics:
          - Distance To Arrival (if present) is stored on the target row:
              route[i][2] == distance from route[i-1] -> route[i]
          - Distance Remaining (if present) is stored on the current row as route[i][3].
        This function handles rows that may or may not have the distance columns.
        """
        # Reset
        self.dist_prev = ""
        self.dist_next = ""
        self.dist_remaining = ""

        if not (0 <= self.offset < len(self.route)):
            return

        def safe_flt(x):
            try:
                return float(x)
            except Exception:
                return None

        def fmt_num(v):
            """Format number: integer if whole, 2 decimals otherwise."""
            if not math.isfinite(v):
                return ""
            return str(int(v)) if v == int(v) else f"{v:.2f}"

        planner_name = self._current_route_planner_name()
        use_spansh_distance_labels = planner_name in ("Neutron Plotter", "Galaxy Plotter") or self.exact_plotter or self.fleetcarrier

        if self.fleetcarrier:
            group_start, group_end = self._fleet_group_bounds(self.offset)
            pv = self._route_distance_to_arrival_at(group_start)
            if pv is not None:
                self.dist_prev = f"{'Distance (Ly)' if use_spansh_distance_labels else 'Jump LY'}: {fmt_num(pv)}"

            if group_end < len(self.route) - 1:
                nv = self._route_distance_to_arrival_at(group_end + 1)
                if nv is not None:
                    next_label = "Next Distance (Ly)" if use_spansh_distance_labels else "Next jump LY"
                    self.dist_next = f"{next_label}: {fmt_num(nv)}"

            total_rem = self._route_remaining_distance_at(group_end)
            if total_rem is not None:
                remaining_label = "Remaining (Ly)" if use_spansh_distance_labels else "LY afterwards"
                self.dist_remaining = f"{remaining_label}: {fmt_num(total_rem)}"
            return

        # --- LY from previous ---
        # distance_to_arrival (index 2) is the distance from route[i-1] -> route[i]
        pv = self._route_distance_to_arrival_at(self.offset)
        if pv is not None:
            self.dist_prev = f"{'Distance (Ly)' if use_spansh_distance_labels else 'Jump LY'}: {fmt_num(pv)}"
        else:
            pj = self._route_progress_value_at(self.offset, None)
            if pj is not None:
                self.dist_prev = f"Number of Jumps: {fmt_num(pj)}"
            else:
                self.dist_prev = "Start of the journey"

        # --- LY to next ---
        if self.offset < len(self.route) - 1:
            nv = self._route_distance_to_arrival_at(self.offset + 1)
            if nv is not None:
                next_label = "Next Distance (Ly)" if use_spansh_distance_labels else "Next jump LY"
                self.dist_next = f"{next_label}: {fmt_num(nv)}"
            else:
                nv2 = self._route_progress_value_at(self.offset + 1, None)
                if nv2 is not None:
                    self.dist_next = f"Next waypoint jumps: {fmt_num(nv2)}"
        else:
            self.dist_next = ""

        # --- Total remaining ---
        total_rem = self._route_remaining_distance_at(self.offset)

        if total_rem is None:
            total = 0.0
            ok = True
            for index in range(self.offset + 1, len(self.route)):
                v = self._route_distance_to_arrival_at(index)
                if v is None:
                    ok = False
                    break
                total += v
            if ok:
                total_rem = total

        if total_rem is not None:
            remaining_label = "Remaining (Ly)" if use_spansh_distance_labels else "LY afterwards"
            self.dist_remaining = f"{remaining_label}: {fmt_num(total_rem)}"
        else:
            s = 0.0
            ok = True
            for index in range(self.offset + 1, len(self.route)):
                v = self._route_progress_value_at(index, None)
                if v is None:
                    ok = False
                    break
                s += v
            if ok and s > 0:
                self.dist_remaining = f"Remaining jumps afterwards: {fmt_num(s)}"
            else:
                self.dist_remaining = ""

    def _advance_route_state(self, direction=1):
        if len(self.route) == 0:
            self.next_stop = "No route planned"
            return {
                "has_route": False,
                "copy_waypoint": False,
                "update_overlay": False,
            }

        if direction > 0 and not getattr(self, "_manual_nav", False) and self._route_complete_for_ui():
            self._waypoint_reached = False
            self._waypoint_reached_restock = False
            return {
                "has_route": True,
                "copy_waypoint": False,
                "update_overlay": False,
            }

        reached_restock = False
        reached_waypoint = direction > 0 and not getattr(self, "_manual_nav", False)
        previous_offset = self.offset if hasattr(self, "offset") and self.offset is not None else 0

        if not hasattr(self, "offset") or self.offset is None:
            self.offset = 0
        if self.offset < 0:
            self.offset = 0
        if self.offset >= len(self.route):
            self.offset = len(self.route) - 1

        try:
            if self.fleetcarrier:
                if direction > 0:
                    self.offset = self._route_visible_next_index(self.offset)
                else:
                    self.offset = self._route_visible_prev_index(self.offset)
                self.jumps_left = self._route_progress_value_at(self.offset, 0) or 0
            elif direction > 0:
                self.jumps_left -= self._route_progress_value_at(self.offset, 0) or 0
                if self.offset < len(self.route) - 1:
                    self.offset += 1
            elif self.offset > 0:
                self.offset -= 1
                self.jumps_left += self._route_progress_value_at(self.offset, 0) or 0
        except Exception:
            self._log_unexpected("Failed to advance route state")
            self.offset = max(0, min(self.offset, len(self.route) - 1))

        if self.offset >= len(self.route):
            self.next_stop = "End of the road!"
            return {
                "has_route": True,
                "copy_waypoint": False,
                "update_overlay": False,
            }

        if reached_waypoint:
            self._mark_waypoint_done(previous_offset)

        self.next_stop = self._route_name_at(self.offset, "")
        self.compute_distances()
        self.pleaserefuel = self._route_refuel_required_at(self.offset)

        if self.fleetcarrier:
            reached_waypoint = reached_waypoint and self._fleet_group_is_waypoint(self.offset)
            reached_restock = reached_waypoint and self._fleet_group_has_restock(self.offset)

        self._waypoint_reached = reached_waypoint
        self._waypoint_reached_restock = reached_restock
        return {
            "has_route": True,
            "copy_waypoint": True,
            "update_overlay": bool(self.exact_plotter or self.galaxy or self._is_neutron_route_active()),
        }

    def _apply_route_ui_side_effects(self, state, *, refresh_viewer=True):
        self.update_gui()
        if state.get("copy_waypoint"):
            self.copy_waypoint()
        if state.get("update_overlay"):
            self._update_overlay()
        if refresh_viewer:
            self._refresh_csv_viewer_if_open()
        self.save_all_route()

    def update_route(self, direction=1, *, refresh_viewer=True):
        state = self._advance_route_state(direction)
        self._apply_route_ui_side_effects(state, refresh_viewer=refresh_viewer)


    def clear_route(self, show_dialog=True):
        clear = confirmDialog.askyesno("SpanshTools","Are you sure you want to clear the current route?") if show_dialog else True

        if clear:
            if self.csv_viewer_win:
                try:
                    self.csv_viewer_win.destroy()
                except Exception:
                    pass
                self._close_csv_viewer()
            self._close_plotter_window()
            self._close_exact_window()
            self._clear_overlay()
            self._clear_neutron_overlay()
            self.offset = 0
            self.route = []
            self._invalidate_route_rows()
            self.route_done = []
            self.jumps_left = 0
            self.route_type = None
            self.fleetcarrier = False
            self.galaxy = False
            self.exact_plotter = False
            self.exact_route_data = []
            self.fleet_carrier_data = []
            self._reset_exploration_state()
            self._clear_plotter_settings()
            try:
                os.remove(self.save_route_path)
            except Exception:
                logger.info("No route to delete")
            try:
                os.remove(self.offset_file_path)
            except Exception:
                logger.info("No offset file to delete")
            try:
                os.remove(self._route_state_path())
            except Exception:
                logger.info("No route state file to delete")
            try:
                os.remove(self.exact_settings_path)
            except Exception:
                pass
            self._exact_settings = None

            self.update_gui()

    def process_loadout(self, entry):
        """Extract FSD parameters from a Loadout journal event."""
        from .fsd_data import get_fsd_specs, GUARDIAN_FSD_BOOSTS

        modules = entry.get('Modules', [])
        fsd_module = None
        for mod in modules:
            if mod.get('Slot') == 'FrameShiftDrive':
                fsd_module = mod
                break

        if not fsd_module:
            return

        item_name = fsd_module.get('Item', '')
        specs = get_fsd_specs(item_name)
        if not specs:
            return

        fsd_class = specs['class']
        fsd_rating = specs['rating']

        # Start with base specs
        fsd_data = dict(specs)

        # Apply engineering overrides if present
        engineering = fsd_module.get('Engineering', {})
        modifiers = engineering.get('Modifiers', [])
        for modifier in modifiers:
            label = modifier.get('Label', '')
            value = modifier.get('Value')
            if value is None:
                continue
            if label == 'FSDOptimalMass':
                fsd_data['optimal_mass'] = float(value)
            elif label == 'MaxFuelPerJump':
                fsd_data['max_fuel_per_jump'] = float(value)

        # Ship-level data
        fuel_capacity = entry.get('FuelCapacity', {})
        fsd_data['tank_size'] = fuel_capacity.get('Main', 16)
        fsd_data['reserve_size'] = fuel_capacity.get('Reserve', 0.63)
        fsd_data['unladen_mass'] = entry.get('UnladenMass', 0)
        fsd_data['cargo_capacity'] = entry.get('CargoCapacity', 0)

        # Guardian FSD Booster detection
        range_boost = 0.0
        for mod in modules:
            item = mod.get('Item', '').lower()
            if 'fsdbooster' in item or 'fsd_booster' in item:
                match = re.search(r'size(\d+)', item)
                if match:
                    size = int(match.group(1))
                    range_boost = GUARDIAN_FSD_BOOSTS.get(size, 0.0)
        fsd_data['range_boost'] = range_boost

        self.ship_fsd_data = fsd_data
        logger.info(f"FSD data detected: class {fsd_class}{fsd_rating}, "
                     f"optimal_mass={fsd_data['optimal_mass']}, "
                     f"max_fuel={fsd_data['max_fuel_per_jump']}, "
                     f"tank={fsd_data['tank_size']}, "
                     f"boost={range_boost}")

    def try_fsd_from_state(self, state):
        """Fallback: extract FSD data from EDMC's state dict if Loadout wasn't received."""
        if self.ship_fsd_data is not None:
            return
        if not state:
            return
        self._detect_fsd_from_state(state)

    def _detect_fsd_from_monitor(self):
        """Pull FSD data directly from EDMC's monitor.state."""
        try:
            self._detect_fsd_from_state(monitor.state)
        except Exception as e:
            logger.debug(f"Could not detect FSD from monitor: {e}")

    def _detect_fsd_from_state(self, state):
        """Extract FSD data from an EDMC state dict (monitor.state or journal_entry state)."""
        if not state:
            return
        modules = state.get('Modules')
        if not modules:
            return
        try:
            # EDMC state['Modules'] is a dict keyed by slot name
            if isinstance(modules, dict):
                module_list = []
                for slot_name, module in modules.items():
                    if isinstance(module, dict):
                        enriched = dict(module)
                        enriched.setdefault("Slot", slot_name)
                        module_list.append(enriched)
                    else:
                        module_list.append(module)
            else:
                module_list = list(modules)

            # Build FuelCapacity — state may store it as a number or as a dict
            fuel_cap = state.get('FuelCapacity', 16)
            if isinstance(fuel_cap, dict):
                fuel_main = fuel_cap.get('Main', 16)
                fuel_reserve = fuel_cap.get('Reserve', 0.63)
            else:
                fuel_main = fuel_cap if fuel_cap else 16
                fuel_reserve = 0.63

            synthetic = {
                'event': 'Loadout',
                'Modules': module_list,
                'FuelCapacity': {
                    'Main': fuel_main,
                    'Reserve': fuel_reserve,
                },
                'UnladenMass': state.get('UnladenMass', 0),
                'CargoCapacity': state.get('CargoCapacity', 0),
            }
            self.process_loadout(synthetic)
        except Exception as e:
            logger.debug(f"Could not extract FSD from state: {e}")

    def has_staged_update(self):
        return bool(self.spansh_updater and self.spansh_updater.is_staged())

    def _stage_update_async(self):
        if not self.spansh_updater or self._staging_update or self.has_staged_update():
            return

        def worker():
            self._staging_update = True
            try:
                if self.spansh_updater.stage():
                    logger.info("SpanshTools update staged successfully")
            except Exception:
                self._log_unexpected("Failed to stage update")
            finally:
                self._staging_update = False

        threading.Thread(target=worker, daemon=True).start()

    def install_staged_update(self):
        if not self.spansh_updater or not self.has_staged_update():
            return False
        return bool(self.spansh_updater.install_staged())

    def check_for_update(self):
        """Check GitHub for a newer release. Runs in a background thread."""
        def _check():
            try:
                if self.update_available or self.has_staged_update():
                    return
                result = SpanshUpdater.check_latest()
                if result:
                    version, download_url, changelog = result
                    if SpanshUpdater.is_newer_version(version, self.plugin_version):
                        self.spansh_updater = SpanshUpdater(version, download_url, changelog, self.plugin_dir)
                        # Don't set update_available here — only set when user accepts in popup
                        # Show update button on main thread
                        if self.frame:
                            self._ui_call(self._show_update_button)
                        return
                    SpanshUpdater.sync_repo_fsd_specs(self.plugin_dir)
            except Exception:
                self._log_unexpected("Failed to check for updates")

        threading.Thread(target=_check, daemon=True).start()

    def _show_update_button(self):
        """Show the update warning button next to the title."""
        if not self._update_btn_visible:
            self.update_btn.pack(side=tk.RIGHT, padx=(5, 0))
            self._update_btn_visible = True

    def _show_update_popup(self):
        """Show a popup with update info and install option."""
        if not self.spansh_updater:
            return

        win = tk.Toplevel(self.parent)
        win.title("SpanshTools Update")
        win.resizable(False, False)
        win.minsize(350, 0)

        # Position near the mouse pointer
        x = self.parent.winfo_pointerx() + 15
        y = self.parent.winfo_pointery() + 10
        win.geometry(f"+{x}+{y}")

        tk.Label(win, text="Update Available!", font=("", 11, "bold")).pack(padx=10, pady=(10, 5))
        tk.Label(win, text=f"Current: v{self.plugin_version}  \u2192  New: v{self.spansh_updater.version}",
                 font=("", 9)).pack(padx=10, pady=2)

        if self.spansh_updater.changelog:
            tk.Label(win, text="Changelog:", font=("", 9, "bold"), anchor=tk.W).pack(
                padx=10, pady=(10, 2), fill=tk.X)
            changelog_text = tk.Text(win, wrap=tk.WORD, height=10, width=45, font=("", 9))
            changelog_text.insert(tk.END, self.spansh_updater.changelog)
            changelog_text.config(state=tk.DISABLED)
            changelog_text.pack(padx=10, pady=2)

        tk.Label(win, text="The update will install on quit after staging finishes.",
                 font=("", 8), fg="gray").pack(padx=10, pady=(5, 2))

        btn_frame = tk.Frame(win)
        btn_frame.pack(padx=10, pady=10)

        def _accept():
            self.update_available = True
            self._stage_update_async()
            win.destroy()

        def _dismiss():
            self.update_available = False
            win.destroy()

        tk.Button(btn_frame, text="Install on Quit", command=_accept, width=14).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Skip", command=_dismiss, width=10).pack(side=tk.LEFT, padx=5)

    def install_update(self):
        """Backward-compatible entry point; only installs already-staged updates."""
        if self.spansh_updater and self.update_available:
            return self.install_staged_update()
        return False
