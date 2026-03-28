"""Plotter window mixins — neutron, exact/galaxy, exploration, fleet carrier."""

import json
import threading
import tkinter as tk
from time import sleep

import requests
from monitor import monitor

from .AutoCompleter import AutoCompleter
from .PlaceHolder import PlaceHolder
from .constants import (
    SPANSH_POLL_INTERVAL,
    SPANSH_POLL_MAX_ITERATIONS,
    _SpanshPollError,
    _SpanshPollTimeout,
    logger,
)
from .widgets import DraggableListWidget, Tooltip


class PlottersMixin:
    """Mixin providing all plotter window methods for SpanshTools."""

    def _spansh_request_headers(self):
        return {"User-Agent": "EDMC_SpanshTools 1.0"}


    def _set_plot_running_state(self, *, active, exact=False, use_enable_plot_gui=False, button=None):
        if active:
            self._mark_plot_started(exact=exact)
        else:
            self._mark_plot_stopped(exact=exact)

        if use_enable_plot_gui:
            self.enable_plot_gui(not active)
        else:
            self._set_main_controls_enabled(not active)
            self._set_plotter_windows_enabled(not active)

        if button is not None:
            try:
                button.config(
                    state=tk.DISABLED if active else tk.NORMAL,
                    text="Computing..." if active else "Calculate",
                )
            except (tk.TclError, AttributeError):
                pass


    def _spansh_response_json(self, response, default=None):
        try:
            return response.json()
        except ValueError:
            return {} if default is None else default


    def _spansh_error_message(self, response, default):
        payload = self._spansh_response_json(response, default={})
        if isinstance(payload, dict):
            error_text = payload.get("error")
            if error_text:
                return error_text
        text = getattr(response, "text", "") or ""
        return text or default


    def _has_spansh_direct_result(self, payload, direct_result_keys=()):
        if isinstance(payload, list):
            return True
        if not isinstance(payload, dict):
            return False
        if any(key in payload for key in direct_result_keys):
            return True
        nested = payload.get("result")
        return isinstance(nested, dict) and any(key in nested for key in direct_result_keys)


    def _submit_spansh_job_request(
        self,
        api_url,
        *,
        params=None,
        data=None,
        timeout=15,
        cancel_attr="_plot_cancelled",
        results_base="https://spansh.co.uk/api/results",
        accept_direct_result=False,
        direct_result_keys=(),
    ):
        response = requests.post(
            api_url,
            params=params,
            data=data,
            headers=self._spansh_request_headers(),
            timeout=timeout,
        )

        if response.status_code == 400:
            raise _SpanshPollError(
                self._spansh_error_message(response, "Invalid request"),
                status_code=400,
            )

        if response.status_code not in (200, 202):
            raise _SpanshPollError(
                self._spansh_error_message(response, f"API error: {response.status_code}"),
                status_code=response.status_code,
            )

        result = self._spansh_response_json(response, default={})
        if accept_direct_result and self._has_spansh_direct_result(result, direct_result_keys):
            return result

        job = result.get("job") if isinstance(result, dict) else None
        if not job:
            raise _SpanshPollError("No job ID returned")

        return self._poll_spansh_job(
            job,
            poll_interval=SPANSH_POLL_INTERVAL,
            max_iterations=SPANSH_POLL_MAX_ITERATIONS,
            cancel_attr=cancel_attr,
            results_base=results_base,
        )


    def _reset_for_new_route(self):
        self._close_csv_viewer_if_open()
        self.clear_route(show_dialog=False)


    def _finalize_applied_route(self, *, close_exact=False, update_overlay=False):
        if close_exact:
            self._close_exact_window()
        else:
            self._close_plotter_window()
        self.compute_distances()
        self.copy_waypoint()
        self.update_gui()
        if update_overlay:
            self._update_overlay()
        self.save_all_route()


    def _refresh_draggable_rows(self, list_widget, items, build_row):
        if not list_widget or not hasattr(list_widget, "inner"):
            return
        row_widgets = []
        for child in list_widget.inner.winfo_children():
            child.destroy()
        highlight_bg = "#dce6f2"
        normal_bg = list_widget.inner.cget("bg")
        for index, item in enumerate(items):
            is_selected = index == list_widget.selected_index
            row_bg = highlight_bg if is_selected else normal_bg
            row_frame = tk.Frame(list_widget.inner, bg=row_bg)
            row_frame.grid(row=index, column=0, sticky=tk.EW, padx=(4, 0), pady=2)
            row_widgets.append(row_frame)
            build_row(index, item, row_frame, row_bg)
        list_widget.refresh_layout(row_widgets)

    def _update_algo_tooltip(self):
        """Update the algorithm dropdown tooltip based on current selection."""
        algo = self.exact_algorithm.get()
        self._algo_sel_tooltip.text = self._algo_descriptions.get(algo, "")


    def show_exact_plotter(self):
        """Open the exact plotter configuration window."""
        if self._is_plotting():
            return
        if not self._prepare_window_kind("Galaxy Plotter"):
            return
        self.exact_win = tk.Toplevel(self.parent)
        self.exact_win.title("Spansh Exact Plotter")
        self.exact_win.resizable(False, False)
        self.exact_win.minsize(300, 0)
        self.exact_win.protocol("WM_DELETE_WINDOW", self._close_exact_window)

        row = 0

        # Source System
        tk.Label(self.exact_win, text="Source System:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        row += 1
        self.exact_source_ac = AutoCompleter(self.exact_win, "Source System", width=30)
        self.exact_source_ac.grid(row=row, columnspan=2, padx=5, pady=2, sticky=tk.EW)
        # Pre-fill source: saved settings if available, otherwise current system
        if self._exact_settings and self._exact_settings.get("source"):
            self.exact_source_ac.set_text(self._exact_settings["source"], False)
        else:
            current_sys = monitor.state.get('SystemName')
            if current_sys:
                self.exact_source_ac.set_text(current_sys, False)
        row += 2  # AutoCompleter needs 2 rows for suggestion list

        # Destination System
        tk.Label(self.exact_win, text="Destination System:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        row += 1
        self.exact_dest_ac = AutoCompleter(self.exact_win, "Destination System", width=30)
        self.exact_dest_ac.grid(row=row, columnspan=2, padx=5, pady=2, sticky=tk.EW)
        if self._exact_settings and self._exact_settings.get("destination"):
            self.exact_dest_ac.set_text(self._exact_settings["destination"], False)
        row += 2

        # Cargo — label left, spinbox right-aligned to match AutoCompleter right edge
        cargo_frame = tk.Frame(self.exact_win)
        cargo_frame.grid(row=row, columnspan=2, sticky=tk.EW, padx=5, pady=2)
        tk.Label(cargo_frame, text="Cargo:").pack(side=tk.LEFT)
        self.exact_cargo_entry = tk.Spinbox(cargo_frame, from_=0, to=9999, width=7,
                                            validate="key")
        self.exact_cargo_entry.configure(validatecommand=self._spinbox_validator(self.exact_cargo_entry))
        self._bind_live_spinbox_clamp(self.exact_cargo_entry, integer=True)
        self.exact_cargo_entry.pack(side=tk.RIGHT, padx=(0, 2))
        if self._exact_settings and self._exact_settings.get("cargo"):
            self.exact_cargo_entry.delete(0, tk.END)
            self.exact_cargo_entry.insert(0, self._exact_settings["cargo"])
        row += 1

        # Reserve Fuel — same layout
        reserve_frame = tk.Frame(self.exact_win)
        reserve_frame.grid(row=row, columnspan=2, sticky=tk.EW, padx=5, pady=2)
        tk.Label(reserve_frame, text="Reserve Fuel (t):").pack(side=tk.LEFT)
        reserve_help = tk.Label(
            reserve_frame,
            text="?",
            font=("", 8),
            fg="blue",
            cursor="question_arrow",
            relief=tk.RAISED,
            borderwidth=1,
            padx=2,
        )
        reserve_help.pack(side=tk.LEFT, padx=(4, 0))
        Tooltip(
            reserve_help,
            "Reserve an amount of fuel that the router will not use for jumping",
        )
        self.exact_reserve_entry = tk.Spinbox(reserve_frame, from_=0, to=32, width=7,
                                              validate="key", increment=1)
        self.exact_reserve_entry.configure(
            validatecommand=self._spinbox_validator(
                self.exact_reserve_entry,
                allow_float=True,
                maximum_decimals=2,
            )
        )
        self._bind_live_spinbox_clamp(self.exact_reserve_entry)
        self.exact_reserve_entry.pack(side=tk.RIGHT, padx=(0, 2))
        if self._exact_settings and self._exact_settings.get("reserve"):
            self.exact_reserve_entry.delete(0, tk.END)
            self.exact_reserve_entry.insert(0, self._exact_settings["reserve"])
        row += 1

        # Checkboxes — restore from saved settings if available
        s = self._exact_settings or {}
        # Already Supercharged: auto-detect from JetConeBoost, fallback to saved settings
        supercharged_default = self.is_supercharged or s.get("is_supercharged", False)
        self.exact_is_supercharged = tk.BooleanVar(value=supercharged_default)
        self.exact_use_supercharge = tk.BooleanVar(value=s.get("use_supercharge", True))
        self.exact_use_injections = tk.BooleanVar(value=s.get("use_injections", False))
        self.exact_exclude_secondary = tk.BooleanVar(value=s.get("exclude_secondary", False))
        self.exact_refuel_scoopable = tk.BooleanVar(value=s.get("refuel_scoopable", True))

        def _cb_row(parent, text, variable, tooltip, row):
            """Create a checkbox + '?' icon in a frame, spanning both columns."""
            f = tk.Frame(parent)
            f.grid(row=row, columnspan=2, sticky=tk.W, padx=5)
            tk.Checkbutton(f, text=text, variable=variable).pack(side=tk.LEFT)
            lbl = tk.Label(f, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                           relief=tk.RAISED, borderwidth=1, padx=2)
            lbl.pack(side=tk.LEFT, padx=(4, 0))
            Tooltip(lbl, tooltip)

        _cb_row(self.exact_win, "Already Supercharged", self.exact_is_supercharged,
                "Is your ship already supercharged?", row)
        row += 1
        _cb_row(self.exact_win, "Use Supercharge", self.exact_use_supercharge,
                "Use neutron stars to supercharge your FSD.", row)
        row += 1
        _cb_row(self.exact_win, "Use FSD Injections", self.exact_use_injections,
                "Use FSD synthesis to boost when a neutron star is not available.", row)
        row += 1
        _cb_row(self.exact_win, "Exclude Secondary Stars", self.exact_exclude_secondary,
                "Prevent using secondary neutron and scoopable stars to help with the route.", row)
        row += 1
        _cb_row(self.exact_win, "Refuel Every Scoopable", self.exact_refuel_scoopable,
                "Refuel every time you encounter a scoopable star.", row)
        row += 1

        # Routing Algorithm
        algo_frame = tk.Frame(self.exact_win)
        algo_frame.grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        tk.Label(algo_frame, text="Routing Algorithm:").pack(side=tk.LEFT)
        algo_help = tk.Label(algo_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                             relief=tk.RAISED, borderwidth=1, padx=2)
        algo_help.pack(side=tk.LEFT, padx=(4, 0))
        Tooltip(algo_help, "Which routing algorithm to use. Different algorithms may work faster, find better routes, or in some cases be unable to find a route.")

        self.exact_algorithm = tk.StringVar(value=s["algorithm"] if s else "optimistic")
        algorithms = ["fuel", "fuel_jumps", "guided", "optimistic", "pessimistic"]
        algo_sel_frame = tk.Frame(self.exact_win)
        algo_sel_frame.grid(row=row, column=1, padx=5, pady=2, sticky=tk.W)
        self.exact_algo_menu = tk.OptionMenu(algo_sel_frame, self.exact_algorithm, *algorithms)
        self.exact_algo_menu.config(width=12)
        self.exact_algo_menu.pack(side=tk.LEFT)
        algo_sel_help = tk.Label(algo_sel_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                                 relief=tk.RAISED, borderwidth=1, padx=2)
        algo_sel_help.pack(side=tk.LEFT, padx=(4, 0))

        # Dynamic tooltip on algorithm '?' based on selection
        self._algo_descriptions = {
            "fuel": "Prioritises saving fuel, will not scoop or supercharge. Makes the smallest jumps possible to preserve fuel.",
            "fuel_jumps": "Prioritises saving fuel with minimised jumps. Attempts to use the entire fuel tank efficiently. May run out of fuel on very long routes.",
            "guided": "Follows a standard Neutron Plotter route as a guide. Penalises routes that diverge more than 100 LY. May time out in sparse regions.",
            "optimistic": "Prioritises neutron jumps. Penalises areas with large gaps between neutron stars. Typically the fastest route with fewest total jumps.",
            "pessimistic": "Prioritises calculation speed. Overestimates average star distance. Calculates faster but routes are typically less optimal.",
        }
        self._algo_sel_tooltip = Tooltip(algo_sel_help, self._algo_descriptions.get(self.exact_algorithm.get(), ""))
        self.exact_algorithm.trace_add("write", lambda *_: self._update_algo_tooltip())
        row += 1

        # Try to detect FSD from EDMC state if not yet detected
        if not self.ship_fsd_data:
            self._detect_fsd_from_monitor()

        # Ship status indicator — show ship name from monitor
        if self.ship_fsd_data:
            ship_name = monitor.state.get('ShipName', '') or monitor.state.get('ShipType', '')
            if ship_name:
                ship_status = f"Ship: {ship_name}"
            else:
                ship_status = "FSD detected"
            ship_color = "green"
        else:
            ship_status = "No FSD data — enter game or switch ship to detect"
            ship_color = "orange"
        self.exact_fsd_status_lbl = tk.Label(self.exact_win, text=ship_status, fg=ship_color)
        self.exact_fsd_status_lbl.grid(row=row, columnspan=2, padx=5, pady=5)
        row += 1

        # Buttons
        self.exact_calculate_btn = tk.Button(self.exact_win, text="Calculate", command=self.plot_exact_route)
        self.exact_calculate_btn.grid(row=row, column=0, padx=5, pady=10)
        tk.Button(self.exact_win, text="Cancel", command=self._cancel_exact_plot).grid(
            row=row, column=1, padx=5, pady=10)
        row += 1

        # Error label
        self.exact_error_txt = tk.StringVar()
        self.exact_error_lbl = tk.Label(self.exact_win, textvariable=self.exact_error_txt, fg="red", wraplength=300)
        self.exact_error_lbl.grid(row=row, columnspan=2, padx=5)
        self._configure_child_window(self.exact_win)


    def _close_plotter_window(self):
        if self._is_plotting():
            self._mark_plot_stopped(cancelled=True)
            self._invalidate_plot_token()
            self._set_main_controls_enabled(True)
            self._set_plotter_windows_enabled(True)
        if self.plotter_win:
            try:
                self.plotter_win.destroy()
            except tk.TclError:
                pass
            self.plotter_win = None
        self._plotter_window_kind = None


    def _close_exact_window(self):
        if self._is_plotting():
            self._mark_plot_stopped(cancelled=True, exact=True)
            self._invalidate_plot_token()
            self._set_main_controls_enabled(True)
            self._set_plotter_windows_enabled(True)
        if self.exact_win:
            try:
                self.exact_win.destroy()
            except tk.TclError:
                pass
            self.exact_win = None
        if self._plotter_window_kind == "Galaxy Plotter":
            self._plotter_window_kind = None


    def _prepare_window_kind(self, kind):
        if kind == "Galaxy Plotter":
            if self.plotter_win:
                self._close_plotter_window()
            if self.exact_win:
                try:
                    if self._plotter_window_kind == kind and self.exact_win.winfo_exists():
                        self._raise_child_window(self.exact_win)
                        return False
                except tk.TclError:
                    self.exact_win = None
                if self.exact_win:
                    self._close_exact_window()
            self._plotter_window_kind = kind
            return True

        if self.exact_win:
            self._close_exact_window()

        if self.plotter_win:
            try:
                if self.plotter_win.winfo_exists():
                    if self._plotter_window_kind == kind:
                        self._raise_child_window(self.plotter_win)
                        return False
                    self._close_plotter_window()
            except tk.TclError:
                self.plotter_win = None

        self._plotter_window_kind = kind
        return True


    def _label_with_help(self, parent, text, help_text, row, *, pady=(0, 2)):
        frame = tk.Frame(parent)
        frame.grid(row=row, column=0, sticky=tk.W, pady=pady)
        tk.Label(frame, text=text).pack(side=tk.LEFT)
        if help_text:
            help_lbl = tk.Label(
                frame,
                text="?",
                font=("", 8),
                fg="blue",
                cursor="question_arrow",
                relief=tk.RAISED,
                borderwidth=1,
                padx=2,
            )
            help_lbl.pack(side=tk.LEFT, padx=(4, 0))
            Tooltip(help_lbl, help_text)
        return frame


    def _checkbox_with_help(self, parent, text, variable, help_text, row, *, columnspan=1):
        frame = tk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=columnspan, sticky=tk.W, pady=2)
        tk.Checkbutton(frame, text=text, variable=variable).pack(side=tk.LEFT)
        if help_text:
            help_lbl = tk.Label(
                frame,
                text="?",
                font=("", 8),
                fg="blue",
                cursor="question_arrow",
                relief=tk.RAISED,
                borderwidth=1,
                padx=2,
            )
            help_lbl.pack(side=tk.LEFT, padx=(4, 0))
            Tooltip(help_lbl, help_text)
        return frame


    def _suggest_jump_range(self):
        if not self.ship_fsd_data:
            self._detect_fsd_from_monitor()

        fsd = self.ship_fsd_data or {}
        optimal_mass = self._safe_float(fsd.get("optimal_mass"), 0)
        max_fuel_per_jump = self._safe_float(fsd.get("max_fuel_per_jump"), 0)
        fuel_multiplier = self._safe_float(fsd.get("fuel_multiplier"), 0)
        fuel_power = self._safe_float(fsd.get("fuel_power"), 0)
        fuel_main = self._safe_float(self.current_fuel_main, None)
        fuel_reservoir = self._safe_float(getattr(self, "current_fuel_reservoir", None), 0.0)
        fuel_mass = None
        if fuel_main is not None and fuel_main >= 0:
            fuel_mass = fuel_main + max(fuel_reservoir or 0.0, 0.0)
        if fuel_mass is None or fuel_mass <= 0:
            fuel_mass = self._safe_float(fsd.get("tank_size"), 0)
        if fuel_mass <= 0:
            return None
        base_mass = self._safe_float(fsd.get("unladen_mass"), 0) + fuel_mass
        range_boost = self._safe_float(fsd.get("range_boost"), 0)

        if optimal_mass > 0 and max_fuel_per_jump > 0 and fuel_multiplier > 0 and fuel_power > 0 and base_mass > 0:
            try:
                jump_range = (optimal_mass / base_mass) * ((max_fuel_per_jump / fuel_multiplier) ** (1 / fuel_power))
                return round(jump_range + range_boost, 2)
            except Exception:
                return None
        return None


    def _prefill_range_entry(self, widget, value=None, *, integer=False):
        if value in (None, "", []):
            value = self._suggest_jump_range()
        if value in (None, "", []):
            return
        if integer:
            text = str(int(round(float(value))))
        else:
            text = f"{float(value):.2f}"
        if isinstance(widget, PlaceHolder):
            widget.set_text(text, False)
        else:
            self._set_entry_value(widget, text)


    def run_search_action(self):
        if self.search_var.get() == "Find nearest system":
            self.show_nearest_finder()


    def show_plotter_window(self):
        """Open the unified plotter window based on the selected planner."""
        if self._is_plotting():
            return
        planner = self.planner_var.get()
        if planner == "Neutron Plotter":
            self._show_neutron_plotter_window()
        elif planner == "Galaxy Plotter":
            self.show_exact_plotter()
        elif planner == "Fleet Carrier Router":
            self._show_fleet_carrier_window()
        elif planner in ("Road to Riches", "Ammonia World Route", "Earth-like World Route",
                         "Rocky/HMC Route", "Exomastery"):
            self._show_exploration_plotter_window(planner)


    def _show_neutron_plotter_window(self):
        """Open the neutron plotter as a Toplevel window."""
        if self._is_plotting():
            return
        planner = "Neutron Plotter"
        if not self._prepare_window_kind(planner):
            return

        self.plotter_win = tk.Toplevel(self.parent)
        self.plotter_win.title("Spansh Neutron Plotter")
        self.plotter_win.resizable(False, False)
        self.plotter_win.minsize(330, 0)
        self.plotter_win.columnconfigure(0, weight=1)
        self.plotter_win.protocol("WM_DELETE_WINDOW", self._close_plotter_window)

        content = self.plotter_win

        settings = self._settings_for_planner(planner)
        self._neutron_vias = list(settings.get("vias", []))
        self._neutron_via_visible = bool(self._neutron_vias)

        row = 0

        # Source System
        self._label_with_help(content, "Source System:", "", row)
        row += 1
        self.source_ac = AutoCompleter(content, "Source System", width=34)
        self.source_ac.grid(row=row, column=0, padx=4, pady=(0, 6), sticky=tk.EW)
        current_sys = settings.get("source") or self._last_source_system or monitor.state.get('SystemName')
        if current_sys:
            self.source_ac.set_text(current_sys, False)
        row += 2

        via_btn_frame = tk.Frame(content)
        via_btn_frame.grid(row=row, column=0, sticky=tk.EW, padx=4, pady=(0, 6))
        via_btn_frame.columnconfigure(0, weight=1)
        via_btn_frame.columnconfigure(1, weight=1)
        neutron_via_btn_width = 14
        self._neutron_via_toggle_btn = tk.Button(
            via_btn_frame,
            text="Add Via",
            width=neutron_via_btn_width,
            command=self._toggle_neutron_via_visibility,
        )
        self._neutron_via_toggle_btn.grid(row=0, column=0, sticky=tk.EW, padx=(0, 4))
        tk.Button(
            via_btn_frame,
            text="Reverse Route",
            width=neutron_via_btn_width,
            command=self._reverse_neutron_route,
        ).grid(row=0, column=1, sticky=tk.EW, padx=(4, 0))
        row += 1

        self._neutron_via_frame = tk.Frame(content)
        self._neutron_via_frame.grid(row=row, column=0, sticky=tk.EW, padx=4, pady=(0, 8))
        self._neutron_via_frame.columnconfigure(0, weight=1)
        self._label_with_help(self._neutron_via_frame, "Add Via:", "", 0)
        self._neutron_via_ac = AutoCompleter(
            self._neutron_via_frame,
            "Via System",
            width=34,
            selected_items_provider=self._current_neutron_vias,
            on_select=lambda _value: self.plotter_win.after_idle(self._add_neutron_via),
        )
        self._neutron_via_ac.grid(row=1, column=0, padx=0, pady=(0, 6), sticky=tk.EW)
        self._neutron_via_ac.bind("<Return>", self._add_neutron_via_from_entry, add="+")
        self._neutron_via_ac.bind("<KP_Enter>", self._add_neutron_via_from_entry, add="+")
        tk.Frame(self._neutron_via_frame, height=1).grid(row=2, column=0, sticky=tk.EW)

        via_list_frame = tk.Frame(self._neutron_via_frame)
        via_list_frame.grid(row=3, column=0, sticky=tk.EW, pady=(2, 0))
        via_list_frame.columnconfigure(0, weight=1)
        self._neutron_via_list = DraggableListWidget(via_list_frame, height=164, visible_rows=6)
        self._neutron_via_list.border.grid(row=0, column=0, sticky=tk.EW)
        self._neutron_via_list.set_items(self._neutron_vias)
        self._neutron_via_list.on_reorder = self._refresh_neutron_vias
        self._neutron_via_list.on_select = self._select_neutron_via_line
        self._neutron_via_menu = tk.Menu(self.plotter_win, tearoff=0)
        self._neutron_via_menu.add_command(label="Copy name", command=self._copy_neutron_via_name)
        self._neutron_menu_via_name = ""
        self._refresh_neutron_vias()
        self._apply_neutron_via_visibility()
        row += 1

        # Destination System
        self._label_with_help(content, "Destination System:", "", row)
        row += 1
        self.dest_ac = AutoCompleter(content, "Destination System", width=34)
        self.dest_ac.grid(row=row, column=0, padx=4, pady=(0, 6), sticky=tk.EW)
        if settings.get("destination"):
            self.dest_ac.set_text(settings["destination"], False)
        row += 2

        # Range
        range_frame = tk.Frame(content)
        range_frame.grid(row=row, column=0, sticky=tk.EW, pady=2)
        tk.Label(range_frame, text="Range (LY):").pack(side=tk.LEFT)
        range_help = tk.Label(range_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                              relief=tk.RAISED, borderwidth=1, padx=2)
        range_help.pack(side=tk.LEFT, padx=(4, 0))
        Tooltip(
            range_help,
            "The range of your ship. Uses a current fuel-aware estimate; otherwise unladen value of current ship.",
        )
        self.range_entry = tk.Spinbox(
            range_frame,
            from_=0,
            to=100,
            increment=1,
            format="%.2f",
            width=10,
            validate="key",
        )
        self.range_entry.configure(
            validatecommand=self._spinbox_validator(
                self.range_entry,
                allow_float=True,
                maximum_decimals=2,
            )
        )
        self._bind_live_spinbox_clamp(self.range_entry)
        self.range_entry.delete(0, tk.END)
        self.range_entry.pack(side=tk.RIGHT, padx=(0, 2))
        self._prefill_range_entry(self.range_entry, settings.get("range"))
        row += 1

        supercharge_frame = tk.Frame(content)
        supercharge_frame.grid(row=row, column=0, pady=(4, 2))
        self.supercharge_multiplier.set(
            self._normalize_supercharge_multiplier(settings.get("supercharge_multiplier", 4))
        )
        tk.Radiobutton(
            supercharge_frame,
            text="Regular Supercharged (4x)",
            variable=self.supercharge_multiplier,
            value=4,
        ).pack(anchor=tk.W)
        tk.Radiobutton(
            supercharge_frame,
            text="Overcharged Supercharged (6x)",
            variable=self.supercharge_multiplier,
            value=6,
        ).pack(anchor=tk.W)
        row += 1

        # Efficiency slider
        efficiency_frame = tk.Frame(content)
        efficiency_frame.grid(row=row, column=0, sticky=tk.EW, padx=4, pady=(6, 4))
        efficiency_frame.columnconfigure(0, weight=1)
        efficiency_label_frame = tk.Frame(efficiency_frame)
        efficiency_label_frame.grid(row=0, column=0, sticky=tk.EW, pady=(0, 2))
        tk.Label(efficiency_label_frame, text="Efficiency (%)").pack(side=tk.LEFT)
        efficiency_help = tk.Label(
            efficiency_label_frame,
            text="?",
            font=("", 8),
            fg="blue",
            cursor="question_arrow",
            relief=tk.RAISED,
            borderwidth=1,
            padx=2,
        )
        efficiency_help.pack(side=tk.LEFT, padx=(4, 0))
        self.neutron_efficiency_var = tk.IntVar(
            value=max(0, min(100, self._safe_int(settings.get("efficiency"), 60)))
        )
        self.efficiency_entry = tk.Spinbox(
            efficiency_label_frame,
            from_=0,
            to=100,
            increment=1,
            width=10,
            textvariable=self.neutron_efficiency_var,
            validate="key",
        )
        self.efficiency_entry.configure(validatecommand=self._spinbox_validator(self.efficiency_entry))
        self._bind_live_spinbox_clamp(self.efficiency_entry, integer=True)
        self.efficiency_entry.pack(side=tk.RIGHT, padx=(0, 2))
        self.efficiency_slider = tk.Scale(
            efficiency_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            showvalue=False,
            variable=self.neutron_efficiency_var,
        )
        self.efficiency_slider.grid(row=1, column=0, sticky=tk.EW)
        Tooltip(
            efficiency_help,
            "Increase this to reduce how far off the direct route the system will plot to get to a neutron star (An efficiency of 100 will not deviate from the direct route in order to plot from A to B and will most likely break down the journey into 20000 LY blocks).",
        )
        row += 1

        # Buttons
        btn_frame = tk.Frame(content)
        btn_frame.grid(row=row, column=0, pady=(10, 0))
        tk.Button(btn_frame, text="Calculate", width=10, command=self.plot_route).pack(side=tk.LEFT, padx=(0, 7))
        tk.Button(btn_frame, text="Cancel", width=10, command=self._cancel_neutron_plot).pack(side=tk.LEFT, padx=(7, 0))
        row += 1

        # Error label
        self.neutron_error_txt = tk.StringVar()
        tk.Label(content, textvariable=self.neutron_error_txt, fg="red",
                 wraplength=340, justify=tk.CENTER).grid(row=row, column=0, pady=(10, 0))
        self._configure_child_window(self.plotter_win)


    def _current_neutron_vias(self):
        if not getattr(self, "_neutron_via_visible", False):
            return []
        return list(getattr(self, "_neutron_vias", []))


    def _apply_neutron_via_visibility(self):
        if not hasattr(self, "_neutron_via_frame"):
            return
        if self._neutron_via_visible:
            self._neutron_via_frame.grid()
            if hasattr(self, "_neutron_via_toggle_btn"):
                self._neutron_via_toggle_btn.configure(text="Hide Via")
        else:
            self._neutron_via_frame.grid_remove()
            if hasattr(self, "_neutron_via_toggle_btn"):
                self._neutron_via_toggle_btn.configure(text="Add Via")


    def _toggle_neutron_via_visibility(self):
        self._neutron_via_visible = not self._neutron_via_visible
        self._apply_neutron_via_visibility()


    def _add_neutron_via(self):
        if not self._neutron_via_visible:
            self._neutron_via_visible = True
            self._apply_neutron_via_visibility()
        via_name = self._neutron_via_ac.get().strip()
        if not via_name or via_name == self._neutron_via_ac.placeholder:
            return
        if via_name not in self._neutron_vias:
            self._neutron_vias.append(via_name)
            self._refresh_neutron_vias()
            self._select_neutron_via_line(len(self._neutron_vias) - 1)
        self._neutron_via_ac.set_text(self._neutron_via_ac.placeholder, True)


    def _add_neutron_via_from_entry(self, _event=None):
        via_name = self._neutron_via_ac.get().strip()
        if not via_name or via_name == self._neutron_via_ac.placeholder:
            return "break"
        self.neutron_error_txt.set("")
        self._resolve_system_record_async(
            via_name,
            on_success=self._neutron_via_resolved,
            on_not_found=lambda query: self.neutron_error_txt.set(
                f"Via system '{query}' not found in Spansh."
            ),
            on_error=lambda query, _exc: self.neutron_error_txt.set(
                f"Failed to look up '{query}'."
            ),
        )
        return "break"


    def _neutron_via_resolved(self, record_name):
        self._neutron_via_ac.set_text(record_name, False)
        self._add_neutron_via()


    def _delete_neutron_via(self, index):
        if index < 0 or index >= len(getattr(self, "_neutron_vias", [])):
            return
        del self._neutron_vias[index]
        if not self._neutron_vias:
            self._neutron_via_list.selected_index = None
        else:
            self._neutron_via_list.selected_index = min(index, len(self._neutron_vias) - 1)
        self._refresh_neutron_vias()


    def _reverse_neutron_route(self):
        if not getattr(self, "source_ac", None) or not getattr(self, "dest_ac", None):
            return
        source = self.source_ac.get().strip()
        destination = self.dest_ac.get().strip()
        vias = list(reversed(self._neutron_vias))
        self.source_ac.set_text(destination, False)
        self.dest_ac.set_text(source, False)
        self._neutron_vias = vias
        self._neutron_via_list.set_items(self._neutron_vias)
        self._neutron_via_list.selected_index = None
        if self._neutron_vias:
            self._neutron_via_visible = True
        self._refresh_neutron_vias()
        self._apply_neutron_via_visibility()


    def _show_neutron_via_menu(self, event, via_name):
        self._neutron_menu_via_name = via_name or ""
        try:
            self._neutron_via_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._neutron_via_menu.grab_release()


    def _copy_neutron_via_name(self):
        if self._neutron_menu_via_name:
            self._copy_to_clipboard(self._neutron_menu_via_name)


    def _refresh_neutron_vias(self):
        if not hasattr(self, "_neutron_via_list"):
            return
        dlw = self._neutron_via_list

        def build_row(index, name, row_frame, row_bg):
            row_frame.columnconfigure(1, weight=1)
            del_btn = tk.Button(
                row_frame,
                text="🗑",
                width=3,
                padx=1,
                pady=0,
                command=lambda i=index: self._delete_neutron_via(i),
            )
            del_btn.grid(row=0, column=0, padx=(2, 6), pady=1)
            label = tk.Label(
                row_frame,
                text=name,
                anchor=tk.W,
                bg=row_bg,
                fg="black",
                cursor="hand2",
            )
            label.grid(row=0, column=1, sticky=tk.EW, pady=1)
            label.bind("<Button-3>", lambda e, n=name: self._show_neutron_via_menu(e, n))
            right_btns = tk.Frame(row_frame, bg=row_bg)
            right_btns.grid(row=0, column=2, padx=(10, 0), pady=1, sticky=tk.E)
            tk.Button(
                right_btns,
                text="▲",
                width=2,
                padx=0,
                pady=0,
                command=lambda i=index: self._move_neutron_via_to(i, -1),
            ).pack(side=tk.LEFT, padx=(0, 4))
            tk.Button(
                right_btns,
                text="▼",
                width=2,
                padx=0,
                pady=0,
                command=lambda i=index: self._move_neutron_via_to(i, 1),
            ).pack(side=tk.LEFT)
            row_frame.bind("<Button-3>", lambda e, n=name: self._show_neutron_via_menu(e, n))
            for widget in (row_frame, label, right_btns):
                dlw.bind_row_events(widget, index)
            dlw.bind_scroll_events(del_btn)

        self._refresh_draggable_rows(dlw, self._neutron_vias, build_row)


    def _select_neutron_via_line(self, index):
        if not hasattr(self, "_neutron_via_list"):
            return
        self._neutron_via_list.select_line(index)


    def _move_neutron_via_to(self, index, direction):
        new_index = index + direction
        if not (0 <= new_index < len(self._neutron_vias)):
            return
        self._neutron_vias[index], self._neutron_vias[new_index] = (
            self._neutron_vias[new_index],
            self._neutron_vias[index],
        )
        self._neutron_via_list.selected_index = new_index
        self._refresh_neutron_vias()


    def _show_exploration_plotter_window(self, planner):
        """Open plotter window for Spansh exploration route types."""
        if self._is_plotting():
            return
        if not self._prepare_window_kind(planner):
            return

        self.plotter_win = tk.Toplevel(self.parent)
        self.plotter_win.title(f"Spansh {planner}")
        self.plotter_win.resizable(False, False)
        self.plotter_win.minsize(300, 0)
        self.plotter_win.columnconfigure(0, weight=1)
        self.plotter_win.columnconfigure(1, weight=0)
        self.plotter_win.protocol("WM_DELETE_WINDOW", self._close_plotter_window)

        content = self.plotter_win

        settings = self._settings_for_planner(planner)

        is_exobiology = planner == "Exomastery"
        is_riches = planner == "Road to Riches"
        default_radius = "25"
        default_max_distance = "1000000" if planner in ("Road to Riches", "Exomastery") else "50000"
        default_min_value = "10000000" if is_exobiology else "100000"

        row = 0

        self._label_with_help(content, "Source System:", "", row)
        row += 1
        self._exp_source_ac = AutoCompleter(content, "Source System", width=30)
        self._exp_source_ac.grid(row=row, column=0, columnspan=2, padx=5, pady=(0, 6), sticky=tk.EW)
        current_sys = settings.get("source") or self._last_source_system or monitor.state.get('SystemName')
        if current_sys:
            self._exp_source_ac.set_text(current_sys, False)
        row += 2

        self._label_with_help(content, "Destination System (optional):", "", row)
        row += 1
        self._exp_dest_ac = AutoCompleter(content, "Destination System", width=30)
        self._exp_dest_ac.grid(row=row, column=0, columnspan=2, padx=5, pady=(0, 6), sticky=tk.EW)
        if settings.get("destination"):
            self._exp_dest_ac.set_text(settings["destination"], False)
        row += 2

        range_frame = tk.Frame(content)
        range_frame.grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        tk.Label(range_frame, text="Jump Range (LY):").pack(side=tk.LEFT)
        range_help = tk.Label(range_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                              relief=tk.RAISED, borderwidth=1, padx=2)
        range_help.pack(side=tk.LEFT, padx=(4, 0))
        Tooltip(
            range_help,
            "The range of your ship. Uses a current fuel-aware estimate; otherwise unladen value of current ship.",
        )
        self._exp_range = tk.Spinbox(content, from_=0, to=100, increment=1, format="%.2f", width=10,
                                     validate="key")
        self._exp_range.configure(
            validatecommand=self._spinbox_validator(
                self._exp_range,
                allow_float=True,
                maximum_decimals=2,
            )
        )
        self._bind_live_spinbox_clamp(self._exp_range)
        self._exp_range.delete(0, tk.END)
        self._exp_range.grid(row=row, column=1, padx=(10, 5), pady=2, sticky=tk.E)
        self._prefill_range_entry(self._exp_range, settings.get("range"))
        row += 1

        radius_frame = tk.Frame(content)
        radius_frame.grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        tk.Label(radius_frame, text=("Radius (LY):" if is_exobiology else "Search Radius (LY):")).pack(side=tk.LEFT)
        radius_help = tk.Label(radius_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                               relief=tk.RAISED, borderwidth=1, padx=2)
        radius_help.pack(side=tk.LEFT, padx=(4, 0))
        Tooltip(
            radius_help,
            "This is the distance in LY around which the plotter will look for valuable worlds for you to visit. A value of 25 LY tends to give a nice balance for A to B routes keeping the number of jumps reasonably low whilst still giving a nice payout. For circular routes (leaving destination blank) you will probably want to increase this to 100-500 LY.",
        )
        self._exp_radius = tk.Spinbox(content, from_=1, to=1000, width=10,
                                      validate="key")
        self._exp_radius.configure(validatecommand=self._spinbox_validator(self._exp_radius))
        self._bind_live_spinbox_clamp(self._exp_radius, integer=True)
        self._exp_radius.delete(0, tk.END)
        self._exp_radius.insert(0, settings.get("radius", default_radius))
        self._exp_radius.grid(row=row, column=1, padx=(10, 5), pady=2, sticky=tk.E)
        row += 1

        max_frame = tk.Frame(content)
        max_frame.grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        tk.Label(max_frame, text="Max Systems:").pack(side=tk.LEFT)
        max_help = tk.Label(max_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                            relief=tk.RAISED, borderwidth=1, padx=2)
        max_help.pack(side=tk.LEFT, padx=(4, 0))
        Tooltip(max_help, "This is the maximum number of systems that the plotter will route you through; lower this for a shorter trip.")
        self._exp_max_results = tk.Spinbox(content, from_=1, to=2000, width=10,
                                           validate="key")
        self._exp_max_results.configure(validatecommand=self._spinbox_validator(self._exp_max_results))
        self._bind_live_spinbox_clamp(self._exp_max_results, integer=True)
        self._exp_max_results.delete(0, tk.END)
        self._exp_max_results.insert(0, settings.get("max_results", "100"))
        self._exp_max_results.grid(row=row, column=1, padx=(10, 5), pady=2, sticky=tk.E)
        row += 1

        max_distance_frame = tk.Frame(content)
        max_distance_frame.grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        tk.Label(max_distance_frame, text="Max Distance (Ls):").pack(side=tk.LEFT)
        max_distance_help = tk.Label(max_distance_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                                     relief=tk.RAISED, borderwidth=1, padx=2)
        max_distance_help.pack(side=tk.LEFT, padx=(4, 0))
        Tooltip(max_distance_help, "Maximum light-seconds from arrival star to the target body.")
        self._exp_max_distance = tk.Spinbox(content, from_=1, to=1000000, width=10,
                                            validate="key")
        self._exp_max_distance.configure(validatecommand=self._spinbox_validator(self._exp_max_distance))
        self._bind_live_spinbox_clamp(self._exp_max_distance, integer=True)
        self._exp_max_distance.delete(0, tk.END)
        self._exp_max_distance.insert(0, settings.get("max_distance", default_max_distance))
        self._exp_max_distance.grid(row=row, column=1, padx=(10, 5), pady=2, sticky=tk.E)
        row += 1

        if is_riches or is_exobiology:
            value_frame = tk.Frame(content)
            value_frame.grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
            min_label = "Min Landmark Value (Cr):" if is_exobiology else "Min Scan Value (Cr):"
            tk.Label(value_frame, text=min_label).pack(side=tk.LEFT)
            min_help = tk.Label(value_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                                relief=tk.RAISED, borderwidth=1, padx=2)
            min_help.pack(side=tk.LEFT, padx=(4, 0))
            Tooltip(min_help, "Minimum value threshold for bodies or exobiology landmarks to include.")
            min_value_max = 100000000 if is_exobiology else 1000000
            self._exp_min_value = tk.Spinbox(content, from_=0, to=min_value_max, width=10,
                                             validate="key")
            self._exp_min_value.configure(validatecommand=self._spinbox_validator(self._exp_min_value))
            self._bind_live_spinbox_clamp(self._exp_min_value, integer=True)
            self._exp_min_value.delete(0, tk.END)
            self._exp_min_value.insert(0, settings.get("min_value", default_min_value))
            self._exp_min_value.grid(row=row, column=1, padx=(10, 5), pady=2, sticky=tk.E)
            row += 1

        if is_riches:
            self._exp_use_mapping_var = tk.BooleanVar(value=settings.get("use_mapping_value", False))
            self._checkbox_with_help(
                content,
                "Use mapping value",
                self._exp_use_mapping_var,
                "Use the mapping value rather than the scan value.",
                row,
                columnspan=2,
            )
            row += 1
        else:
            self._exp_use_mapping_var = tk.BooleanVar(value=False)

        self._exp_avoid_thargoids_var = tk.BooleanVar(value=settings.get("avoid_thargoids", True))
        self._checkbox_with_help(
            content,
            "Avoid Thargoids",
            self._exp_avoid_thargoids_var,
            "Avoid systems that are at war with or controlled by the Thargoids.",
            row,
            columnspan=2,
        )
        row += 1

        self._exp_loop = tk.BooleanVar(value=settings.get("loop", True))
        self._checkbox_with_help(
            content,
            "Loop",
            self._exp_loop,
            "Force the route to return to the starting system. Only applies when there is no destination selected.",
            row,
            columnspan=2,
        )
        row += 1

        btn_frame = tk.Frame(content)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(10, 0))
        self._exp_calc_btn = tk.Button(btn_frame, text="Calculate", width=10,
                                        command=lambda: self._plot_exploration_route(planner))
        self._exp_calc_btn.pack(side=tk.LEFT, padx=(0, 7))
        tk.Button(btn_frame, text="Cancel", width=10,
                  command=self._cancel_exploration_plot).pack(side=tk.LEFT, padx=(7, 0))
        row += 1

        self._exp_error_txt = tk.StringVar()
        tk.Label(content, textvariable=self._exp_error_txt, fg="red",
                 wraplength=340, justify=tk.CENTER).grid(row=row, column=0, columnspan=2, pady=(10, 0))
        self._configure_child_window(self.plotter_win)


    def _cancel_exploration_plot(self):
        """Cancel exploration plotter."""
        if self._is_plotting():
            self._mark_plot_stopped(cancelled=True)
            self._invalidate_plot_token()
            self._set_main_controls_enabled(True)
            self._set_plotter_windows_enabled(True)
        self._close_plotter_window()


    def _current_exploration_settings(self, planner, source, dest, range_ly, radius, max_results, max_distance):
        settings = {
            "source": source,
            "destination": dest,
            "range": str(range_ly),
            "radius": str(radius),
            "max_results": str(max_results),
            "max_distance": str(max_distance),
            "avoid_thargoids": bool(self._exp_avoid_thargoids_var.get()),
            "loop": bool(self._exp_loop.get()),
        }
        if planner == "Road to Riches":
            settings["min_value"] = self._exp_min_value.get().strip()
            settings["use_mapping_value"] = bool(self._exp_use_mapping_var.get())
        elif planner == "Exomastery":
            settings["min_value"] = self._exp_min_value.get().strip()
            settings["use_mapping_value"] = False
        else:
            settings["min_value"] = ""
            settings["use_mapping_value"] = False
        return settings


    def _plot_exploration_route(self, planner):
        """Validate and submit an exploration/salesman route request."""
        try:
            source = self._exp_source_ac.get().strip()
            self._exp_error_txt.set("")
            self._exp_source_ac.hide_list()
            self._exp_dest_ac.hide_list()

            if not source or source == self._exp_source_ac.placeholder:
                self._exp_error_txt.set("Please provide a starting system.")
                return

            dest = self._exp_dest_ac.get().strip()
            if dest == self._exp_dest_ac.placeholder:
                dest = ""

            try:
                range_ly = self._clamp_spinbox_input(
                    self._exp_range,
                    error_message="Invalid range",
                )
            except ValueError:
                self._exp_error_txt.set("Invalid range")
                return

            try:
                radius = self._clamp_spinbox_input(
                    self._exp_radius,
                    integer=True,
                    error_message="Radius, max systems, and max distance must be numbers.",
                )
                max_results = self._clamp_spinbox_input(
                    self._exp_max_results,
                    integer=True,
                    error_message="Radius, max systems, and max distance must be numbers.",
                )
                max_distance = self._clamp_spinbox_input(
                    self._exp_max_distance,
                    integer=True,
                    error_message="Radius, max systems, and max distance must be numbers.",
                )
            except ValueError:
                self._exp_error_txt.set("Radius, max systems, and max distance must be numbers.")
                return

            is_exobiology = planner == "Exomastery"
            is_riches = planner == "Road to Riches"
            body_types_map = {
                "Ammonia World Route": ["Ammonia world"],
                "Earth-like World Route": ["Earth-like world"],
                "Rocky/HMC Route": ["Rocky body", "High metal content world"],
            }

            params = {
                "from": source,
                "range": range_ly,
                "radius": radius,
                "max_results": max_results,
                "max_distance": max_distance,
                "loop": 1 if self._exp_loop.get() else 0,
            }
            if dest:
                params["to"] = dest

            if is_exobiology:
                try:
                    min_value = self._clamp_spinbox_input(
                        self._exp_min_value,
                        integer=True,
                        error_message="Minimum landmark value must be a number.",
                    )
                except ValueError:
                    self._exp_error_txt.set("Minimum landmark value must be a number.")
                    return
                api_url = "https://spansh.co.uk/api/exobiology/route"
                params["min_value"] = min_value
                params["avoid_thargoids"] = 1 if self._exp_avoid_thargoids_var.get() else 0
            else:
                api_url = "https://spansh.co.uk/api/riches/route"
                params["avoid_thargoids"] = 1 if self._exp_avoid_thargoids_var.get() else 0
                if is_riches:
                    try:
                        min_value = self._clamp_spinbox_input(
                            self._exp_min_value,
                            integer=True,
                            error_message="Minimum scan value must be a number.",
                        )
                    except ValueError:
                        self._exp_error_txt.set("Minimum scan value must be a number.")
                        return
                    params["min_value"] = min_value
                    params["use_mapping_value"] = 1 if self._exp_use_mapping_var.get() else 0
                elif planner in body_types_map:
                    params["body_types"] = body_types_map[planner]
                    params["min_value"] = 1

            settings = self._current_exploration_settings(
                planner,
                source,
                dest,
                range_ly,
                radius,
                max_results,
                max_distance,
            )

            self._set_plot_running_state(active=True, button=getattr(self, "_exp_calc_btn", None))

            token = self._next_plot_token()
            threading.Thread(
                target=self._exploration_route_worker,
                args=(api_url, params, planner, settings, token),
                daemon=True,
            ).start()
        except Exception:
            self._set_plot_running_state(active=False, button=getattr(self, "_exp_calc_btn", None))
            self._log_unexpected("Exploration plot error")
            self._exp_error_txt.set("Error starting route calculation.")


    def _exploration_route_worker(self, api_url, params, planner, settings, token):
        """Background worker for exploration route plotting."""
        try:
            if self._is_plot_cancelled():
                return

            source = params.get("from") or params.get("source", "")
            ok, nearest, error_msg = self._validate_source_system(source)
            if not ok:
                if nearest:
                    self._ui_call(self._exp_source_ac.set_text, nearest, False, token=token)
                    self._ui_call(self._copy_to_clipboard, nearest, token=token)
                self._ui_call(self._exploration_route_error, error_msg, token=token)
                return

            if self._is_plot_cancelled():
                return

            data = self._submit_spansh_job_request(
                api_url,
                data=self._traditional_form_data(params),
                accept_direct_result=True,
                direct_result_keys=("result", "systems", "system_jumps", "route"),
            )
            if data is None:
                return
            self._ui_call(self._exploration_route_success, data, planner, settings, token=token)

        except (_SpanshPollError, _SpanshPollTimeout) as e:
            self._ui_call(self._exploration_route_error, str(e), token=token)
        except requests.RequestException as e:
            self._ui_call(self._exploration_route_error, f"Network error: {e}", token=token)
        except Exception as e:
            self._log_unexpected(f"Exploration route error: {e}")
            self._ui_call(self._exploration_route_error, str(e), token=token)


    def _exploration_route_success(self, route_data, planner, settings=None):
        """Called on main thread when exploration route succeeds."""
        self._set_plot_running_state(active=False, button=getattr(self, "_exp_calc_btn", None))
        systems = self._extract_exploration_systems(route_data)
        if not systems:
            if self.plotter_win:
                try:
                    self._exp_calc_btn.config(state=tk.NORMAL, text="Calculate")
                    self._exp_error_txt.set("No route found for the given parameters.")
                    return
                except Exception:
                    pass
            self.show_error("No route found for the given parameters.")
            return

        settings = settings or {}
        self._reset_for_new_route()
        self._apply_exploration_route_data(planner, systems)
        if settings:
            self._store_plotter_settings(planner, settings)

        self._reset_offset_from_current_system()
        self._finalize_applied_route()


    def _extract_exploration_systems(self, payload):
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []

        for key in ("systems", "result", "system_jumps", "route"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        nested = payload.get("result")
        if isinstance(nested, dict):
            for key in ("systems", "result", "system_jumps", "route"):
                value = nested.get(key)
                if isinstance(value, list):
                    return value

        return []


    def _exploration_route_error(self, msg):
        """Called on main thread when exploration route fails."""
        self._set_plot_running_state(active=False, button=getattr(self, "_exp_calc_btn", None))
        if self.plotter_win:
            try:
                self._exp_error_txt.set(msg)
                return
            except (tk.TclError, AttributeError):
                pass
        self.show_error(msg)


    def _show_fleet_carrier_window(self):
        """Open fleet carrier plotter window."""
        planner = "Fleet Carrier Router"
        if self._is_plotting():
            return
        if not self._prepare_window_kind(planner):
            return

        settings = self._settings_for_planner(planner)
        self._fc_destinations = list(settings.get("destinations", []))
        self._fc_refuel_destinations = set(settings.get("refuel_destinations", []))

        self.plotter_win = tk.Toplevel(self.parent)
        self.plotter_win.title("Spansh Fleet Carrier Router")
        self.plotter_win.resizable(False, False)
        self.plotter_win.minsize(460, 0)
        self.plotter_win.columnconfigure(0, weight=1)
        self.plotter_win.protocol("WM_DELETE_WINDOW", self._close_plotter_window)

        content = tk.Frame(self.plotter_win)
        content.grid(row=0, column=0, padx=14, pady=12)
        content.columnconfigure(0, weight=1)

        row = 0
        self._label_with_help(content, "Source System:", "", row)
        row += 1
        self._fc_source_ac = AutoCompleter(content, "Source System", width=42)
        self._fc_source_ac.grid(row=row, column=0, sticky=tk.EW, padx=4, pady=(0, 6))
        current_sys = settings.get("source") or self._last_source_system or monitor.state.get("SystemName")
        if current_sys:
            self._fc_source_ac.set_text(current_sys, False)
        row += 2

        self._label_with_help(content, "Add Destination:", "", row)
        row += 1
        self._fc_dest_ac = AutoCompleter(
            content,
            "Destination System",
            width=42,
            selected_items_provider=lambda: list(getattr(self, "_fc_destinations", [])),
            on_select=lambda _value: self.plotter_win.after_idle(self._fc_add_destination),
        )
        self._fc_dest_ac.grid(row=row, column=0, sticky=tk.EW, padx=4, pady=(0, 6))
        self._fc_dest_ac.bind("<Return>", self._fc_add_destination_from_entry, add="+")
        self._fc_dest_ac.bind("<KP_Enter>", self._fc_add_destination_from_entry, add="+")
        row += 2

        dest_list_frame = tk.Frame(content)
        dest_list_frame.grid(row=row, column=0, sticky=tk.EW, padx=4, pady=(2, 8))
        dest_list_frame.columnconfigure(0, weight=1)
        self._fc_dest_list = DraggableListWidget(dest_list_frame, height=196, visible_rows=6)
        self._fc_dest_list.border.grid(row=0, column=0, sticky=tk.EW)
        self._fc_dest_list.set_items(self._fc_destinations)
        self._fc_dest_list.on_reorder = self._fc_refresh_destinations
        self._fc_dest_list.on_select = self._fc_select_destination_line
        self._fc_dest_menu = tk.Menu(self.plotter_win, tearoff=0)
        self._fc_dest_menu.add_command(label="Copy name", command=self._fc_copy_destination_name)
        self._fc_menu_destination_name = ""
        self._fc_refresh_destinations()
        row += 1

        self._fc_carrier_type = tk.StringVar(
            value=self._normalize_fleet_carrier_type(settings.get("carrier_type", "fleet"))
        )
        type_frame = tk.Frame(content)
        type_frame.grid(row=row, column=0, sticky=tk.W, pady=2)
        tk.Radiobutton(type_frame, text="Player Carrier", variable=self._fc_carrier_type, value="fleet").pack(side=tk.LEFT)
        tk.Radiobutton(type_frame, text="Squadron Carrier", variable=self._fc_carrier_type, value="squadron").pack(side=tk.LEFT, padx=(12, 0))
        row += 1

        used_frame = tk.Frame(content)
        used_frame.grid(row=row, column=0, sticky=tk.EW, pady=2)
        tk.Label(used_frame, text="Used Capacity (t):").pack(side=tk.LEFT)
        used_help = tk.Label(used_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                             relief=tk.RAISED, borderwidth=1, padx=2)
        used_help.pack(side=tk.LEFT, padx=(4, 0))
        Tooltip(used_help, "Fill in the capacity shown in the upper right corner of the carrier management screen.")
        self._fc_used_capacity = tk.Spinbox(used_frame, from_=0, to=60000, width=12,
                                            validate="key")
        self._fc_used_capacity.configure(validatecommand=self._spinbox_validator(self._fc_used_capacity))
        self._bind_live_spinbox_clamp(self._fc_used_capacity, integer=True)
        self._fc_used_capacity.delete(0, tk.END)
        self._fc_used_capacity.insert(0, settings.get("used_capacity", "0"))
        self._fc_used_capacity.pack(side=tk.RIGHT, padx=(0, 2))
        row += 1

        self._fc_determine_required_fuel = tk.BooleanVar(value=settings.get("determine_required_fuel", True))
        self._checkbox_with_help(
            content,
            "Determine Tritium Requirements",
            self._fc_determine_required_fuel,
            "Calculate how much Tritium would be required to complete the entire route.",
            row,
        )
        row += 1

        self._fc_fuel_frame = tk.Frame(content)
        self._fc_fuel_frame.grid(row=row, column=0, sticky=tk.EW, pady=2)
        fuel_row = tk.Frame(self._fc_fuel_frame)
        fuel_row.pack(fill=tk.X, pady=2)
        tk.Label(fuel_row, text="Tritium in Tank (t):").pack(side=tk.LEFT)
        self._fc_tritium_fuel = tk.Spinbox(fuel_row, from_=0, to=1000, width=12,
                                           validate="key")
        self._fc_tritium_fuel.configure(validatecommand=self._spinbox_validator(self._fc_tritium_fuel))
        self._bind_live_spinbox_clamp(self._fc_tritium_fuel, integer=True)
        self._fc_tritium_fuel.delete(0, tk.END)
        self._fc_tritium_fuel.insert(0, settings.get("tritium_fuel", "0"))
        self._fc_tritium_fuel.pack(side=tk.RIGHT, padx=(0, 2))

        market_row = tk.Frame(self._fc_fuel_frame)
        market_row.pack(fill=tk.X, pady=2)
        tk.Label(market_row, text="Tritium in Market (t):").pack(side=tk.LEFT)
        self._fc_tritium_market = tk.Spinbox(market_row, from_=0, to=60000, width=12,
                                             validate="key")
        self._fc_tritium_market.configure(validatecommand=self._spinbox_validator(self._fc_tritium_market))
        self._bind_live_spinbox_clamp(self._fc_tritium_market, integer=True)
        self._fc_tritium_market.delete(0, tk.END)
        self._fc_tritium_market.insert(0, settings.get("tritium_market", "0"))
        self._fc_tritium_market.pack(side=tk.RIGHT, padx=(0, 2))
        self._fc_determine_required_fuel.trace_add("write", lambda *_: self._fc_toggle_fuel_inputs())
        self._fc_toggle_fuel_inputs()
        row += 1

        btn_frame = tk.Frame(content)
        btn_frame.grid(row=row, column=0, pady=(10, 0))
        self._fc_calc_btn = tk.Button(btn_frame, text="Calculate", width=10, command=self._plot_fleet_carrier_route)
        self._fc_calc_btn.pack(side=tk.LEFT, padx=(0, 7))
        tk.Button(btn_frame, text="Cancel", width=10, command=self._cancel_fleet_carrier_plot).pack(side=tk.LEFT, padx=(7, 0))
        row += 1

        self._fc_error_txt = tk.StringVar()
        tk.Label(content, textvariable=self._fc_error_txt, fg="red", wraplength=340, justify=tk.CENTER).grid(
            row=row, column=0, pady=(10, 0)
        )
        self._configure_child_window(self.plotter_win)


    def _fc_refresh_destinations(self):
        if not hasattr(self, "_fc_dest_list"):
            return
        dlw = self._fc_dest_list

        def build_row(index, name, row_frame, row_bg):
            is_refuel = name in getattr(self, "_fc_refuel_destinations", set())
            row_frame.columnconfigure(2, weight=1)
            del_btn = tk.Button(
                row_frame,
                text="🗑",
                width=3,
                padx=1,
                pady=0,
                command=lambda i=index: self._fc_remove_destination(i),
            )
            del_btn.grid(row=0, column=0, padx=(2, 3), pady=1, sticky="")
            refuel_btn = tk.Button(
                row_frame,
                text="⛽",
                width=3,
                padx=1,
                pady=0,
                command=lambda i=index: self._fc_toggle_refuel_destination(i),
            )
            if is_refuel:
                refuel_btn.configure(bg="#ffd7a8", activebackground="#ffd7a8")
            refuel_btn.grid(row=0, column=1, padx=(0, 6), pady=1, sticky="")
            label = tk.Label(
                row_frame,
                text=name,
                anchor=tk.W,
                bg=row_bg,
                fg="black",
                cursor="hand2",
            )
            label.grid(row=0, column=2, sticky=tk.EW, pady=1)
            label.bind("<Button-3>", lambda e, n=name: self._fc_show_destination_menu(e, n))
            right_btns = tk.Frame(row_frame, bg=row_bg)
            right_btns.grid(row=0, column=3, padx=(10, 0), pady=1, sticky=tk.E)
            tk.Button(
                right_btns,
                text="▲",
                width=2,
                padx=0,
                pady=0,
                command=lambda i=index: self._fc_move_destination_to(i, -1),
            ).pack(side=tk.LEFT, padx=(0, 4))
            tk.Button(
                right_btns,
                text="▼",
                width=2,
                padx=0,
                pady=0,
                command=lambda i=index: self._fc_move_destination_to(i, 1),
            ).pack(side=tk.LEFT)

            for widget in (row_frame, label, right_btns):
                dlw.bind_row_events(widget, index)
            for widget in (del_btn, refuel_btn):
                dlw.bind_scroll_events(widget)

        self._refresh_draggable_rows(dlw, self._fc_destinations, build_row)


    def _fc_select_destination_line(self, index):
        if not hasattr(self, "_fc_dest_list"):
            return
        self._fc_dest_list.select_line(index)


    def _fc_add_destination(self):
        destination = self._fc_dest_ac.get().strip()
        if not destination or destination == self._fc_dest_ac.placeholder:
            return
        normalized_destination = destination.lower()
        existing_destinations = {
            (name or "").strip().lower()
            for name in self._fc_destinations
        }
        if normalized_destination not in existing_destinations:
            self._fc_destinations.append(destination)
            self._fc_refresh_destinations()
            self._fc_select_destination_line(len(self._fc_destinations) - 1)
        self._fc_dest_ac.set_text(self._fc_dest_ac.placeholder, True)


    def _fc_add_destination_from_entry(self, _event=None):
        destination = self._fc_dest_ac.get().strip()
        if not destination or destination == self._fc_dest_ac.placeholder:
            return "break"
        self._fc_error_txt.set("")
        self._resolve_system_record_async(
            destination,
            on_success=self._fc_destination_resolved,
            on_not_found=lambda query: self._fc_error_txt.set(
                f"Destination system '{query}' not found in Spansh."
            ),
            on_error=lambda query, _exc: self._fc_error_txt.set(
                f"Failed to look up '{query}'."
            ),
        )
        return "break"


    def _fc_destination_resolved(self, record_name):
        self._fc_dest_ac.set_text(record_name, False)
        self._fc_add_destination()


    def _fc_remove_destination(self, index=None):
        if index is None:
            index = self._fc_dest_list.selected_index
        if index is None or not (0 <= index < len(self._fc_destinations)):
            return
        self._fc_refuel_destinations.discard(self._fc_destinations[index])
        del self._fc_destinations[index]
        if not self._fc_destinations:
            self._fc_dest_list.selected_index = None
        else:
            self._fc_dest_list.selected_index = min(index, len(self._fc_destinations) - 1)
        self._fc_refresh_destinations()


    def _fc_move_destination_to(self, index, direction):
        new_index = index + direction
        if not (0 <= new_index < len(self._fc_destinations)):
            return
        self._fc_destinations[index], self._fc_destinations[new_index] = (
            self._fc_destinations[new_index],
            self._fc_destinations[index],
        )
        self._fc_dest_list.selected_index = new_index
        self._fc_refresh_destinations()


    def _fc_toggle_refuel_destination(self, index=None):
        if index is None:
            index = self._fc_dest_list.selected_index
        if index is None or not (0 <= index < len(self._fc_destinations)):
            return
        destination = self._fc_destinations[index]
        if destination in self._fc_refuel_destinations:
            self._fc_refuel_destinations.remove(destination)
        else:
            self._fc_refuel_destinations.add(destination)
        self._fc_refresh_destinations()


    def _fc_show_destination_menu(self, event, destination_name):
        self._fc_menu_destination_name = destination_name or ""
        try:
            self._fc_dest_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._fc_dest_menu.grab_release()


    def _fc_copy_destination_name(self):
        if self._fc_menu_destination_name:
            self._copy_to_clipboard(self._fc_menu_destination_name)


    def _fc_toggle_fuel_inputs(self):
        if self._fc_determine_required_fuel.get():
            self._fc_fuel_frame.grid_remove()
        else:
            self._fc_fuel_frame.grid()


    def _cancel_fleet_carrier_plot(self):
        """Cancel fleet-carrier plotting if active, otherwise close the window."""
        if self._is_plotting():
            self._mark_plot_stopped(cancelled=True)
            self._invalidate_plot_token()
            self._set_main_controls_enabled(True)
            self._set_plotter_windows_enabled(True)
        self._close_plotter_window()


    def _plot_fleet_carrier_route(self):
        try:
            source = self._fc_source_ac.get().strip()
            self._fc_error_txt.set("")
            self._fc_source_ac.hide_list()
            self._fc_dest_ac.hide_list()

            if not source or source == self._fc_source_ac.placeholder:
                self._fc_error_txt.set("Please provide a starting system.")
                return
            if not self._fc_destinations:
                self._fc_error_txt.set("Add at least one destination.")
                return

            used_capacity = self._clamp_spinbox_input(
                self._fc_used_capacity,
                integer=True,
                error_message="Used capacity must be a number.",
            )
            determine_required_fuel = bool(self._fc_determine_required_fuel.get())
            tritium_fuel = 0
            tritium_market = 0
            if not determine_required_fuel:
                tritium_fuel = self._clamp_spinbox_input(
                    self._fc_tritium_fuel,
                    integer=True,
                    error_message="Tritium values must be numbers.",
                )
                tritium_market = self._clamp_spinbox_input(
                    self._fc_tritium_market,
                    integer=True,
                    error_message="Tritium values must be numbers.",
                )

            params = {
                "source": source,
                "destinations": list(self._fc_destinations),
                "refuel_destinations": [
                    name for name in self._fc_destinations
                    if name in getattr(self, "_fc_refuel_destinations", set())
                ],
                "carrier_type": self._fc_carrier_type.get(),
                "used_capacity": used_capacity,
                "determine_required_fuel": determine_required_fuel,
                "tritium_fuel": tritium_fuel,
                "tritium_market": tritium_market,
            }

            self._set_plot_running_state(active=True, button=getattr(self, "_fc_calc_btn", None))

            token = self._next_plot_token()
            threading.Thread(target=self._fleet_carrier_route_worker, args=(params, token), daemon=True).start()
        except ValueError as e:
            self._fc_error_txt.set(str(e))
        except Exception:
            self._set_plot_running_state(active=False, button=getattr(self, "_fc_calc_btn", None))
            self._log_unexpected("Fleet carrier plot error")
            self._fc_error_txt.set("Error starting route calculation.")


    def _fleet_carrier_route_worker(self, params, token):
        try:
            ok, source_record, nearest, error_msg = self._resolve_valid_source_record(
                params["source"],
                require_id64=True,
            )
            if not ok:
                if nearest:
                    self._ui_call(self._fc_source_ac.set_text, nearest, False, token=token)
                    self._ui_call(self._copy_to_clipboard, nearest, token=token)
                self._ui_call(self._fleet_carrier_route_error, error_msg, token=token)
                return

            source_id64 = source_record.get("id64") if isinstance(source_record, dict) else None
            if not source_record or source_id64 in (None, ""):
                self._ui_call(self._fleet_carrier_route_error, f"Source system '{params['source']}' not found in Spansh.", token=token)
                return

            normalized_destinations = []
            seen_destinations = set()
            for name in params["destinations"]:
                normalized_name = (name or "").strip()
                if not normalized_name:
                    continue
                normalized_key = normalized_name.lower()
                if normalized_key in seen_destinations:
                    continue
                seen_destinations.add(normalized_key)
                normalized_destinations.append(normalized_name)

            destination_records = {}
            for name in normalized_destinations:
                record = self._resolve_system_record(name)
                record_id64 = record.get("id64") if isinstance(record, dict) else None
                if not record or record_id64 in (None, ""):
                    self._ui_call(self._fleet_carrier_route_error, f"Destination system '{name}' not found in Spansh.", token=token)
                    return
                destination_records[name.lower()] = record

            carrier_profile = self._fleet_carrier_profile(params["carrier_type"])
            destinations = [
                destination_records[name.lower()]
                for name in normalized_destinations
            ]

            payload = {
                "source": source_id64,
                "destinations": [dest.get("id64") for dest in destinations],
                "capacity": carrier_profile["capacity"],
                "mass": carrier_profile["mass"],
                "capacity_used": params["used_capacity"],
                "calculate_starting_fuel": 1 if params["determine_required_fuel"] else 0,
            }
            if not params["determine_required_fuel"]:
                payload["fuel_loaded"] = params["tritium_fuel"]
                payload["tritium_stored"] = params["tritium_market"]
            elif params.get("refuel_destinations"):
                refuel_destination_names = {
                    (name or "").strip().lower()
                    for name in params["refuel_destinations"]
                    if (name or "").strip()
                }
                payload["refuel_destinations"] = [
                    dest.get("id64")
                    for dest in destinations
                    if (dest.get("name") or "").strip().lower() in refuel_destination_names
                ]

            result = self._submit_spansh_job_request(
                "https://spansh.co.uk/api/fleetcarrier/route",
                data=payload,
                accept_direct_result=True,
                direct_result_keys=("result", "jumps"),
            )
            if result is None:
                return
            route_data = result.get("result", result) if isinstance(result, dict) else result
            self._ui_call(self._fleet_carrier_route_success, route_data, params, token=token)

        except (_SpanshPollError, _SpanshPollTimeout) as e:
            self._ui_call(self._fleet_carrier_route_error, str(e), token=token)
        except requests.RequestException as e:
            self._ui_call(self._fleet_carrier_route_error, f"Network error: {e}", token=token)
        except Exception as e:
            self._log_unexpected("Fleet carrier route error")
            self._ui_call(self._fleet_carrier_route_error, str(e), token=token)


    def _fleet_carrier_route_success(self, route_data, params):
        self._set_plot_running_state(active=False, button=getattr(self, "_fc_calc_btn", None))
        jumps = route_data.get("jumps", route_data if isinstance(route_data, list) else [])
        if not jumps:
            if self.plotter_win:
                try:
                    self._fc_calc_btn.config(state=tk.NORMAL, text="Calculate")
                    self._fc_error_txt.set("No carrier route found for the given parameters.")
                    return
                except (tk.TclError, AttributeError):
                    pass
            self.show_error("No carrier route found for the given parameters.")
            return

        settings = {
            "source": params["source"],
            "destinations": list(params["destinations"]),
            "refuel_destinations": list(params.get("refuel_destinations", [])),
            "carrier_type": params["carrier_type"],
            "used_capacity": params["used_capacity"],
            "determine_required_fuel": params["determine_required_fuel"],
            "tritium_fuel": params["tritium_fuel"],
            "tritium_market": params["tritium_market"],
        }
        self._reset_for_new_route()

        self.fleetcarrier = True
        self.exact_plotter = False
        self.galaxy = False

        self._reset_exploration_state()
        self.exact_route_data = []
        self.fleet_carrier_data = jumps
        for jump in self.fleet_carrier_data:
            jump.setdefault("done", False)
        self._apply_fleet_waypoint_flags(
            self.fleet_carrier_data,
            source=params.get("source", ""),
            destinations=params.get("destinations", []),
        )
        self._set_current_plotter("Fleet Carrier Router")

        self.route = []
        total_jumps = len(jumps) - 1 if len(jumps) > 1 else 0
        for i, jump in enumerate(jumps):
            distance = jump.get("distance", "")
            distance_remaining = jump.get("distance_to_destination", "")
            jumps_value = str(max(total_jumps - i, 0))
            self.route.append([
                jump.get("name", ""),
                jumps_value,
                distance,
                distance_remaining,
                "Yes" if jump.get("must_restock") else "No",
            ])

        self._store_plotter_settings("Fleet Carrier Router", settings)

        self._reset_offset_from_current_system()
        self._recalculate_jumps_left_from_offset()
        self._finalize_applied_route()


    def _fleet_carrier_route_error(self, msg):
        self._set_plot_running_state(active=False, button=getattr(self, "_fc_calc_btn", None))
        if self.plotter_win:
            try:
                self._fc_error_txt.set(msg)
                return
            except (tk.TclError, AttributeError):
                pass
        self.show_error(msg)


    def plot_route(self):
        """Validate inputs on main thread, then submit to background worker."""
        self.hide_error()
        try:
            source = self.source_ac.get().strip()
            dest = self.dest_ac.get().strip()
            vias = self._current_neutron_vias()

            # Hide autocomplete lists
            self.source_ac.hide_list()
            self.dest_ac.hide_list()

            # Validate inputs
            if not source or source == self.source_ac.placeholder:
                self._set_neutron_error("Please provide a starting system.")
                return
            if not dest or dest == self.dest_ac.placeholder:
                self._set_neutron_error("Please provide a destination system.")
                return

            # Range
            try:
                range_ly = self._clamp_spinbox_input(
                    self.range_entry,
                    error_message="Invalid range",
                )
            except ValueError:
                self._set_neutron_error("Invalid range")
                return

            try:
                efficiency = self._clamp_spinbox_input(
                    self.efficiency_entry,
                    integer=True,
                    error_message="Invalid efficiency",
                )
                self.neutron_efficiency_var.set(int(efficiency))
            except ValueError:
                self._set_neutron_error("Invalid efficiency")
                return

            supercharge_multiplier = self.supercharge_multiplier.get()

            self._set_plot_running_state(active=True, use_enable_plot_gui=True)

            params = {
                "source": source,
                "dest": dest,
                "vias": vias,
                "efficiency": efficiency,
                "range": range_ly,
                "supercharge_multiplier": supercharge_multiplier,
            }
            token = self._next_plot_token()
            threading.Thread(target=self._plot_route_worker, args=(params, token), daemon=True).start()
        except Exception:
            self._log_unexpected("Failed to start neutron route plot")
            self._set_plot_running_state(active=False, use_enable_plot_gui=True)
            self._set_neutron_error(self.plot_error)


    def _cancel_neutron_plot(self):
        """Cancel button for neutron plotter — cancels if computing, otherwise closes window."""
        if self._is_plotting():
            self._mark_plot_stopped(cancelled=True)
            self._invalidate_plot_token()
            self.enable_plot_gui(True)
        self._close_plotter_window()
        self.update_gui()


    def _poll_spansh_job(self, job, poll_interval=2, max_iterations=120,
                         cancel_attr="_plot_cancelled",
                         results_base="https://spansh.co.uk/api/results"):
        """Poll Spansh API for job results.

        Returns parsed JSON data dict on success, None if cancelled.
        Raises _SpanshPollError on API errors, _SpanshPollTimeout on timeout.
        """
        for attempt in range(max_iterations):
            if self._cancel_flag_from_attr(cancel_attr):
                return None

            try:
                result = requests.get(f"{results_base}/{job}", timeout=10)
            except requests.RequestException as exc:
                raise requests.RequestException(
                    f"Network error while polling Spansh: {exc}"
                ) from exc

            if self._cancel_flag_from_attr(cancel_attr):
                return None

            if result is not None and result.status_code == 200:
                data = result.json()
                if data.get("status") == "ok" or data.get("state") == "completed":
                    return data
                elif "error" in data:
                    raise _SpanshPollError(data["error"])
            elif result is not None and result.status_code != 202:
                try:
                    err_data = result.json()
                    error_msg = err_data.get("error", f"API error: {result.status_code}")
                except (ValueError, KeyError):
                    error_msg = f"API error: {result.status_code}"
                raise _SpanshPollError(error_msg, status_code=result.status_code)

            if attempt < max_iterations - 1:
                sleep(poll_interval)

        raise _SpanshPollTimeout("Route computation timed out. Please try again.")


    def _plot_route_worker(self, params, token):
        """Background worker for neutron route plotting."""
        try:
            if self._is_plot_cancelled():
                return

            ok, nearest, error_msg = self._validate_source_system(params["source"])
            if not ok:
                if nearest:
                    self._ui_call(self.source_ac.set_text, nearest, False, token=token)
                    self._ui_call(self._copy_to_clipboard, nearest, token=token)
                self._ui_call(self._plot_route_error, error_msg, token=token)
                return

            if self._is_plot_cancelled():
                return

            data = self._submit_spansh_job_request(
                "https://spansh.co.uk/api/route",
                params={
                    "efficiency": params["efficiency"],
                    "range": params["range"],
                    "from": params["source"],
                    "to": params["dest"],
                    "via": params.get("vias", []),
                    "supercharge_multiplier": params["supercharge_multiplier"],
                },
            )
            if data is None:
                return  # cancelled

            try:
                route = data["result"]["system_jumps"]
            except (KeyError, TypeError) as e:
                logger.warning(f"Invalid data from Spansh: {e}")
                self._ui_call(self._plot_route_error, self.plot_error, token=token)
                return
            self._ui_call(self._plot_route_success, route, token=token)

        except _SpanshPollError as e:
            if e.status_code == 400:
                self._ui_call(self._plot_route_validation_error, str(e), token=token)
            else:
                self._ui_call(self._plot_route_error, self.plot_error, token=token)
        except requests.RequestException as e:
            self._ui_call(self._plot_route_error, f"Network error: {e}", token=token)
        except _SpanshPollTimeout:
            self._ui_call(self._plot_route_error,
                          "The query to Spansh timed out. Please try again.", token=token)
        except Exception:
            self._log_unexpected("Unexpected neutron plotter worker failure")
            self._ui_call(self._plot_route_error, self.plot_error, token=token)


    def _plot_route_success(self, route):
        """Called on main thread when neutron route succeeds."""
        self._set_plot_running_state(active=False, use_enable_plot_gui=True)
        settings = {
            "source": self.source_ac.get().strip(),
            "destination": self.dest_ac.get().strip(),
            "vias": self._current_neutron_vias(),
            "range": self.range_entry.get().strip(),
            "efficiency": self.efficiency_slider.get(),
            "supercharge_multiplier": self.supercharge_multiplier.get(),
        }
        self._reset_for_new_route()
        self._apply_neutron_route_rows([
            {
                "system": waypoint.get("system", ""),
                "jumps": waypoint.get("jumps", 0),
                "distance_to_arrival": waypoint.get("distance_jumped", ""),
                "distance_remaining": waypoint.get("distance_left", ""),
                "neutron": "Yes" if waypoint.get("neutron_star") else "No",
                "done": False,
            }
            for waypoint in route
        ], settings=settings)

        self.offset = (
            1
            if self._route_starts_at_current_system()
            else 0
        )
        self.next_stop = self._current_route_row_name("")

        self._finalize_applied_route()


    def _plot_route_error(self, msg):
        """Called on main thread when neutron route fails."""
        self._set_plot_running_state(active=False, use_enable_plot_gui=True)
        # Show error in plotter window if open, otherwise in main panel
        if self.plotter_win:
            try:
                self.neutron_error_txt.set(msg)
                return
            except (tk.TclError, AttributeError):
                pass
        self.show_error(msg)


    def _plot_route_validation_error(self, error_msg):
        """Called on main thread for Spansh 400 validation errors."""
        self._set_plot_running_state(active=False, use_enable_plot_gui=True)
        plotter_alive = False
        try:
            plotter_alive = bool(self.plotter_win and self.plotter_win.winfo_exists())
        except Exception:
            plotter_alive = False
        # Show error in plotter window if open
        if plotter_alive:
            try:
                self.neutron_error_txt.set(error_msg)
                if "starting system" in error_msg:
                    if self.source_ac.winfo_exists():
                        self.source_ac["fg"] = "red"
                if "destination system" in error_msg or "finishing system" in error_msg:
                    if self.dest_ac.winfo_exists():
                        self.dest_ac["fg"] = "red"
                return
            except (tk.TclError, AttributeError):
                pass
        self.show_error(error_msg)
        if "destination system" in error_msg or "finishing system" in error_msg:
            try:
                if plotter_alive and self.dest_ac.winfo_exists():
                    self.dest_ac["fg"] = "red"
            except Exception:
                pass


    def plot_exact_route(self):
        """Validate and submit an exact plotter route request."""
        source = self.exact_source_ac.get().strip()
        dest = self.exact_dest_ac.get().strip()

        if not source or source == self.exact_source_ac.placeholder:
            self.exact_error_txt.set("Please provide a source system.")
            return
        if not dest or dest == self.exact_dest_ac.placeholder:
            self.exact_error_txt.set("Please provide a destination system.")
            return

        # Try to detect FSD if not yet detected
        if not self.ship_fsd_data:
            self._detect_fsd_from_monitor()
        if not self.ship_fsd_data:
            self.exact_error_txt.set("No ship data available. Enter the game or switch ships.")
            return

        # Parse cargo/reserve
        try:
            cargo = self._clamp_spinbox_input(
                self.exact_cargo_entry,
                integer=True,
                error_message="Invalid cargo value.",
            )
        except ValueError:
            self.exact_error_txt.set("Invalid cargo value.")
            return
        try:
            reserve = self._clamp_spinbox_input(
                self.exact_reserve_entry,
                error_message="Invalid reserve fuel value.",
            )
        except ValueError:
            self.exact_error_txt.set("Invalid reserve fuel value.")
            return
        cargo_val = self.exact_cargo_entry.get().strip()
        reserve_val = self.exact_reserve_entry.get().strip()

        # Disable UI while computing
        self.exact_calculate_btn.config(state=tk.DISABLED, text="Computing...")
        self.exact_error_txt.set("")

        # Build API params with individual FSD parameters
        # (Spansh API parses ship_build client-side on the website, API needs individual params)
        fsd = self.ship_fsd_data
        params = {
            "source": source,
            "destination": dest,
            "is_supercharged": 1 if self.exact_is_supercharged.get() else 0,
            "use_supercharge": 1 if self.exact_use_supercharge.get() else 0,
            "use_injections": 1 if self.exact_use_injections.get() else 0,
            "exclude_secondary": 1 if self.exact_exclude_secondary.get() else 0,
            "refuel_every_scoopable": 1 if self.exact_refuel_scoopable.get() else 0,
            "algorithm": self.exact_algorithm.get(),
            "tank_size": fsd['tank_size'],
            "cargo": cargo,
            "optimal_mass": fsd['optimal_mass'],
            "base_mass": fsd['unladen_mass'] + fsd['reserve_size'],
            "internal_tank_size": fsd['reserve_size'],
            "max_fuel_per_jump": fsd['max_fuel_per_jump'],
            "range_boost": fsd.get('range_boost', 0),
            "fuel_power": fsd['fuel_power'],
            "fuel_multiplier": fsd['fuel_multiplier'],
            "reserve_size": reserve,
            "supercharge_multiplier": fsd.get('supercharge_multiplier', 4),
            "injection_multiplier": 2,
            "max_time": 60,
        }

        # Capture settings to restore after clear_route in _exact_plot_success
        self._pending_exact_settings = {
            "source": source,
            "destination": dest,
            "cargo": cargo_val,
            "reserve": reserve_val,
            "is_supercharged": self.exact_is_supercharged.get(),
            "use_supercharge": self.exact_use_supercharge.get(),
            "use_injections": self.exact_use_injections.get(),
            "exclude_secondary": self.exact_exclude_secondary.get(),
            "refuel_scoopable": self.exact_refuel_scoopable.get(),
            "algorithm": self.exact_algorithm.get(),
        }

        self._set_plot_running_state(active=True, exact=True, button=getattr(self, "exact_calculate_btn", None))

        token = self._next_plot_token()
        threading.Thread(target=self._exact_plot_worker, args=(params, token), daemon=True).start()


    def _cancel_exact_plot(self):
        """Cancel the exact plotter computation and close the window."""
        self._mark_plot_stopped(cancelled=True, exact=True)
        self._invalidate_plot_token()
        self._set_main_controls_enabled(True)
        self._set_plotter_windows_enabled(True)
        self._close_exact_window()


    def _exact_plot_worker(self, params, token):
        """Background worker for exact plotter API call."""
        try:
            if self._is_plot_cancelled(exact=True):
                return

            source = params.get("source", "")
            ok, nearest, error_msg = self._validate_source_system(source)
            if not ok:
                if nearest:
                    self._ui_call(self.exact_source_ac.set_text, nearest, False, token=token)
                    self._ui_call(self._copy_to_clipboard, nearest, token=token)
                self._ui_call(self._exact_plot_error, error_msg, token=token)
                return

            dest = params.get("destination", "")
            dest_ok, dest_error = self._validate_destination_system(dest)
            if not dest_ok:
                self._ui_call(self._exact_plot_error, dest_error, token=token)
                return

            if self._is_plot_cancelled(exact=True):
                return

            response = self._submit_spansh_job_request(
                "https://www.spansh.co.uk/api/generic/route",
                data=params,
                cancel_attr="_exact_plot_cancelled",
                results_base="https://www.spansh.co.uk/api/results",
            )

            if self._is_plot_cancelled(exact=True):
                return

            if response is None:
                return  # cancelled
            self._ui_call(self._exact_plot_success, response, token=token)

        except _SpanshPollError as e:
            ui_error_msg, nearest_name = self._prepare_exact_plot_error_ui(str(e), params)
            self._ui_call(self._show_exact_plot_resolved_error, ui_error_msg, nearest_name, token=token)
        except _SpanshPollTimeout as e:
            self._ui_call(self._exact_plot_error, str(e), token=token)
        except requests.RequestException as e:
            self._ui_call(self._exact_plot_error, f"Network error: {e}", token=token)
        except Exception as e:
            self._log_unexpected(f"Exact plotter error: {e}")
            self._ui_call(self._exact_plot_error, str(e), token=token)


    def _exact_plot_success(self, route_data):
        """Called on main thread when exact plot succeeds."""
        self._set_plot_running_state(active=False, exact=True, button=getattr(self, "exact_calculate_btn", None))
        try:
            jumps = route_data["result"]["jumps"]
        except (KeyError, TypeError):
            self._exact_plot_error("Invalid response from Spansh.")
            return

        # Clear previous route (this wipes _exact_settings)
        self._reset_for_new_route()

        # Restore and persist exact plotter settings
        self._exact_settings = getattr(self, '_pending_exact_settings', None)
        self._save_exact_settings()

        # Set mode flags
        self.exact_plotter = True
        self._set_current_plotter("Galaxy Plotter")
        self.galaxy = False
        self.fleetcarrier = False

        self._reset_exploration_state()
        self.fleet_carrier_data = []

        # Store full jump data for overlay and refuel
        self.exact_route_data = jumps
        if self.exact_route_data:
            self.exact_route_data[0]["must_refuel"] = True
        for jump in self.exact_route_data:
            jump.setdefault("done", False)

        # Build self.route in standard format
        # First entry is the source system (not a jump), rest are actual jumps
        for i, jump in enumerate(jumps):
            system_name = jump.get("name", "")
            distance = jump.get("distance", 0)
            distance_remaining = jump.get("distance_to_destination", 0)

            self.route.append([
                system_name,
                "1" if i > 0 else "0",  # source isn't a jump
                str(distance),
                str(distance_remaining)
            ])

        # Jump count excludes the source system
        self.jumps_left = len(jumps) - 1 if len(jumps) > 1 else 0

        # Set offset from current system using the shared route-reset logic.
        self._reset_offset_from_current_system()
        self.next_stop = self._current_route_row_name("")

        # Set refuel/neutron status for current waypoint
        if self.offset < len(self.exact_route_data):
            self.pleaserefuel = self.exact_route_data[self.offset].get("must_refuel", False)

        self._finalize_applied_route(close_exact=True, update_overlay=True)


    def _exact_plot_error(self, message):
        """Called on main thread when exact plot fails."""
        self._set_plot_running_state(active=False, exact=True, button=getattr(self, "exact_calculate_btn", None))
        if hasattr(self, 'exact_error_txt'):
            self.exact_error_txt.set(message)


    def _check_system_in_spansh(self, system_name):
        """Check if a system exists in Spansh by querying the autocomplete API."""
        system_name = (system_name or "").strip()
        if not system_name:
            return False
        try:
            resp = requests.get(
                "https://spansh.co.uk/api/systems",
                params={"q": system_name},
                headers={'User-Agent': "EDMC_SpanshTools 1.0"},
                timeout=5
            )
        except requests.RequestException as exc:
            logger.warning("Spansh system lookup failed for '%s': %s", system_name, exc)
            return None

        if resp.status_code != 200:
            logger.warning(
                "Spansh system lookup for '%s' returned status %s",
                system_name,
                resp.status_code,
            )
            return None

        try:
            results = resp.json()
        except ValueError:
            logger.warning("Spansh system lookup for '%s' returned invalid JSON", system_name)
            return None

        for name in results:
            if str(name).strip().lower() == system_name.lower():
                return True
        return False


    def _spansh_lookup_error_message(self, label, system_name):
        return (
            f"Failed to look up {label} system '{system_name}' in Spansh.\n"
            "Please try again."
        )


    def _lookup_nearest_system(self, coords, *, timeout=5):
        x, y, z = coords
        response = requests.get(
            "https://www.spansh.co.uk/api/nearest",
            params={"x": x, "y": y, "z": z},
            headers=self._spansh_request_headers(),
            timeout=timeout,
        )
        if response.status_code != 200:
            raise _SpanshPollError(
                self._spansh_error_message(response, f"API error: {response.status_code}"),
                status_code=response.status_code,
            )
        payload = self._spansh_response_json(response, default={})
        if not isinstance(payload, dict):
            raise _SpanshPollError("Invalid response from Spansh.")
        return (payload.get("system", {}) or {}).get("name", "")


    def _source_matches_current_system(self, source):
        source_lower = (source or "").strip().lower()
        if not source_lower:
            return False
        return source_lower == self._current_system_name().lower()


    def _current_spansh_coords(self):
        coords, _system = self._get_current_location()
        if coords is None:
            coords = monitor.state.get('StarPos')
        return coords


    def _nearest_system_name(self, coords):
        try:
            return self._lookup_nearest_system(coords, timeout=5)
        except (_SpanshPollError, requests.RequestException):
            self._log_unexpected("Nearest system lookup failed")
        return ""


    def _resolve_valid_source_record(self, source, *, require_id64=False):
        source = (source or "").strip()
        if not source:
            return (False, None, None, "Source system is empty.")

        try:
            record = self._resolve_system_record(source)
        except requests.RequestException as exc:
            logger.warning("Spansh source lookup failed for '%s': %s", source, exc)
            return (False, None, None, self._spansh_lookup_error_message("source", source))
        except Exception:
            self._log_unexpected(f"Source lookup failed for '{source}'")
            return (False, None, None, self._spansh_lookup_error_message("source", source))

        record_id64 = record.get("id64") if isinstance(record, dict) else None
        if record and (not require_id64 or record_id64 not in (None, "")):
            return (True, record, None, None)
        if record and require_id64 and record_id64 in (None, ""):
            return (False, None, None, f"Source system '{source}' not found in Spansh.")

        known_system = self._check_system_in_spansh(source)
        if known_system is None:
            return (False, None, None, self._spansh_lookup_error_message("source", source))
        if known_system:
            if require_id64:
                return (
                    False,
                    None,
                    None,
                    f"Source system '{source}' is known to Spansh,\n"
                    "but route details are unavailable right now.\n"
                    "Please try again.",
                )
            return (True, {"name": source}, None, None)

        source_is_current = self._source_matches_current_system(source)
        coords = self._current_spansh_coords()
        tip = ("Tip: Plot a route to this system in game\n"
               "to log it in Spansh, then try again.")

        if source_is_current and coords:
            nearest_name = self._nearest_system_name(coords)
            if nearest_name and nearest_name.strip().lower() != source.lower():
                return (
                    False,
                    None,
                    nearest_name,
                    "Your current system is not in Spansh database.\n"
                    f"Nearest known system: {nearest_name}\n"
                    "System name copied to clipboard.\n"
                    "Route will start from there. Press Calculate again to plot.",
                )
            if nearest_name and nearest_name.strip().lower() == source.lower():
                return (True, None, None, None)

        if source_is_current:
            return (
                False,
                None,
                None,
                "Your current system is not in Spansh database.\n"
                "Use 'Find nearest system' with coordinates\n"
                f"from the Galaxy Map.\n{tip}",
            )

        return (
            False,
            None,
            None,
            f"Source '{source}' not found in Spansh database.\n"
            f"You are not at this system, so the plotter\n"
            f"cannot find the nearest known system.\n"
            f"Use 'Find nearest system' with coordinates\n"
            f"from the Galaxy Map.\n{tip}",
        )


    def _validate_source_system(self, source):
        """Validate source system against Spansh (thread-safe, no UI calls).

        Returns (ok, nearest_name_or_None, error_msg_or_None).
        """
        ok, _record, nearest_name, error_msg = self._resolve_valid_source_record(source)
        return ok, nearest_name, error_msg


    def _validate_destination_system(self, dest):
        """Validate destination system against Spansh (thread-safe, no UI calls).

        Returns (ok, error_msg_or_None).
        """
        dest = (dest or "").strip()
        if not dest:
            return (False, "Destination system is empty.")
        known_system = self._check_system_in_spansh(dest)
        if known_system is True:
            return (True, None)
        if known_system is None:
            return (False, self._spansh_lookup_error_message("destination", dest))
        tip = ("Tip: Plot a route to this system in game\n"
               "to log it in Spansh, then try again.")
        return (False,
                f"Destination '{dest}' not found in Spansh database.\n"
                f"Use 'Find nearest system' with coordinates\n"
                f"from the Galaxy Map to find an alternative.\n{tip}")


    def _prepare_exact_plot_error_ui(self, error_msg, params):
        """Resolve exact plot fallback messages off the UI thread."""
        source = params.get("source", "")
        dest = params.get("destination", "")

        ok, nearest, src_error = self._validate_source_system(source)
        if not ok:
            return src_error, nearest or ""

        dest_ok, dest_error = self._validate_destination_system(dest)
        if not dest_ok:
            return dest_error, ""

        # Both exist but route failed — likely sync delay or API issue
        msg = (f"{error_msg}\n"
               f"This can happen when a system was recently\n"
               f"discovered and not fully synced yet.\n"
               f"Wait a few minutes and try again.")
        return msg, ""


    def _show_exact_plot_resolved_error(self, message, nearest_name=""):
        if nearest_name:
            try:
                self.exact_source_ac.set_text(nearest_name, False)
            except Exception:
                pass
            self._copy_to_clipboard(nearest_name)
        self._exact_plot_error(message)


    def show_nearest_finder(self):
        """Open a window to find the nearest Spansh system by coordinates."""
        win = tk.Toplevel(self.parent)
        win.title("Find Nearest System")
        win.resizable(False, False)

        row = 0
        tk.Label(win, text="Enter coordinates from Galaxy Map:").grid(
            row=row, columnspan=2, padx=10, pady=(10, 5))
        row += 1

        # Galaxy bounds: X [-50000, +50000], Y [-16000, +9000], Z [-24000, +76000]
        tk.Label(win, text="X:").grid(row=row, column=0, sticky=tk.E, padx=(10, 2), pady=2)
        def _select_all(widget):
            widget.bind("<FocusIn>", lambda e: widget.after(10, lambda: widget.select_range(0, tk.END)))

        nearest_x = tk.Spinbox(win, from_=-50000, to=50000, width=10, validate="key")
        nearest_x.configure(validatecommand=self._spinbox_validator(nearest_x, signed=True))
        nearest_x.delete(0, tk.END)
        nearest_x.insert(0, "0")
        nearest_x.grid(row=row, column=1, padx=(2, 10), pady=2, sticky=tk.W)
        _select_all(nearest_x)
        row += 1

        tk.Label(win, text="Y:").grid(row=row, column=0, sticky=tk.E, padx=(10, 2), pady=2)
        nearest_y = tk.Spinbox(win, from_=-16000, to=9000, width=10, validate="key")
        nearest_y.configure(validatecommand=self._spinbox_validator(nearest_y, signed=True))
        nearest_y.delete(0, tk.END)
        nearest_y.insert(0, "0")
        nearest_y.grid(row=row, column=1, padx=(2, 10), pady=2, sticky=tk.W)
        _select_all(nearest_y)
        row += 1

        tk.Label(win, text="Z:").grid(row=row, column=0, sticky=tk.E, padx=(10, 2), pady=2)
        nearest_z = tk.Spinbox(win, from_=-24000, to=76000, width=10, validate="key")
        nearest_z.configure(validatecommand=self._spinbox_validator(nearest_z, signed=True))
        nearest_z.delete(0, tk.END)
        nearest_z.insert(0, "0")
        nearest_z.grid(row=row, column=1, padx=(2, 10), pady=2, sticky=tk.W)
        _select_all(nearest_z)
        row += 1

        result_var = tk.StringVar()
        result_lbl = tk.Label(win, textvariable=result_var, fg="blue", wraplength=250)
        result_lbl.grid(row=row, columnspan=2, padx=10, pady=5)
        row += 1

        coord_limits = {
            "X": (nearest_x, -50000, 50000),
            "Y": (nearest_y, -16000, 9000),
            "Z": (nearest_z, -24000, 76000),
        }

        def do_search():
            try:
                x = float(nearest_x.get())
                y = float(nearest_y.get())
                z = float(nearest_z.get())
            except ValueError:
                result_var.set("Invalid coordinates. Enter numbers only.")
                result_lbl.config(fg="red")
                return

            # Clamp to bounds and update spinboxes if out of range
            for name, (spinbox, lo, hi) in coord_limits.items():
                val = {"X": x, "Y": y, "Z": z}[name]
                clamped = max(lo, min(hi, val))
                if clamped != val:
                    spinbox.delete(0, tk.END)
                    spinbox.insert(0, str(int(clamped)))
                    if name == "X": x = clamped
                    elif name == "Y": y = clamped
                    else: z = clamped

            result_var.set("Searching...")
            result_lbl.config(fg="blue")
            search_btn.config(state=tk.DISABLED)

            def worker():
                try:
                    name = self._lookup_nearest_system((x, y, z), timeout=10)
                    if name:
                        def _copy_and_show(n=name):
                            self._copy_to_clipboard(n)
                            result_var.set(
                                f"Nearest system: {n}\n"
                                f"Copied to clipboard.")
                            result_lbl.config(fg="green")
                        self._window_after_if_alive(win, 0, _copy_and_show)
                    else:
                        self._window_after_if_alive(win, 0, lambda: result_var.set("No system found nearby."))
                        self._window_after_if_alive(win, 0, lambda: result_lbl.config(fg="red"))
                except (_SpanshPollError, requests.RequestException) as e:
                    self._window_after_if_alive(win, 0, lambda err=e: result_var.set(str(err)))
                    self._window_after_if_alive(win, 0, lambda: result_lbl.config(fg="red"))
                finally:
                    self._window_after_if_alive(win, 0, lambda: search_btn.config(state=tk.NORMAL))

            threading.Thread(target=worker, daemon=True).start()

        search_btn = tk.Button(win, text="Find Nearest", command=do_search)
        search_btn.grid(row=row, columnspan=2, padx=10, pady=10)

    #   -- Overlay support --
