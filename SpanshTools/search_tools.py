"""Search tools mixin -- nearest system finder and coordinate lookup."""
import tkinter as tk
from tkinter import messagebox
import threading
import os
import json

from config import config
from .web_utils import WebUtils
from .AutoCompleter import AutoCompleter
from .constants import logger
from .widgets import Tooltip, DraggableListWidget, truncate_text_px

class SearchToolsMixin:
    """Mixin for nearest-system finder and coordinate-based search dialogs."""

    _NEAREST_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "nearest_search_history.json")

    # --- Nearest Finder Window ---

    def show_nearest_finder(self):
        if hasattr(self, "_nearest_finder_win") and self._nearest_finder_win and self._nearest_finder_win.winfo_exists():
            self._nearest_finder_win.lift()
            return

        win = tk.Toplevel(self.parent)
        win.withdraw()
        self._nearest_finder_win = win
        win.title("Find Nearest System")
        win.resizable(False, False)
        win.minsize(400, 200)

        try:
            self._nearest_history_collapsed = bool(config.get_int('spansh_nearest_history_collapsed', default=0))

            mode_var = tk.StringVar(value="coords")

            container = tk.Frame(win, padx=10, pady=5)
            container.pack(fill=tk.BOTH, expand=True)
            container.columnconfigure(0, weight=1)

            info_lbl = tk.Label(container, text="Right click on list elements for options.", font=("", 9))
            info_lbl.grid(row=0, column=0, pady=(5, 0), sticky=tk.EW)

            mode_frame = tk.LabelFrame(container, text="Search Mode", padx=10, pady=5)
            mode_frame.grid(row=1, column=0, sticky=tk.EW, pady=5)
            rb_inner_frame = tk.Frame(mode_frame)
            rb_inner_frame.pack(expand=True)

            rb_coords = tk.Radiobutton(rb_inner_frame, text="Find Nearest", variable=mode_var, value="coords")
            rb_system = tk.Radiobutton(rb_inner_frame, text="Get Coordinates", variable=mode_var, value="system")
            rb_coords.pack(side=tk.LEFT, padx=15)
            rb_system.pack(side=tk.LEFT, padx=15)

            # Input area
            input_container = tk.Frame(container)
            input_container.grid(row=2, column=0, sticky=tk.EW)
            input_container.columnconfigure(0, weight=1)

            coords_frame = tk.Frame(input_container)
            self._nearest_coords_frame = coords_frame
            coords_inner = tk.Frame(coords_frame)
            coords_inner.pack(expand=True)

            tk.Label(coords_inner, text="X:").grid(row=0, column=0, sticky=tk.E, padx=2, pady=2)
            nearest_x = tk.Spinbox(coords_inner, from_=-50000, to=50000, width=15, increment=1)
            self._setup_spinbox(nearest_x, signed=True, allow_float=True)
            nearest_x.delete(0, tk.END)
            nearest_x.grid(row=0, column=1, sticky=tk.W, padx=2, pady=2)

            tk.Label(coords_inner, text="Y:").grid(row=1, column=0, sticky=tk.E, padx=2, pady=2)
            nearest_y = tk.Spinbox(coords_inner, from_=-16000, to=9000, width=15, increment=1)
            self._setup_spinbox(nearest_y, signed=True, allow_float=True)
            nearest_y.delete(0, tk.END)
            nearest_y.grid(row=1, column=1, sticky=tk.W, padx=2, pady=2)

            tk.Label(coords_inner, text="Z:").grid(row=2, column=0, sticky=tk.E, padx=2, pady=2)
            nearest_z = tk.Spinbox(coords_inner, from_=-24000, to=76000, width=15, increment=1)
            self._setup_spinbox(nearest_z, signed=True, allow_float=True)
            nearest_z.delete(0, tk.END)
            nearest_z.grid(row=2, column=1, sticky=tk.W, padx=2, pady=2)

            system_frame = tk.Frame(input_container)
            self._nearest_system_frame = system_frame
            system_frame.columnconfigure(0, weight=1)

            self._nearest_system_info_lbl = tk.Label(self._nearest_system_frame,
                                                    text="Autocomplete may not have it, but you can still search to query EDSM.",
                                                    font=("", 9), wraplength=350, justify=tk.CENTER)
            self._nearest_system_info_lbl.grid(row=0, column=0, pady=(0, 5), sticky=tk.EW)

            entry_row = tk.Frame(self._nearest_system_frame)
            entry_row.grid(row=1, column=0, pady=2, sticky=tk.EW)
            entry_row.columnconfigure(1, weight=1)
            tk.Label(entry_row, text="System Name:").grid(row=0, column=0, padx=2, sticky=tk.W)

            system_ac = AutoCompleter(entry_row, "System Name", width=30)
            system_ac.grid(row=0, column=1, padx=2, sticky=tk.EW)
            if getattr(self, "current_system", None):
                system_ac.set_text(self.current_system, False)

            action_frame = tk.Frame(container)
            action_frame.grid(row=3, column=0, sticky=tk.EW, pady=5)
            action_frame.columnconfigure(0, weight=1)

            result_var = tk.StringVar()
            result_lbl = tk.Label(action_frame, textvariable=result_var, font=("", 10, "bold"), wraplength=350, justify=tk.CENTER)

            search_btn = tk.Button(action_frame, text="Find", width=18)
            search_btn.grid(row=1, column=0, pady=5)

            def _update_result(text, color="black"):
                result_var.set(text)
                result_lbl.config(fg=color)
                if text:
                    result_lbl.grid(row=0, column=0, pady=5, sticky=tk.EW)
                else:
                    result_lbl.grid_forget()
                win.update_idletasks()
                win.geometry("")

            def worker():
                mode = mode_var.get()
                try:
                    if mode == "coords":
                        try:
                            x = float(nearest_x.get() or 0)
                            y = float(nearest_y.get() or 0)
                            z = float(nearest_z.get() or 0)
                        except ValueError:
                            self._window_after_if_alive(win, 0, lambda: _update_result("Invalid coordinates.", "red"))
                            return

                        x = max(-50000, min(50000, x)); y = max(-16000, min(9000, y)); z = max(-24000, min(76000, z))
                        name, real_coords, distance = WebUtils.get_nearest_system((x, y, z))
                        if name:
                            self._window_after_if_alive(win, 0, lambda n=name, c=real_coords, d=distance: _success_nearest(n, c, d))
                        else:
                            self._window_after_if_alive(win, 0, lambda: _update_result("No system found nearby.", "red"))

                    else: # system mode
                        s_name = system_ac.get().strip()
                        if system_ac.is_effectively_empty():
                            self._window_after_if_alive(win, 0, lambda: _update_result("Enter a system name.", "black"))
                            return

                        res_name, coords = WebUtils.get_system_coordinates(s_name)
                        if coords:
                            self._window_after_if_alive(win, 0, lambda n=res_name, c=coords: _success_coords(n, c))
                        else:
                            self._window_after_if_alive(win, 0, lambda: _update_result("System not found in Spansh or EDSM.", "red"))

                except Exception as e:
                    self._window_after_if_alive(win, 0, lambda err=e: _update_result(f"Error: {err}", "red"))
                finally:
                    self._window_after_if_alive(win, 0, lambda: search_btn.config(state=tk.NORMAL))

            def _success_nearest(n, c, d=None):
                self._copy_to_clipboard(n)
                dist_str = f"\nDistance: {d:.2f} Ly" if d is not None else ""
                _update_result(f"Found: {n}{dist_str}\nCopied to clipboard.", "green")
                _add_to_history(n, c)

            def _success_coords(n, c):
                c_str = f"X: {c[0]:.2f}  Y: {c[1]:.2f}  Z: {c[2]:.2f}"
                self._copy_to_clipboard(f"{c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f}")
                _update_result(f"System: {n}\nCoordinates: {c_str}\nCopied to clipboard.", "green")
                _add_to_history(n, c)

            def _add_to_history(n, c):
                history = SearchToolsMixin.load_nearest_history()
                history = [e for e in history if e.get("name") != n]
                history.insert(0, {"name": n, "coords": list(c)})
                SearchToolsMixin.save_nearest_history(history)
                self._refresh_nearest_history_rows()

            def do_find():
                _update_result("Searching...", "blue")
                search_btn.config(state=tk.DISABLED)
                threading.Thread(target=worker, daemon=True).start()

            search_btn.config(command=do_find)

            def on_mode_change():
                mode = mode_var.get()
                _update_result("", "black")
                self._toggle_nearest_mode(mode)

            rb_coords.config(command=on_mode_change)
            rb_system.config(command=on_mode_change)

            history_outer_frame = tk.Frame(container)
            history_outer_frame.grid(row=4, column=0, sticky=tk.EW, pady=(10, 0))
            self._nearest_history_outer_frame = history_outer_frame

            header_row = tk.Frame(history_outer_frame)
            header_row.pack(fill=tk.X)

            self._nearest_history_collapse_btn = tk.Button(
                header_row,
                text="⏵" if self._nearest_history_collapsed else "⏷",
                font=("", 8), width=3, padx=1, pady=0, bd=1, relief=tk.GROOVE,
                command=self._toggle_nearest_history_collapse
            )
            self._nearest_history_collapse_btn.pack(side=tk.LEFT)
            Tooltip(self._nearest_history_collapse_btn, "Expand/Collapse History")

            tk.Label(header_row, text="Search History", font=("", 10, "bold")).pack(side=tk.LEFT, expand=True)

            clear_btn = tk.Button(header_row, text="🗑", font=("", 10), width=3, padx=1, pady=0, bd=1, relief=tk.GROOVE,
                                 command=lambda: self._clear_nearest_history())
            clear_btn.pack(side=tk.RIGHT)
            Tooltip(clear_btn, "Clear History")

            self._nearest_history_content = tk.Frame(history_outer_frame)
            self._nearest_history_list = DraggableListWidget(self._nearest_history_content, height=180, visible_rows=6)
            self._nearest_history_list.border.pack(fill=tk.X, expand=True)
            self._nearest_history_list.drag_enabled = False
            self._nearest_history_list.on_select = self._select_nearest_history_line
            self._nearest_history_content.pack(fill=tk.X, pady=(5, 0))

            self._nearest_history_menu = tk.Menu(win, tearoff=0)
            self._nearest_history_menu.add_command(label="Copy Name")
            self._nearest_history_menu.add_command(label="Copy Coordinates")
            self._nearest_history_menu.add_separator()
            self._nearest_history_menu.add_command(label="Open in EDSM")
            self._nearest_history_menu.add_command(label="Open in Spansh")

            self._bind_select_all_text(system_ac)

            self._nearest_search_data = []
            self._refresh_nearest_history_rows()
            win.update_idletasks()
            self._nearest_finder_min_width = max(400, win.winfo_reqwidth(), win.winfo_width())
            win.minsize(self._nearest_finder_min_width, 200)
            if self._nearest_history_collapsed:
                self._nearest_history_content.pack_forget()

            self._configure_child_window(win)

            def show_history_menu(event, name, index=None):
                if index is not None and hasattr(self, "_nearest_history_list"):
                    self._select_nearest_history_line(index)
                self._nearest_history_menu.entryconfigure("Copy Name", command=lambda: self._copy_to_clipboard(name))
                coords = next((e.get("coords") for e in self._nearest_search_data if e.get("name") == name), [0,0,0])
                c_str = f"X: {coords[0]:.2f}  Y: {coords[1]:.2f}  Z: {coords[2]:.2f}"
                self._nearest_history_menu.entryconfigure("Copy Coordinates", command=lambda: self._copy_to_clipboard(c_str))
                self._nearest_history_menu.entryconfigure("Open in EDSM", command=lambda: threading.Thread(target=lambda: WebUtils.open_edsm(name), daemon=True).start())
                self._nearest_history_menu.entryconfigure("Open in Spansh", command=lambda: threading.Thread(target=lambda: WebUtils.open_spansh(name), daemon=True).start())
                try:
                    self._nearest_history_menu.tk_popup(event.x_root, event.y_root)
                finally:
                    self._nearest_history_menu.grab_release()

            self._nearest_show_history_menu = show_history_menu

            win.bind("<Return>", lambda e: do_find())
            self._toggle_nearest_mode("coords")

            win.update_idletasks()
            win.geometry("")

        except Exception as e:
            logger.error(f"Error drawing Find Nearest UI: {e}")
            tk.Label(win, text=f"Error initializing window: {e}", fg="red").pack(pady=20)

    # --- UI Toggle Helpers ---

    def _toggle_nearest_mode(self, mode):
        if not hasattr(self, "_nearest_coords_frame"): return
        if mode == "coords":
            self._nearest_system_frame.grid_forget()
            self._nearest_coords_frame.grid(row=0, column=0, pady=5, sticky=tk.EW)
        else:
            self._nearest_coords_frame.grid_forget()
            self._nearest_system_frame.grid(row=0, column=0, pady=5, sticky=tk.EW)
        if hasattr(self, "_nearest_finder_win"):
            self._nearest_finder_win.update_idletasks()
            self._nearest_finder_win.geometry("")

    def _toggle_nearest_history_collapse(self):
        self._nearest_history_collapsed = not self._nearest_history_collapsed
        config.set('spansh_nearest_history_collapsed', 1 if self._nearest_history_collapsed else 0)
        self._nearest_history_collapse_btn.config(text="⏵" if self._nearest_history_collapsed else "⏷")
        if self._nearest_history_collapsed:
            self._nearest_history_content.pack_forget()
        else:
            self._nearest_history_content.pack(fill=tk.X, pady=(5, 0))
        if hasattr(self, "_nearest_finder_win"):
            self._nearest_finder_win.update_idletasks()
            self._nearest_finder_win.geometry("")

    # --- History Management ---

    def _refresh_nearest_history_rows(self):
        if not hasattr(self, "_nearest_history_list"):
            return
        dlw = self._nearest_history_list
        data = SearchToolsMixin.load_nearest_history()
        dlw.set_items(data)
        self._nearest_search_data = data

        def build_row(index, entry, row_frame, row_bg):
            name = entry.get("name", "Unknown")
            coords = entry.get("coords", [0, 0, 0])
            display_coords = f"X: {coords[0]:.2f}  Y: {coords[1]:.2f}  Z: {coords[2]:.2f}"

            row_frame.columnconfigure(0, weight=1)

            lbl_text = f"{index + 1}. {name} | {display_coords}"
            display_text, truncated = truncate_text_px(lbl_text, 320)

            label = tk.Label(row_frame, text=display_text, anchor=tk.W, bg=row_bg, fg="black", cursor="hand2")
            label.grid(row=0, column=0, sticky=tk.EW, pady=1, padx=(5, 5))
            if truncated:
                Tooltip(label, lbl_text)

            del_btn = tk.Button(row_frame, text="🗑", width=3, padx=1, pady=0,
                                command=lambda i=index: self._remove_nearest_history_item(i))
            del_btn.grid(row=0, column=1, padx=(5, 2), pady=1)

            for widget in (row_frame, label):
                dlw.bind_row_events(widget, index)
                widget.bind(
                    "<Button-3>",
                    lambda e, n=name, i=index: self._nearest_show_history_menu(e, n, i),
                )
            dlw.bind_scroll_events(del_btn)

        self._refresh_draggable_rows(dlw, data, build_row)

    def _select_nearest_history_line(self, index):
        if not hasattr(self, "_nearest_history_list"):
            return
        self._nearest_history_list.set_selected_index(index, update_highlight=True)

    def _remove_nearest_history_item(self, index):
        history = SearchToolsMixin.load_nearest_history()
        if 0 <= index < len(history):
            history.pop(index)
            SearchToolsMixin.save_nearest_history(history)
            self._refresh_nearest_history_rows()

    def _clear_nearest_history(self):
        if messagebox.askyesno("Clear History", "Are you sure you want to clear search history?", parent=self._nearest_finder_win):
            SearchToolsMixin.save_nearest_history([])
            self._refresh_nearest_history_rows()

    @classmethod
    def load_nearest_history(cls):
        if os.path.exists(cls._NEAREST_HISTORY_PATH):
            try:
                with open(cls._NEAREST_HISTORY_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    @classmethod
    def save_nearest_history(cls, data):
        try:
            target_dir = os.path.dirname(cls._NEAREST_HISTORY_PATH)
            os.makedirs(target_dir, exist_ok=True)
            tmp_path = cls._NEAREST_HISTORY_PATH + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data[:50], f)
            os.replace(tmp_path, cls._NEAREST_HISTORY_PATH)
        except Exception as e:
            logger.error(f"Error saving nearest history: {e}")
