"""Plotter window mixins — neutron, exact/galaxy, exploration, fleet carrier."""

import json
import os
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as confirmDialog

from .web_utils import WebUtils, RequestException
from .search_tools import SearchToolsMixin
from config import config
from monitor import monitor

from .AutoCompleter import AutoCompleter
from .constants import (
    SPANSH_POLL_INTERVAL,
    SPANSH_POLL_MAX_ITERATIONS,
    SHIP_LIST_MAX_OWNED,
    SHIP_LIST_MAX_IMPORTED,
    _SpanshPollError,
    _SpanshPollTimeout,
    logger,
)
from .widgets import (
    DraggableListWidget,
    PlaceHolder,
    Tooltip,
    truncate_text_px,
)


class PlottersMixin(SearchToolsMixin):
    """Mixin providing route plotter windows (exact, neutron, exploration, fleet carrier) and ship list management."""

    # -- Ship List Handlers --

    _EXACT_SHIP_DIALOG_SIZE = (420, 210)
    _EXACT_SELECTED_SHIP_CONFIG_KEY = "spansh_exact_selected_ship_key"

    def _show_exact_ship_list(self):
        if self._plotter_window_kind != "Exact Plotter" or not getattr(self, "plotter_win", None):
            return
        existing = self._live_exact_ship_dialog("_exact_ship_list_win")
        if existing is not None:
            self._raise_child_window(existing)
            return

        win = tk.Toplevel(self.plotter_win)
        win.withdraw()
        self._exact_ship_list_win = win
        win.title("Ship List")
        win.resizable(False, False)
        win.minsize(460, 0)
        win.columnconfigure(0, weight=1)

        content = tk.Frame(win)
        content.grid(row=0, column=0, padx=14, pady=12)
        content.columnconfigure(0, weight=1)

        tk.Label(
            content,
            text="Double-click/Select to use. Drag to reorder.\nUse 📝 to rename, 🗑 to remove. Right click on ships to access more options.\nUpdate imported ships by selecting and re-importing.",
            justify=tk.LEFT,
        ).grid(row=0, column=0, sticky=tk.W, padx=4, pady=(0, 4))

        self._exact_ship_list_current_frame = tk.Frame(content, relief=tk.SUNKEN, borderwidth=1)
        self._exact_ship_list_current_frame.grid(row=1, column=0, sticky=tk.EW, padx=4, pady=(0, 0))
        self._exact_ship_list_current_frame.columnconfigure(1, weight=1)
        self._refresh_ship_list_current_row()

        search_frame = tk.Frame(content)
        search_frame.grid(row=2, column=0, sticky=tk.EW, padx=4, pady=(4, 2))
        search_frame.columnconfigure(1, weight=1)
        tk.Label(search_frame, text="Search:").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        self._exact_ship_list_search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self._exact_ship_list_search_var)
        search_entry.grid(row=0, column=1, sticky=tk.EW)
        self._bind_select_all_text(search_entry)
        self._exact_ship_list_search_var.trace_add("write", lambda *_: self._refresh_ship_list_rows())

        from tkinter import ttk
        cmdrs = set()
        for e in getattr(self, "_ship_list", []):
            if e.get("is_owned"):
                c = str(e.get("commander") or "").strip()
                if c:
                    cmdrs.add(c)
        cmdrs = sorted(cmdrs)
        active_cmdr = getattr(self, "current_commander", "")
        if active_cmdr and active_cmdr not in cmdrs:
            cmdrs.append(active_cmdr)
            cmdrs = sorted(cmdrs)

        options = ["Imported"] + cmdrs
        self._exact_ship_list_commander_var = tk.StringVar()
        saved_cmdr = config.get_str("spansh_exact_ship_list_commander", default="").strip()

        if saved_cmdr and saved_cmdr in options:
            self._exact_ship_list_commander_var.set(saved_cmdr)
        elif active_cmdr:
            self._exact_ship_list_commander_var.set(active_cmdr)
        elif cmdrs:
            self._exact_ship_list_commander_var.set(cmdrs[0])
        else:
            self._exact_ship_list_commander_var.set("Imported")

        cmdr_cmb = ttk.Combobox(search_frame, textvariable=self._exact_ship_list_commander_var, values=options, state="readonly", width=15)
        cmdr_cmb.grid(row=0, column=2, padx=(6, 0))

        def _clear_filtered_list():
            if not confirmDialog.askyesno("Clear List", "Remove all ships from the current list?\n(Current ship will be kept)", parent=win):
                return
            cmdr_filter = str(self._exact_ship_list_commander_var.get() or "Imported").strip()
            current_id = (getattr(self, "current_ship_loadout", None) or {}).get("ShipID")
            def _should_remove(e):
                if cmdr_filter == "Imported":
                    return not e.get("is_owned")
                return e.get("is_owned") and str(e.get("commander") or "").strip() == cmdr_filter
            self._ship_list[:] = [e for e in self._ship_list if not _should_remove(e) or (e.get("is_owned") and (e.get("loadout") or {}).get("ShipID") == current_id)]
            self._save_ship_list()
            self._refresh_ship_list_rows()

        clear_list_btn = tk.Button(search_frame, text="🗑", font=("", 10), width=3, padx=1, pady=0, bd=1, relief=tk.GROOVE, command=_clear_filtered_list)
        clear_list_btn.grid(row=0, column=3, padx=(4, 0))
        Tooltip(clear_list_btn, "Clear all ships from current list")

        def _on_cmdr_change(*_):
            config.set("spansh_exact_ship_list_commander", self._exact_ship_list_commander_var.get())
            self._refresh_ship_list_rows()

        self._exact_ship_list_commander_var.trace_add("write", _on_cmdr_change)

        dest_list_frame = tk.Frame(content)
        dest_list_frame.grid(row=3, column=0, sticky=tk.EW, padx=4, pady=(0, 8))
        dest_list_frame.columnconfigure(0, weight=1)
        dlw = DraggableListWidget(dest_list_frame, height=168, visible_rows=5)
        dlw.border.grid(row=0, column=0, sticky=tk.EW)
        dlw.set_items(getattr(self, "_ship_list", []))
        dlw.on_reorder = self._ship_list_on_reorder
        dlw.on_select = self._ship_list_on_select
        self._exact_ship_list_dlw = dlw

        self._ship_list_row_menu = tk.Menu(win, tearoff=0)
        self._ship_list_row_menu_entry = None
        self._ship_list_row_menu.add_command(label="Copy", command=lambda: self._ship_list_open_external("copy"))
        self._ship_list_row_menu.add_command(label="Copy SLEF", command=lambda: self._ship_list_open_external("copy_slef"))
        self._ship_list_row_menu.add_separator()
        self._ship_list_row_menu.add_command(label="Open in Coriolis", command=lambda: self._ship_list_open_external("coriolis"))
        self._ship_list_row_menu.add_command(label="Open in EDSY", command=lambda: self._ship_list_open_external("edsy"))


        self._exact_ship_list_count_lbl = tk.Label(content, text="", anchor=tk.E)
        self._exact_ship_list_count_lbl.grid(row=4, column=0, sticky=tk.E, padx=6, pady=(0, 2))

        btn_frame = tk.Frame(content)
        btn_frame.grid(row=5, column=0, pady=(0, 0))
        self._exact_ship_list_import_btn = tk.Button(btn_frame, text="Import Ship", width=12, command=self._show_exact_ship_import_dialog)
        self._exact_ship_list_import_btn.pack(side=tk.LEFT, padx=(0, 7))
        tk.Button(btn_frame, text="Export Ship", width=12, command=self._show_exact_ship_export_dialog).pack(
            side=tk.LEFT, padx=(0, 7))
        tk.Button(btn_frame, text="Select", width=12, command=self._ship_list_select_current).pack(
            side=tk.LEFT, padx=(0, 7))
        cancel_btn = tk.Button(btn_frame, text="Cancel", width=12)
        cancel_btn.pack(side=tk.LEFT)

        def _close_ship_list():
            self._destroy_exact_ship_dialog("_exact_ship_import_win")
            self._destroy_exact_ship_dialog("_exact_ship_export_win")
            self._close_exact_ship_dialog("_exact_ship_list_win", win)
            # Clear stale window-local references so a reopen starts fresh
            self._exact_ship_list_dlw = None
            self._exact_ship_list_current_frame = None
            self._exact_ship_list_search_var = None
            self._exact_ship_list_filtered = []
            self._exact_ship_list_commander_var = None
            self._exact_ship_list_count_lbl = None
            self._exact_ship_list_import_btn = None

        cancel_btn.config(command=_close_ship_list)
        win.protocol("WM_DELETE_WINDOW", _close_ship_list)
        self._refresh_ship_list_rows()
        win.after_idle(self._refresh_ship_list_rows)

        self._configure_child_window(win, host=self.plotter_win)

    def _notify_ship_list_full(self):
        win = self._live_exact_ship_dialog("_exact_ship_list_win")
        if win is None:
            return
        cmdr = getattr(self, "current_commander", "") or ""
        confirmDialog.showwarning(
            "Ship List Full",
            f"Commander list for '{cmdr}' is full ({SHIP_LIST_MAX_OWNED}).\n"
            "New ships will not be added automatically until a slot is freed.",
            parent=win,
        )

    def _ship_list_category_count(self, cmdr_filter=None):
        if cmdr_filter is None:
            cmdr_filter = str(getattr(self, "_exact_ship_list_commander_var", None)
                              and self._exact_ship_list_commander_var.get() or "Imported").strip()
        all_ships = getattr(self, "_ship_list", [])
        if cmdr_filter == "Imported":
            count = sum(1 for e in all_ships if not e.get("is_owned"))
            return count, SHIP_LIST_MAX_IMPORTED
        count = sum(1 for e in all_ships if e.get("is_owned") and str(e.get("commander") or "").strip() == cmdr_filter)
        return count, SHIP_LIST_MAX_OWNED

    def _update_ship_list_count_label(self):
        lbl = getattr(self, "_exact_ship_list_count_lbl", None)
        if lbl is None:
            return
        count, limit = self._ship_list_category_count()
        try:
            lbl.config(text=f"{count} / {limit}")
        except Exception:
            pass
        # Grey out Import button when the imported list is full
        import_btn = getattr(self, "_exact_ship_list_import_btn", None)
        if import_btn is not None:
            imported_count, imported_limit = self._ship_list_category_count("Imported")
            try:
                import_btn.config(state=tk.DISABLED if imported_count >= imported_limit else tk.NORMAL)
            except Exception:
                pass

    def _refresh_ship_list_current_row(self):
        frame = getattr(self, "_exact_ship_list_current_frame", None)
        if frame is None:
            return
        lbl = None
        for child in frame.winfo_children():
            if isinstance(child, tk.Label):
                lbl = child
                break

        if lbl is None:
            frame.columnconfigure(0, weight=1)
            lbl = tk.Label(frame, anchor=tk.W, cursor="hand2", padx=6, pady=3)
            lbl.grid(row=0, column=0, sticky=tk.EW, pady=0)
        for widget in (lbl, frame):
            widget.bind("<Button-1>", lambda _e: self._ship_list_focus_current_row())
            widget.bind("<Double-Button-1>", lambda _e: self._ship_list_select_current_ship())
            widget.bind("<Button-3>", lambda e: self._ship_list_show_menu(e, None, None))

        loadout = getattr(self, "current_ship_loadout", None) or {}
        name = self._exact_ship_display_name(loadout) or "No ship detected"

        dlw = getattr(self, "_exact_ship_list_dlw", None)
        is_current_active = (dlw is None or dlw.selected_index is None)
        try:
            normal_bg = self.plotter_win.cget("bg")
        except Exception:
            normal_bg = "SystemButtonFace"
        target_bg = "#a5c9ff" if is_current_active else normal_bg
        try:
            frame.config(bg=target_bg)
        except Exception:
            pass

        lbl.config(text=f"Current: {name}", bg=target_bg)

    def _sync_ship_list_dialogs(self, entry=None):
        export_win = self._live_exact_ship_dialog("_exact_ship_export_win")
        if export_win is not None:
            self._show_exact_ship_export_dialog()

        import_name_var = getattr(self, "_exact_ship_import_name_var", None)
        if import_name_var and self._live_exact_ship_dialog("_exact_ship_import_win"):
            import_name_var.set("" if entry is None else entry.get("name", ""))

    def _ship_list_selected_entry(self):
        dlw = getattr(self, "_exact_ship_list_dlw", None)
        filtered = getattr(self, "_exact_ship_list_filtered", [])
        if dlw is None or dlw.selected_index is None or not (0 <= dlw.selected_index < len(filtered)):
            return None
        return filtered[dlw.selected_index]

    def _ship_list_focus_current_row(self):
        """Single-click on current row: deselect DLW so export targets current ship."""
        dlw = getattr(self, "_exact_ship_list_dlw", None)
        if dlw is not None and dlw.selected_index is not None:
            dlw.set_selected_index(None, update_highlight=True)
        self._exact_imported_ship_loadout = None
        self._exact_imported_ship_fsd_data = None
        self._save_selected_ship_to_config(None)
        self._update_ship_list_highlights()
        self._sync_ship_list_dialogs()

    def _ship_list_select_current_ship(self):
        if self._is_plotting():
            return
        self._reset_exact_ship_to_current()
        win = self._live_exact_ship_dialog("_exact_ship_list_win")
        if win is not None:
            self._close_exact_ship_dialog("_exact_ship_list_win", win)

    def _ship_list_matches_filter(self, entry, query):
        if not query:
            return True
        q = query.lower()
        loadout = entry.get("loadout") or {}
        fields = [
            entry.get("name") or "",
            entry.get("ident") or "",
            entry.get("ship_type") or "",
            self._resolve_ship_type_display(entry.get("ship_type") or ""),
            loadout.get("ShipName") or "",
            loadout.get("ShipIdent") or "",
        ]
        return any(q in str(f).lower() for f in fields)

    def _build_ship_list_row(self, dlw, real_indices, index, entry, row_frame, row_bg):
        real_i = real_indices.get(id(entry), index)
        row_frame.columnconfigure(1, weight=1)
        tk.Label(row_frame, text=f"{index + 1}.", anchor=tk.W, bg=row_bg).grid(
            row=0, column=0, padx=(2, 4), pady=1, sticky=tk.W)

        full_display = self._ship_list_display_name(entry)
        display, needs_tooltip = truncate_text_px(full_display, 405)
        lbl = tk.Label(row_frame, text=display, anchor=tk.W, bg=row_bg, fg="black", cursor="hand2")
        lbl.grid(row=0, column=1, sticky=tk.W, pady=1, padx=(0, 4))
        if needs_tooltip:
            Tooltip(lbl, full_display)

        is_owned = entry.get("is_owned")
        edit_btn = tk.Button(row_frame, text="📝", width=2, padx=1, pady=0)
        edit_btn.grid(row=0, column=2, pady=1)
        del_btn = tk.Button(
            row_frame, text="🗑", width=2, padx=1, pady=0,
            command=lambda i=real_i: self._ship_list_delete(i),
        )
        del_btn.grid(row=0, column=3, pady=1, padx=(0, 4))
        is_current_ship = is_owned and (entry.get("loadout") or {}).get("ShipID") == (getattr(self, "current_ship_loadout", None) or {}).get("ShipID")
        if is_owned:
            edit_btn.config(state=tk.DISABLED)
            edit_tooltip = Tooltip(edit_btn, "Owned ships update from gameplay")
            if is_current_ship:
                del_btn.config(state=tk.DISABLED)
                Tooltip(del_btn, "Cannot delete current ship")
            else:
                Tooltip(del_btn, "Remove from list")
        else:
            edit_tooltip = Tooltip(edit_btn, "Edit")
            Tooltip(del_btn, "Remove from list")

        edit_btn.config(
            command=lambda i=real_i, r=row_frame, b=edit_btn, bg=row_bg, tt=edit_tooltip:
            self._ship_list_enter_edit(i, r, b, bg, tt)
        )

        for widget in (row_frame, lbl):
            dlw.bind_row_events(widget, index)
            widget.bind("<Double-Button-1>", lambda _e, i=real_i: self._ship_list_select_at(i), add="+")
            widget.bind("<Button-3>", lambda e, ent=entry, i=index: self._ship_list_show_menu(e, ent, i))
        for widget in (edit_btn, del_btn):
            dlw.bind_scroll_events(widget)

    def _refresh_ship_list_rows(self):
        win = self._live_exact_ship_dialog("_exact_ship_list_win")
        if win is None:
            return
        dlw = getattr(self, "_exact_ship_list_dlw", None)
        if dlw is None:
            return
        selected_entry = self._ship_list_selected_entry()
        query = str(getattr(self, "_exact_ship_list_search_var", None) and
                    self._exact_ship_list_search_var.get() or "").strip()
        cmdr_filter = str(getattr(self, "_exact_ship_list_commander_var", None) and
                          self._exact_ship_list_commander_var.get() or "Imported").strip()

        all_ships = getattr(self, "_ship_list", [])
        if cmdr_filter == "Imported":
            ships = [e for e in all_ships if not e.get("is_owned")]
        else:
            ships = [e for e in all_ships if e.get("is_owned") and str(e.get("commander") or "").strip() == cmdr_filter]
        ships.sort(key=lambda e: e.get("sort_order") if isinstance(e.get("sort_order"), (int, float)) else float('inf'))
        if query:
            ships = [e for e in ships if self._ship_list_matches_filter(e, query)]
        dlw.drag_enabled = not query

        self._exact_ship_list_filtered = ships
        dlw.set_items(ships)
        selected_id = id(selected_entry) if selected_entry is not None else None
        dlw.selected_index = next((i for i, e in enumerate(ships) if id(e) == selected_id), None)
        real_indices = {id(e): i for i, e in enumerate(all_ships)}

        self._refresh_draggable_rows(
            dlw,
            ships,
            lambda index, entry, row_frame, row_bg: self._build_ship_list_row(
                dlw, real_indices, index, entry, row_frame, row_bg,
            ),
        )
        self._refresh_ship_list_current_row()
        self._update_ship_list_count_label()
        self._sync_ship_list_dialogs(self._ship_list_selected_entry())

    def _ship_list_show_menu(self, event, entry, index=None):
        self._ship_list_row_menu_entry = entry
        if index is None:
            self._ship_list_focus_current_row()
        else:
            self._ship_list_on_select(index)

        cmdr_var = getattr(self, "_exact_ship_list_commander_var", None)
        is_imported_list = not cmdr_var or str(cmdr_var.get()).strip() == "Imported"
        try:
            self._ship_list_row_menu.delete("Copy to Imported")
        except Exception:
            pass
        if not is_imported_list:
            imported_count, imported_limit = self._ship_list_category_count("Imported")
            state = tk.DISABLED if imported_count >= imported_limit else tk.NORMAL
            self._ship_list_row_menu.insert_command(2, label="Copy to Imported", command=lambda: self._ship_list_copy_to_imported(), state=state)

        try:
            self._ship_list_row_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ship_list_row_menu.grab_release()

    def _ship_list_open_external(self, action):
        entry = self._ship_list_row_menu_entry
        loadout = self._active_exact_ship_loadout() if entry is None else entry.get("loadout")
        ship_name = self._exact_ship_display_name(loadout, include_ident=False)

        if action == "copy":
            self._copy_to_clipboard(ship_name)
        elif action == "copy_slef":
            try:
                export_payload = self._ship_export_payload(loadout)
                if export_payload:
                    self._copy_to_clipboard(json.dumps(export_payload, indent=4))
            except Exception as e:
                self._set_exact_error(f"Export failed: {str(e)}")
        elif action in ("coriolis", "edsy"):
            if not loadout:
                return
            import plug
            target_plugin = "Coriolis" if action == "coriolis" else "EDSY"
            is_beta = getattr(monitor, "is_beta", False)
            clean_loadout = self._sanitize_loadout_for_export(loadout)
            if "event" not in clean_loadout:
                clean_loadout["event"] = "Loadout"
            url = None
            try:
                url = plug.invoke(target_plugin, None, "shipyard_url", clean_loadout, is_beta)
            except Exception:
                logger.debug("Failed to invoke ship build plugin", exc_info=True)
            if url:
                import webbrowser
                webbrowser.open(url)

    def _ship_list_copy_to_imported(self):
        entry = self._ship_list_row_menu_entry
        if not entry or not entry.get("is_owned"):
            return
        loadout = entry.get("loadout")
        if not loadout:
            return
        import copy
        imported_loadout = copy.deepcopy(loadout)
        imported_loadout.pop("ShipID", None)
        if not self._ship_list_add(imported_loadout, is_owned=False):
            win = self._live_exact_ship_dialog("_exact_ship_list_win")
            confirmDialog.showwarning(
                "Ship List Full",
                f"Imported ship list is full ({SHIP_LIST_MAX_IMPORTED}).\nRemove a ship to make room.",
                parent=win or self.plotter_win,
            )
            return
        self._refresh_ship_list_rows()

    def _ship_list_enter_edit(self, index, row_frame, edit_btn, row_bg, edit_tooltip=None):
        ships = getattr(self, "_ship_list", [])
        if not (0 <= index < len(ships)):
            return
        for child in row_frame.grid_slaves(row=0, column=1):
            try:
                child.destroy()
            except Exception:
                pass
        current_name = str(ships[index].get("name") or "").strip()
        name_var = tk.StringVar(value=current_name)

        def _limit_name(*_):
            val = name_var.get()
            if len(val) > 64:
                name_var.set(val[:64])

        name_var.trace_add("write", _limit_name)
        entry = tk.Entry(row_frame, textvariable=name_var, bg=row_bg)
        entry.grid(row=0, column=1, sticky=tk.EW, pady=1, padx=(0, 4))
        self._bind_select_all_text(entry)
        entry.focus_set()
        entry.select_range(0, tk.END)

        if edit_tooltip is not None:
            edit_tooltip.text = "Save"
        edit_btn.config(
            text="✅",
            command=lambda i=index, v=name_var, e=entry: self._ship_list_save_edit(i, v, e),
        )
        entry.bind("<Return>", lambda _ev, i=index, v=name_var, e=entry: self._ship_list_save_edit(i, v, e))
        entry.bind("<Escape>", lambda _ev: self._refresh_ship_list_rows())

    def _ship_list_save_edit(self, index, name_var, entry):
        name = name_var.get().strip()
        if not name:
            try:
                entry.config(bg="#ffe0e0")
                Tooltip(entry, "Ship Name is required")
            except Exception:
                pass
            return

        if self._is_ship_name_duplicate(name, exclude_index=index):
            try:
                entry.config(bg="#ffe0e0")
                Tooltip(entry, f"Name '{name}' already exists")
            except Exception:
                pass
            return

        ships = getattr(self, "_ship_list", [])
        if not (0 <= index < len(ships)):
            return

        entry_meta = ships[index]
        loadout = entry_meta.get("loadout") or {}
        active_loadout = self._active_exact_ship_loadout()

        edited_key = self._ship_list_identity_key(entry_meta)
        active_key = self._ship_identity_key_str(
            active_loadout or {},
            commander=entry_meta.get("commander"),
            fallback_name=entry_meta.get("name", ""),
        )
        is_active = bool(edited_key and edited_key == active_key)

        ships[index]["name"] = name
        if isinstance(loadout, dict):
            loadout["ShipName"] = name
        self._save_ship_list()

        if is_active:
             if getattr(self, "_exact_imported_ship_loadout", None):
                 self._exact_imported_ship_loadout["ShipName"] = name
             self._save_selected_ship_to_config(loadout, commander=entry_meta.get("commander"))
             self._update_exact_ship_status_label()

        self._refresh_ship_list_rows()
        self._sync_ship_list_dialogs(self._ship_list_selected_entry())

    def _ship_list_on_reorder(self):
        dlw = getattr(self, "_exact_ship_list_dlw", None)
        if not dlw:
            return
        # Stamp new sort_order values onto the entries — no list rearrangement needed
        for i, entry in enumerate(getattr(dlw, "_items", [])):
            entry["sort_order"] = i
        self._save_ship_list()
        self._refresh_ship_list_rows()

    def _ship_list_on_select(self, index):
        dlw = getattr(self, "_exact_ship_list_dlw", None)
        if dlw is None:
            return
        dlw.set_selected_index(index, update_highlight=True, ensure_visible=True)
        self._update_ship_list_highlights()
        self._sync_ship_list_dialogs(self._ship_list_selected_entry())

    def _update_ship_list_highlights(self):
        dlw = getattr(self, "_exact_ship_list_dlw", None)
        if dlw is None or not hasattr(dlw, "_row_widgets") or not dlw._row_widgets:
            return

        current_frame = getattr(self, "_exact_ship_list_current_frame", None)
        if current_frame:
            is_current_active = (dlw.selected_index is None)
            try:
                n_bg = self.plotter_win.cget("bg")
            except Exception:
                n_bg = "SystemButtonFace"
            target_bg = "#a5c9ff" if is_current_active else n_bg
            try:
                current_frame.config(bg=target_bg)
                for child in current_frame.winfo_children():
                    if isinstance(child, tk.Label):
                        child.config(bg=target_bg)
            except Exception:
                pass

        dlw.update_selection_highlight()

    def _ship_list_delete(self, index):
        all_ships = getattr(self, "_ship_list", [])
        if not (0 <= index < len(all_ships)):
            return
        deleted_entry = all_ships[index]
        deleted_key = self._ship_list_identity_key(deleted_entry)
        active_loadout = self._active_exact_ship_loadout()
        active_key = self._ship_identity_key_str(
            active_loadout or {},
            commander=deleted_entry.get("commander"),
            fallback_name=str(deleted_entry.get("name") or "").strip(),
        )
        is_active = bool(deleted_key and deleted_key == active_key)

        all_ships.pop(index)
        self._save_ship_list()
        if is_active:
            self._reset_exact_ship_to_current()

        self._refresh_ship_list_rows()
        if is_active:
            self._update_ship_list_highlights()
            self._sync_ship_list_dialogs()
            return
        self._sync_ship_list_dialogs(self._ship_list_selected_entry())

    def _ship_list_select_at(self, index):
        if self._is_plotting():
            return
        ships = getattr(self, "_ship_list", [])
        if not (0 <= index < len(ships)):
            return
        loadout = ships[index].get("loadout")
        if not loadout:
            return
        try:
            self._apply_exact_ship_import(loadout, custom_name=ships[index].get("name"))
        except ValueError as exc:
            if hasattr(self, "exact_error_txt"):
                self._set_exact_error(str(exc))
            return
        self._save_selected_ship_to_config(loadout, commander=ships[index].get("commander"))
        win = self._live_exact_ship_dialog("_exact_ship_list_win")
        if win is not None:
            self._close_exact_ship_dialog("_exact_ship_list_win", win)

    def _get_ship_list_selected_real_index(self):
        entry = self._ship_list_selected_entry()
        if entry is None:
            return None
        return next((i for i, e in enumerate(getattr(self, "_ship_list", [])) if id(e) == id(entry)), None)

    def _show_import_choice_dialog(self, parent_win, payload, real_index, parent_error_var):
        popup = tk.Toplevel(parent_win)
        popup.withdraw()
        popup.title("Import Choice")
        popup.resizable(False, False)
        ship_name = self._ship_list_display_name(getattr(self, "_ship_list", [])[real_index])
        display_name, needs_choice_tooltip = truncate_text_px(ship_name, 450)
        lbl = tk.Label(
            popup,
            text=f"Updating: {display_name}\n\nDo you want to update the selected ship's data?",
            padx=20, pady=20, justify=tk.CENTER
        )
        lbl.pack()
        if needs_choice_tooltip:
            Tooltip(lbl, ship_name)
        btn_frame = tk.Frame(popup, pady=10, padx=10)
        btn_frame.pack()
        def update_selected():
            if self._import_exact_ship_from_payload(payload, error_var=parent_error_var, overwrite_index=real_index, custom_name=getattr(self, "_exact_ship_import_name", None)):
                self._close_exact_ship_dialog("_exact_ship_import_win", parent_win)
            popup.destroy()
        tk.Button(btn_frame, text="Update Selected", width=16, command=update_selected).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", width=12, command=popup.destroy).pack(side=tk.LEFT, padx=5)
        popup.transient(parent_win)
        popup.grab_set()
        self._position_child_window_next_to_host(popup, parent_win)
        popup.deiconify()

    def _ship_list_select_current(self):
        dlw = getattr(self, "_exact_ship_list_dlw", None)
        if dlw is None:
            return
        if dlw.selected_index is None:
            self._ship_list_select_current_ship()
            return
        real_index = self._get_ship_list_selected_real_index()
        if real_index is not None:
            self._ship_list_select_at(real_index)

    def _exact_ship_display_name(self, loadout=None, include_ident=True):
        loadout = loadout or self._active_exact_ship_loadout()
        if isinstance(loadout, dict):
            name = str(loadout.get("ShipName") or "").strip()
            ident = str(loadout.get("ShipIdent") or "").strip()
            ship_type = str(loadout.get("Ship") or "").strip()
        else:
            name = str(monitor.state.get("ShipName") or "").strip()
            ident = str(monitor.state.get("ShipIdent") or "").strip()
            ship_type = str(monitor.state.get("ShipType") or "").strip()

        base_name = name or (self._resolve_ship_type_display(ship_type) if ship_type else "")
        if base_name and ident and include_ident:
            return f"{base_name} [{ident}]"
        elif base_name:
            return base_name
        elif ident:
            return f"[{ident}]"
        return ""

    def _update_exact_ship_status_label(self):
        if not hasattr(self, "exact_fsd_status_lbl"):
            return
        ship_name = self._exact_ship_display_name()
        if not ship_name:
            return  # Keep last known label
        is_current = (not getattr(self, "_exact_imported_ship_loadout", None))
        display_base = f"Ship: {ship_name}"
        ship_status, needs_main_tooltip = truncate_text_px(display_base, 210)
        if is_current:
            ship_status += "\n(Current Ship)"
            full_status = display_base + "\n(Current Ship)"
        else:
            full_status = display_base
        ship_color = "green"
        if needs_main_tooltip:
            if not hasattr(self, "exact_fsd_status_lbl_tooltip"):
                self.exact_fsd_status_lbl_tooltip = Tooltip(self.exact_fsd_status_lbl, full_status)
            else:
                self.exact_fsd_status_lbl_tooltip.text = full_status
        elif hasattr(self, "exact_fsd_status_lbl_tooltip"):
            self.exact_fsd_status_lbl_tooltip.text = ""
        try:
            self.exact_fsd_status_lbl.config(text=ship_status, fg=ship_color)
        except Exception:
            pass

    def _apply_exact_ship_import(self, loadout, custom_name=None):
        self._apply_exact_ship_import_core(loadout, custom_name=custom_name)
        import_name_var = getattr(self, "_exact_ship_import_name_var", None)
        import_win = self._live_exact_ship_dialog("_exact_ship_import_win")
        if import_name_var and import_win:
            import_name_var.set(self._exact_ship_display_name(self._exact_imported_ship_loadout, include_ident=False))
            import_win.update_idletasks()
        self._update_exact_ship_status_label()
        self._update_cargo_button_state()
        cargo = getattr(self, "exact_cargo_entry", None)
        if cargo:
            try:
                if cargo.winfo_exists():
                    self._set_entry_value(cargo, "0")
            except Exception:
                pass

    def _import_exact_ship_from_payload(self, payload, *, error_var=None, overwrite_index=None, custom_name=None):
        try:
            self._import_exact_ship_from_payload_core(
                payload,
                overwrite_index=overwrite_index,
                custom_name=custom_name,
            )
        except ValueError as exc:
            if error_var is not None:
                error_var.set(str(exc))
                return False
            raise
        cmdr_var = getattr(self, "_exact_ship_list_commander_var", None)
        if cmdr_var is not None:
            cmdr_var.set("Imported")
        self._refresh_ship_list_rows()
        if error_var is not None:
            error_var.set("")
        return True

    def _reset_exact_ship_to_current(self):
        self._exact_imported_ship_loadout = None
        self._exact_imported_ship_fsd_data = None
        self._clear_selected_ship_config()
        if not self.ship_fsd_data:
            self._detect_fsd_from_monitor()
        import_name_var = getattr(self, "_exact_ship_import_name_var", None)
        if import_name_var and self._live_exact_ship_dialog("_exact_ship_import_win"):
            import_name_var.set("")
        self._update_exact_ship_status_label()
        self._update_cargo_button_state()
        cargo = getattr(self, "exact_cargo_entry", None)
        if cargo:
            try:
                if cargo.winfo_exists():
                    self._fill_cargo_from_current(cargo, force=True)
            except Exception:
                pass
        if hasattr(self, "exact_error_txt"):
            self._set_exact_error("")

    def _live_exact_ship_dialog(self, attr_name):
        window = getattr(self, attr_name, None)
        if not window:
            return None
        try:
            if window.winfo_exists():
                return window
        except Exception:
            pass
        setattr(self, attr_name, None)
        return None

    def _close_exact_ship_dialog(self, attr_name, window):
        if getattr(self, attr_name, None) is window:
            setattr(self, attr_name, None)
        try:
            window.destroy()
        except Exception:
            pass

    def _destroy_exact_ship_dialog(self, attr_name):
        window = self._live_exact_ship_dialog(attr_name)
        if window is None:
            return
        self._close_exact_ship_dialog(attr_name, window)

    def _position_child_window_below_host(self, window, host):
        """Position window below host, fallback above if not enough screen space."""
        try:
            window.update_idletasks()
            host.update_idletasks()
        except Exception:
            pass
        try:
            host_x = int(host.winfo_rootx())
            host_y = int(host.winfo_rooty())
            host_height = max(1, int(host.winfo_height()))
            child_width = max(1, int(window.winfo_reqwidth() or window.winfo_width()))
            child_height = max(1, int(window.winfo_reqheight() or window.winfo_height()))
            screen_width = max(1, int(window.winfo_screenwidth()))
            screen_height = max(1, int(window.winfo_screenheight()))
        except Exception:
            return
        margin = 8
        desired_y = host_y + host_height + margin
        if desired_y + child_height > screen_height:
            desired_y = max(0, host_y - child_height - margin)
        desired_x = host_x
        if desired_x + child_width > screen_width:
            desired_x = max(0, screen_width - child_width - margin)
        try:
            window.geometry(f"+{int(desired_x)}+{int(desired_y)}")
        except Exception:
            pass

    def _finalize_exact_ship_dialog(self, window, size=None):
        width, height = size or self._EXACT_SHIP_DIALOG_SIZE
        try:
            window.resizable(False, False)
            window.geometry(f"{width}x{height}")
            window.minsize(width, height)
            window.maxsize(width, height)
        except Exception:
            pass
        ship_list_win = self._live_exact_ship_dialog("_exact_ship_list_win")
        if ship_list_win is not None:
            self._configure_child_window(window, host=ship_list_win, position_fn=self._position_child_window_below_host)
        else:
            self._configure_child_window(window, host=self.plotter_win)

    def _show_exact_ship_import_dialog(self):
        if self._plotter_window_kind != "Exact Plotter" or not getattr(self, "plotter_win", None):
            return
        existing = self._live_exact_ship_dialog("_exact_ship_import_win")
        if existing is not None:
            self._raise_child_window(existing)
            return
        other = self._live_exact_ship_dialog("_exact_ship_export_win")
        if other is not None:
            self._close_exact_ship_dialog("_exact_ship_export_win", other)
        win = tk.Toplevel(self.plotter_win)
        win.withdraw()
        self._exact_ship_import_win = win
        win.title("Import Ship")
        tk.Label(
            win,
            text="Paste ship JSON/SLEF text below or import a JSON file.",
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=8, pady=(8, 4))

        selected_entry = self._ship_list_selected_entry()
        default_name = "" if selected_entry is None else selected_entry.get("name", "")

        name_var = tk.StringVar()
        self._exact_ship_import_name_var = name_var

        def _limit_import_name(*_):
            val = name_var.get()
            if len(val) > 80:
                name_var.set(val[:80])
            self._exact_ship_import_name = name_var.get()

        name_var.trace_add("write", _limit_import_name)

        name_var.set(default_name)
        self._exact_ship_import_name = default_name

        name_frame = tk.Frame(win)
        name_frame.grid(row=1, column=0, columnspan=3, sticky=tk.EW, padx=8, pady=(0, 4))
        name_frame.grid_columnconfigure(1, weight=1)

        tk.Label(name_frame, text="Ship Name*:").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        name_entry = tk.Entry(name_frame, textvariable=name_var)
        name_entry.grid(row=0, column=1, sticky=tk.EW)
        self._bind_select_all_text(name_entry)

        text = tk.Text(win, wrap=tk.WORD, height=8, width=72, font=("", 9))
        text.grid(row=2, column=0, columnspan=3, padx=8, pady=4, sticky=tk.NSEW)
        win.grid_columnconfigure(0, weight=1)
        win.grid_columnconfigure(1, weight=1)
        win.grid_columnconfigure(2, weight=1)
        win.grid_rowconfigure(2, weight=1)

        def _auto_fill_name_from_paste():
            try:
                raw = text.get("1.0", tk.END).strip()
                if not raw:
                    return
                payload = json.loads(raw)
                item = self._ship_loadout_from_import_payload(payload)
                if not isinstance(item, dict):
                    return
                ship_name = str(item.get("ShipName") or "").strip()
                if ship_name and not name_var.get().strip():
                    name_var.set(ship_name)
            except Exception:
                pass

        from .widgets import bind_select_all_and_paste
        bind_select_all_and_paste(text, on_after_paste=_auto_fill_name_from_paste)

        def _text_copy_all():
            content = text.get("1.0", tk.END).strip()
            if content:
                self._copy_to_clipboard(content)

        def _text_cut_all():
            _text_copy_all()
            text.delete("1.0", tk.END)

        text_menu = tk.Menu(text, tearoff=0)
        text_menu.add_command(label="Cut", command=_text_cut_all)
        text_menu.add_command(label="Copy", command=_text_copy_all)
        def _text_paste_replace():
            try:
                content = text.clipboard_get()
            except Exception:
                return
            text.delete("1.0", tk.END)
            text.insert("1.0", content)
            text.after_idle(_auto_fill_name_from_paste)

        text_menu.add_command(label="Paste", command=_text_paste_replace)
        text.bind("<ButtonRelease-3>", lambda e: text_menu.tk_popup(e.x_root, e.y_root))

        error_var = tk.StringVar()
        error_lbl = tk.Label(win, textvariable=error_var, fg="red", wraplength=520, justify=tk.LEFT)
        error_lbl.grid(row=3, column=0, columnspan=3, sticky=tk.W, padx=8, pady=(0, 1))
        error_lbl.grid_remove()

        def set_error(message):
            error_var.set(message or "")
            (error_lbl.grid if message else error_lbl.grid_remove)()

        def _run_import_with_choice(payload, is_file_json=False):
            try:
                if "coriolis.io" in json.dumps(payload).lower():
                    set_error("Coriolis is not supported yet.")
                    return
            except Exception:
                pass

            item = self._ship_loadout_from_import_payload(payload)
            if not isinstance(item, dict):
                item = payload[0] if isinstance(payload, (list, tuple)) and payload else payload

            payload_name = str(item.get("ShipName") or "").strip()
            field_name = name_var.get().strip()
            target_name = (payload_name or field_name) if is_file_json else (field_name or payload_name)
            if is_file_json and payload_name and payload_name != field_name:
                name_var.set(payload_name)

            if not target_name:
                set_error("Ship Name is required.")
                return

            search_name = target_name.lower()
            duplicate_idx = next(
                (
                    i for i, ship in enumerate(getattr(self, "_ship_list", []))
                    if not ship.get("is_owned") and str(ship.get("name") or "").strip().lower() == search_name
                ),
                None,
            )

            self._exact_ship_import_name = target_name

            if duplicate_idx is not None:
                self._show_import_choice_dialog(win, payload, duplicate_idx, error_var)
                return

            if self._import_exact_ship_from_payload(payload, error_var=error_var, custom_name=target_name):
                self._close_exact_ship_dialog("_exact_ship_import_win", win)
            else:
                set_error(error_var.get())

        def import_from_text():
            raw = text.get("1.0", tk.END).strip()
            if not raw:
                set_error("Paste ship JSON or SLEF text.")
                return
            try:
                payload = json.loads(raw)
            except ValueError:
                set_error("Ship import text must be valid JSON.")
                return
            _run_import_with_choice(payload)

        def import_from_json():
            initial_dir = getattr(self, "_spansh_ship_dir", None) or os.path.expanduser("~")
            filename = filedialog.askopenfilename(
                parent=win,
                title="Import Ship JSON",
                initialdir=initial_dir,
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            )
            if not filename:
                return
            self._spansh_ship_dir = os.path.dirname(filename)
            try:
                with open(filename, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception:
                set_error("Selected file is not valid JSON.")
                return
            _run_import_with_choice(payload, is_file_json=True)

        button_frame = tk.Frame(win)
        button_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, padx=8, pady=(1, 8))
        for column in range(3):
            button_frame.grid_columnconfigure(column, weight=1, uniform="exact-ship-dialog-buttons")

        tk.Button(button_frame, text="Import Text", width=12, command=import_from_text).grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
        tk.Button(button_frame, text="Import JSON", width=12, command=import_from_json).grid(row=0, column=1, sticky=tk.EW, padx=4)
        tk.Button(button_frame, text="Cancel", width=12, command=lambda: self._close_exact_ship_dialog("_exact_ship_import_win", win)).grid(row=0, column=2, sticky=tk.EW, padx=(8, 0))
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_exact_ship_dialog("_exact_ship_import_win", win))
        self._finalize_exact_ship_dialog(win)

    def _export_dialog_loadout(self):
        """Return the loadout to export: selected in ship list, or active ship."""
        real_idx = self._get_ship_list_selected_real_index()
        if real_idx is not None:
            ships = getattr(self, "_ship_list", [])
            if 0 <= real_idx < len(ships):
                return ships[real_idx].get("loadout")
        loadout = self._active_exact_ship_loadout()
        if not loadout:
            self._detect_fsd_from_monitor()
            loadout = self._active_exact_ship_loadout()
        return loadout

    def _show_exact_ship_export_dialog(self):
        other = self._live_exact_ship_dialog("_exact_ship_import_win")
        if other is not None:
            self._close_exact_ship_dialog("_exact_ship_import_win", other)
        if self._plotter_window_kind != "Exact Plotter" or not getattr(self, "plotter_win", None):
            return

        loadout = self._export_dialog_loadout()
        payload = self._ship_export_payload(loadout)

        existing = self._live_exact_ship_dialog("_exact_ship_export_win")
        if existing is not None:
            if getattr(self, "_exact_ship_export_text", None) is not None and payload is not None:
                try:
                    new_text = json.dumps(payload, indent=4)
                    self._exact_ship_export_text.config(state=tk.NORMAL)
                    self._exact_ship_export_text.delete("1.0", tk.END)
                    self._exact_ship_export_text.insert("1.0", new_text)
                    self._exact_ship_export_text.config(state=tk.DISABLED)
                    self._exact_ship_export_payload = new_text
                except Exception:
                    pass
            if getattr(self, "_exact_ship_export_title_lbl", None) is not None:
                try:
                    self._exact_ship_export_title_lbl.config(text=f"{self._exact_ship_display_name(loadout)} SLEF")
                except Exception:
                    pass
            self._raise_child_window(existing)
            return
        if not payload:
            if hasattr(self, "exact_error_txt"):
                self._set_exact_error("No ship data available to export.")
            return

        slef_text = json.dumps(payload, indent=4)
        self._exact_ship_export_payload = slef_text

        win = tk.Toplevel(self._live_exact_ship_dialog("_exact_ship_list_win") or self.plotter_win)
        win.withdraw()
        self._exact_ship_export_win = win
        win.title("Export Ship")
        display_name = self._exact_ship_display_name(loadout)
        self._exact_ship_export_title_lbl = tk.Label(win, text=f"{display_name} SLEF", justify=tk.LEFT, anchor="w", wraplength=330)
        self._exact_ship_export_title_lbl.grid(row=0, column=0, sticky=tk.W, padx=8, pady=(8, 4))
        tk.Button(
            win,
            text="Copy",
            font=("", 8),
            padx=1,
            pady=1,
            command=lambda: self._copy_to_clipboard(getattr(self, "_exact_ship_export_payload", slef_text)),
        ).grid(row=0, column=1, sticky=tk.E, padx=8)

        text_frame = tk.Frame(win)
        text_frame.grid(row=1, column=0, columnspan=2, padx=8, pady=4, sticky=tk.NSEW)
        text_frame.grid_columnconfigure(0, weight=1)
        text = tk.Text(text_frame, wrap=tk.WORD, height=8, width=72, font=("", 9))
        text.grid(row=0, column=0, sticky=tk.NSEW)
        text.insert("1.0", slef_text)
        try:
            text.config(state=tk.DISABLED)
        except Exception:
            pass
        win.grid_columnconfigure(0, weight=1)
        win.grid_columnconfigure(1, weight=1)
        win.grid_rowconfigure(1, weight=1)
        text_frame.grid_rowconfigure(0, weight=1)
        self._exact_ship_export_text = text
        self._bind_select_all_text(text)

        error_var = tk.StringVar()
        error_lbl = tk.Label(win, textvariable=error_var, fg="red", wraplength=430, justify=tk.LEFT)
        error_lbl.grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=8, pady=(0, 1))
        error_lbl.grid_remove()

        def set_error(message):
            error_var.set(message or "")
            (error_lbl.grid if message else error_lbl.grid_remove)()

        def export_json():
            current_payload = getattr(self, "_exact_ship_export_payload", slef_text)
            try:
                current_data = json.loads(current_payload)
            except Exception:
                current_data = payload
            try:
                data_entry = current_data[0]["data"] if isinstance(current_data, list) and current_data else current_data
                ship_name = self._sanitize_export_name_token(self._exact_ship_display_name(data_entry), default="ship")
            except Exception:
                ship_name = "ship"

            initial_dir = getattr(self, "_spansh_ship_dir", None) or os.path.expanduser("~")
            filename = filedialog.asksaveasfilename(
                parent=win,
                title="Export Ship JSON",
                initialdir=initial_dir,
                initialfile=f"{ship_name}.json",
                defaultextension=".json",
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            )
            if not filename:
                return
            self._spansh_ship_dir = os.path.dirname(filename)
            try:
                with open(filename, "w", encoding="utf-8") as handle:
                    json.dump(self._sanitize_loadout_for_export(current_data), handle, indent=4)
            except Exception as e:
                set_error(f"Failed to export ship JSON: {str(e)}")
                return
            set_error("")

        button_frame = tk.Frame(win)
        button_frame.grid(row=3, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=(1, 8))
        for column in range(2):
            button_frame.grid_columnconfigure(column, weight=1, uniform="exact-ship-dialog-buttons")

        tk.Button(button_frame, text="Export to JSON", width=12, command=export_json).grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
        tk.Button(button_frame, text="Close", width=12, command=lambda: self._close_exact_ship_dialog("_exact_ship_export_win", win)).grid(row=0, column=1, sticky=tk.EW, padx=(8, 0))
        def _on_export_close():
            self._exact_ship_export_text = None
            self._exact_ship_export_title_lbl = None
            self._exact_ship_export_payload = None
            self._close_exact_ship_dialog("_exact_ship_export_win", win)

        win.protocol("WM_DELETE_WINDOW", _on_export_close)
        self._finalize_exact_ship_dialog(win)


# --- Shared Plotter Methods ---

    # -- Shared Route State --

    def _reset_for_new_route(self):
        self._close_csv_viewer_if_open()
        self.clear_route(show_dialog=False)

    def _finalize_applied_route(self, *, update_overlay=False):
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
        highlight_bg = "#a5c9ff"
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

    def _with_destination_not_found_tip(self, message):
        message = str(message or "")
        lowered = message.lower()
        if (
            "could not find" in lowered
            and ("destination system" in lowered or "finishing system" in lowered)
            and "tip: plot a route to this system in game" not in lowered
        ):
            return (
                f"{message}\n"
                "Tip: Plot a route to this system in game\n"
                "to log it in Spansh, then try again."
            )
        return message

    def _mark_widget_text_error(self, widget):
        try:
            if widget is not None and widget.winfo_exists():
                if hasattr(widget, "set_error_style"):
                    widget.set_error_style()
                else:
                    widget.config(fg="red")
        except Exception:
            pass

    def _spansh_incomplete_warning(self, payload):
        result = payload.get("result", payload) if isinstance(payload, dict) else {}
        if isinstance(result, dict) and result.get("incomplete"):
            return "Could not generate route, closest found returned."
        return None

    def _show_spansh_warning(self, message, title="Warning"):
        if not message:
            return
        parent = None
        try:
            if self.plotter_win and self.plotter_win.winfo_exists():
                parent = self.plotter_win
        except Exception:
            parent = None
        try:
            confirmDialog.showwarning(title, message, parent=parent or self.parent)
        except Exception:
            pass

    def _set_exact_error(self, message):
        message = self._with_destination_not_found_tip(message)
        target = getattr(self, "exact_error_txt", None)
        if target is not None:
            try:
                target.set(message)
                return
            except Exception:
                pass
        if message and self._plotter_window_kind != "Exact Plotter":
            self.show_error(message)

    def _set_exploration_error(self, message):
        message = self._with_destination_not_found_tip(message)
        target = getattr(self, "_exp_error_txt", None)
        if target is not None:
            try:
                target.set(message)
                return
            except Exception:
                pass
        if message and self._plotter_window_kind not in (
            "Road to Riches",
            "Ammonia World Route",
            "Earth-like World Route",
            "Rocky/HMC Route",
            "Exomastery",
        ):
            self.show_error(message)

    def _set_fleet_error(self, message):
        message = self._with_destination_not_found_tip(message)
        target = getattr(self, "_fc_error_txt", None)
        if target is not None:
            try:
                target.set(message)
                return
            except Exception:
                pass
        if message and self._plotter_window_kind != "Fleet Carrier Router":
            self.show_error(message)

    # -- Plotter Window --

    def _build_plotter_window(
        self,
        *,
        title,
        close_command,
        minsize=(300, 0),
        content_padding=(5, 2),
        content_column_weights=(1,),
    ):
        window = tk.Toplevel(self.parent)
        window.withdraw()
        self.plotter_win = window
        window.title(title)
        window.resizable(False, False)
        if minsize is not None:
            window.minsize(*minsize)
        window.columnconfigure(0, weight=1)
        window.protocol("WM_DELETE_WINDOW", close_command)

        content = tk.Frame(window)
        content.grid(row=0, column=0, padx=content_padding[0], pady=content_padding[1], sticky=tk.NSEW)
        for index, weight in enumerate(content_column_weights):
            content.columnconfigure(index, weight=weight)

        return window, content

    def _build_plotter_sections(self, parent, *, row, sections):
        # Unified sections
        def build_system_autocomplete_section(
            *,
            current_row,
            label_text,
            placeholder,
            attr_name,
            width,
            settings=None,
            settings_key=None,
            use_current_button=False,
            use_current_fallback=False,
            columnspan=2,
            padx=5,
            entry_pady=(0, 6),
        ):
            header = tk.Frame(parent)
            header.grid(row=current_row, column=0, columnspan=columnspan, sticky=tk.EW, padx=padx, pady=2)
            header.columnconfigure(0, weight=1)
            tk.Label(header, text=label_text).grid(row=0, column=0, sticky=tk.W)
            if use_current_button:
                def use_current_system():
                    sys_name = str(monitor.state.get("SystemName") or "").strip()
                    if not sys_name:
                        return
                    widget = getattr(self, attr_name, None)
                    if widget is not None:
                        widget.set_text(sys_name, False)

                button = tk.Button(header, text="🌠", padx=2, pady=2, command=use_current_system)
                button.grid(row=0, column=1, sticky=tk.E)
                Tooltip(button, "Use Current System")
            current_row += 1

            widget = AutoCompleter(parent, placeholder, width=width)
            setattr(self, attr_name, widget)
            widget.grid(
                row=current_row,
                column=0,
                columnspan=columnspan,
                padx=padx,
                pady=entry_pady,
                sticky=tk.EW,
            )

            value = None
            if settings_key and settings:
                value = settings.get(settings_key)
            if not value and use_current_fallback:
                value = self._last_source_system or monitor.state.get("SystemName")
            if value:
                widget.set_text(value, False)
            return current_row + 2

        def add_source_section(
            *,
            current_row,
            attr_name,
            width=None,
            settings=None,
            settings_key="source",
            layout="full",
        ):
            if layout == "single":
                width = 34 if width is None else width
                columnspan = 1
                padx = 4
            else:
                width = 30 if width is None else width
                columnspan = 2
                padx = 5
            return build_system_autocomplete_section(
                current_row=current_row,
                label_text="Source System:",
                placeholder="Source System",
                attr_name=attr_name,
                width=width,
                settings=settings,
                settings_key=settings_key,
                use_current_button=True,
                use_current_fallback=True,
                columnspan=columnspan,
                padx=padx,
            )

        def add_destination_section(
            *,
            current_row,
            attr_name,
            width=None,
            settings=None,
            settings_key="destination",
            label_text="Destination System:",
            layout="full",
        ):
            if layout == "single":
                width = 34 if width is None else width
                columnspan = 1
                padx = 4
            else:
                width = 30 if width is None else width
                columnspan = 2
                padx = 5
            return build_system_autocomplete_section(
                current_row=current_row,
                label_text=label_text,
                placeholder="Destination System",
                attr_name=attr_name,
                width=width,
                settings=settings,
                settings_key=settings_key,
                columnspan=columnspan,
                padx=padx,
            )

        def add_range_section(*, current_row, attr_name, planner):
            range_frame = tk.Frame(parent)
            range_frame.grid(row=current_row, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=2)
            tk.Label(range_frame, text="Range (LY):").pack(side=tk.LEFT)
            range_help = tk.Label(
                range_frame,
                text="?",
                font=("", 8),
                fg="blue",
                cursor="question_arrow",
                relief=tk.RAISED,
                borderwidth=1,
                padx=2,
            )
            range_help.pack(side=tk.LEFT, padx=(4, 0))
            Tooltip(
                range_help,
                "The current jump range of your ship. It will be autofilled with current or last known jump range.",
            )

            range_entry = tk.Spinbox(
                range_frame,
                from_=0,
                to=100,
                increment=1,
                format="%.2f",
                width=10,
            )
            self._setup_spinbox(range_entry, allow_float=True, maximum_decimals=2)
            range_entry.delete(0, tk.END)
            range_entry.pack(side=tk.RIGHT, padx=(0, 2))

            range_refresh_btn = tk.Button(
                range_frame,
                text="🔄",
                padx=2,
                pady=2,
                command=lambda w=range_entry: self._fill_range_from_current(w),
            )
            range_refresh_btn.pack(side=tk.RIGHT, padx=(0, 2))
            Tooltip(
                range_refresh_btn,
                "Recalculate jump range from current ship.\nCould be stale if game is not running.",
            )
            self._prefill_range_entry(range_entry, planner=planner)
            setattr(self, attr_name, range_entry)
            return current_row + 1

        def add_labeled_spinbox_row(
            *,
            current_row,
            label_text,
            help_text,
            attr_name,
            from_,
            to,
            initial_value,
            integer=True,
            allow_float=False,
            maximum_decimals=2,
        ):
            label_frame = tk.Frame(parent)
            label_frame.grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=2)
            tk.Label(label_frame, text=label_text).pack(side=tk.LEFT)
            help_lbl = tk.Label(
                label_frame,
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

            spinbox = tk.Spinbox(parent, from_=from_, to=to, width=10)
            self._setup_spinbox(
                spinbox,
                integer=integer,
                allow_float=allow_float,
                maximum_decimals=maximum_decimals,
            )
            spinbox.delete(0, tk.END)
            spinbox.insert(0, str(initial_value))
            spinbox.grid(row=current_row, column=1, padx=(10, 5), pady=2, sticky=tk.E)
            setattr(self, attr_name, spinbox)
            return spinbox

        # Exact sections
        def add_exact_options_section(*, current_row):
            cargo_frame = tk.Frame(parent)
            cargo_frame.grid(row=current_row, columnspan=2, sticky=tk.EW, padx=5, pady=2)
            tk.Label(cargo_frame, text="Cargo:").pack(side=tk.LEFT)
            self.exact_cargo_entry = tk.Spinbox(cargo_frame, from_=0, to=9999, width=7, validate="key")
            self._setup_spinbox(self.exact_cargo_entry, integer=True)
            self.exact_cargo_entry.pack(side=tk.RIGHT, padx=(0, 2))
            is_current_ship = not getattr(self, "_exact_imported_ship_loadout", None)
            cargo_refresh_btn = tk.Button(
                cargo_frame,
                text="🔄",
                padx=2,
                pady=2,
                command=lambda: self._fill_cargo_from_current(self.exact_cargo_entry, force=True),
                state=tk.NORMAL if is_current_ship else tk.DISABLED,
            )
            cargo_refresh_btn.pack(side=tk.RIGHT, padx=(0, 2))
            self._exact_cargo_refresh_btn = cargo_refresh_btn
            self._exact_cargo_refresh_tooltip = Tooltip(
                cargo_refresh_btn,
                "Get current cargo" if is_current_ship else "Get current cargo\n(Not possible with manually selected ships)",
            )
            exact_saved = self._settings_for_planner("Exact Plotter")
            if exact_saved.get("cargo") is not None:
                self.exact_cargo_entry.delete(0, tk.END)
                self.exact_cargo_entry.insert(0, str(exact_saved["cargo"]))
            elif self._cargo_prefill_ready:
                self._fill_cargo_from_current(self.exact_cargo_entry)
            current_row += 1

            reserve_frame = tk.Frame(parent)
            reserve_frame.grid(row=current_row, columnspan=2, sticky=tk.EW, padx=5, pady=2)
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
            Tooltip(reserve_help, "Reserve an amount of fuel that the router will not use for jumping.")
            self.exact_reserve_entry = tk.Spinbox(
                reserve_frame,
                from_=0,
                to=32,
                width=7,
                increment=1,
                format="%.2f",
            )
            self._setup_spinbox(self.exact_reserve_entry, allow_float=True)
            self.exact_reserve_entry.pack(side=tk.RIGHT, padx=(0, 2))
            if exact_saved.get("reserve") is not None:
                self.exact_reserve_entry.delete(0, tk.END)
                self.exact_reserve_entry.insert(0, str(exact_saved["reserve"]))
            current_row += 1

            super_val = exact_saved.get("is_supercharged")
            if super_val is None:
                super_val = bool(getattr(self, "is_supercharged", False))
            self.exact_is_supercharged = tk.BooleanVar(value=bool(super_val))
            self.exact_use_supercharge = tk.BooleanVar(value=exact_saved.get("use_supercharge", True))
            self.exact_use_injections = tk.BooleanVar(value=exact_saved.get("use_injections", False))
            self.exact_exclude_secondary = tk.BooleanVar(value=exact_saved.get("exclude_secondary", False))
            self.exact_refuel_every_scoopable = tk.BooleanVar(
                value=exact_saved.get("refuel_every_scoopable", True)
            )

            def add_checkbox_row(text, variable, tooltip, checkbox_row):
                frame = tk.Frame(parent)
                frame.grid(row=checkbox_row, columnspan=2, sticky=tk.W, padx=5)
                tk.Checkbutton(frame, text=text, variable=variable).pack(side=tk.LEFT)
                lbl = tk.Label(
                    frame,
                    text="?",
                    font=("", 8),
                    fg="blue",
                    cursor="question_arrow",
                    relief=tk.RAISED,
                    borderwidth=1,
                    padx=2,
                )
                lbl.pack(side=tk.LEFT, padx=(4, 0))
                Tooltip(lbl, tooltip)

            add_checkbox_row(
                "Already Supercharged",
                self.exact_is_supercharged,
                "Is your ship already supercharged?",
                current_row,
            )
            current_row += 1
            add_checkbox_row(
                "Use Supercharge",
                self.exact_use_supercharge,
                "Use neutron stars to supercharge your FSD.",
                current_row,
            )
            current_row += 1
            add_checkbox_row(
                "Use FSD Injections",
                self.exact_use_injections,
                "Use FSD synthesis to boost when a neutron star is not available.",
                current_row,
            )
            current_row += 1
            add_checkbox_row(
                "Exclude Secondary Stars",
                self.exact_exclude_secondary,
                "Prevent using secondary neutron and scoopable stars to help with the route.",
                current_row,
            )
            current_row += 1
            add_checkbox_row(
                "Refuel Every Scoopable",
                self.exact_refuel_every_scoopable,
                "Refuel every time you encounter a scoopable star.",
                current_row,
            )
            current_row += 1

            algo_frame = tk.Frame(parent)
            algo_frame.grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=2)
            tk.Label(algo_frame, text="Routing Algorithm:").pack(side=tk.LEFT)
            algo_help = tk.Label(
                algo_frame,
                text="?",
                font=("", 8),
                fg="blue",
                cursor="question_arrow",
                relief=tk.RAISED,
                borderwidth=1,
                padx=2,
            )
            algo_help.pack(side=tk.LEFT, padx=(4, 0))
            Tooltip(
                algo_help,
                "Which routing algorithm to use. Different algorithms may work faster, find better routes, or in some cases be unable to find a route.",
            )

            self.exact_algorithm = tk.StringVar(
                value=exact_saved.get("algorithm", "optimistic") if exact_saved else "optimistic"
            )
            algorithms = ["fuel", "fuel_jumps", "guided", "optimistic", "pessimistic"]
            algo_sel_frame = tk.Frame(parent)
            algo_sel_frame.grid(row=current_row, column=1, padx=5, pady=2, sticky=tk.W)
            self.exact_algo_menu = tk.OptionMenu(algo_sel_frame, self.exact_algorithm, *algorithms)
            self.exact_algo_menu.config(width=12)
            self.exact_algo_menu.pack(side=tk.LEFT)
            algo_sel_help = tk.Label(
                algo_sel_frame,
                text="?",
                font=("", 8),
                fg="blue",
                cursor="question_arrow",
                relief=tk.RAISED,
                borderwidth=1,
                padx=2,
            )
            algo_sel_help.pack(side=tk.LEFT, padx=(4, 0))

            self._algo_descriptions = {
                "fuel": "Prioritises saving fuel, will not scoop or supercharge. Makes the smallest jumps possible to preserve fuel.",
                "fuel_jumps": "Prioritises saving fuel with minimised jumps. Attempts to use the entire fuel tank efficiently. May run out of fuel on very long routes.",
                "guided": "Follows a standard Neutron Plotter route as a guide. Penalises routes that diverge more than 100 LY. May time out in sparse regions.",
                "optimistic": "Prioritises neutron jumps. Penalises areas with large gaps between neutron stars. Typically the fastest route with fewest total jumps.",
                "pessimistic": "Prioritises calculation speed. Overestimates average star distance. Calculates faster but routes are typically less optimal.",
            }
            self._algo_sel_tooltip = Tooltip(
                algo_sel_help,
                self._algo_descriptions.get(self.exact_algorithm.get(), ""),
            )
            self.exact_algorithm.trace_add("write", lambda *_: self._update_algo_tooltip())
            return current_row + 1

        def add_exact_ship_section(*, current_row):
            ship_frame = tk.Frame(parent)
            ship_frame.grid(row=current_row, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=5)
            ship_frame.grid_columnconfigure(0, weight=1, uniform="exact-ship-status")
            ship_frame.grid_columnconfigure(2, weight=1, uniform="exact-ship-status")
            ship_button_gutter = tk.Frame(ship_frame, width=26, height=1)
            ship_button_gutter.grid(row=0, column=0, sticky=tk.E)
            ship_button_gutter.grid_propagate(False)
            self.exact_fsd_status_lbl = tk.Label(ship_frame)
            self.exact_fsd_status_lbl.grid(row=0, column=1)
            refresh_wrap = tk.Frame(ship_frame)
            refresh_wrap.grid(row=0, column=2, sticky=tk.E, padx=(6, 2))
            refresh_btn = tk.Button(
                refresh_wrap,
                text="🔄",
                padx=2,
                pady=2,
                command=self._reset_exact_ship_to_current,
            )
            refresh_btn.pack(padx=2, pady=2)
            Tooltip(refresh_btn, "Use Current Ship")
            self._update_exact_ship_status_label()
            current_row += 1

            tk.Button(parent, text="Ship List", width=12, command=self._show_exact_ship_list).grid(
                row=current_row,
                column=0,
                columnspan=2,
                pady=(0, 6),
            )
            return current_row + 1

        # Neutron sections
        def add_neutron_via_section(*, current_row):
            via_btn_frame = tk.Frame(parent)
            via_btn_frame.grid(row=current_row, column=0, sticky=tk.EW, padx=4, pady=(0, 6))
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
            current_row += 1

            self._neutron_via_frame = tk.Frame(parent)
            self._neutron_via_frame.grid(row=current_row, column=0, sticky=tk.EW, padx=4, pady=(0, 8))
            self._neutron_via_frame.columnconfigure(0, weight=1)
            via_header = tk.Frame(self._neutron_via_frame)
            via_header.grid(row=0, column=0, sticky=tk.EW)
            via_header.columnconfigure(0, weight=1)
            tk.Label(via_header, text="Add Via:").grid(row=0, column=0, sticky=tk.W)
            via_clear_btn = tk.Button(
                via_header, text="🗑", width=3, padx=1, pady=0,
                command=self._confirm_clear_neutron_vias,
            )
            via_clear_btn.grid(row=0, column=1, sticky=tk.E)
            Tooltip(via_clear_btn, "Clear list")
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
            return current_row + 1

        def add_neutron_options_section(*, current_row, settings):
            supercharge_frame = tk.Frame(parent)
            supercharge_frame.grid(row=current_row, column=0, pady=(4, 2))
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
            current_row += 1

            efficiency_frame = tk.Frame(parent)
            efficiency_frame.grid(row=current_row, column=0, sticky=tk.EW, padx=4, pady=(6, 4))
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
            )
            self._setup_spinbox(self.efficiency_entry, integer=True)
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
            return current_row + 1

        # Exploration sections
        def add_exploration_options_section(*, current_row, planner, settings):
            is_exobiology = planner == "Exomastery"
            is_riches = planner == "Road to Riches"
            default_radius = "25"
            default_max_distance = "50000"
            default_min_value = "10000000" if is_exobiology else "100000"

            current_row = add_range_section(
                current_row=current_row,
                attr_name="_exp_range",
                planner=planner,
            )

            add_labeled_spinbox_row(
                current_row=current_row,
                label_text="Radius (LY):" if is_exobiology else "Search Radius (LY):",
                help_text="This is the distance in LY around which the plotter will look for valuable worlds for you to visit. A value of 25 LY tends to give a nice balance for A to B routes keeping the number of jumps reasonably low whilst still giving a nice payout. For circular routes (leaving destination blank) you will probably want to increase this to 100-500 LY.",
                attr_name="_exp_radius",
                from_=1,
                to=1000,
                initial_value=settings.get("radius", default_radius),
                integer=True,
            )
            current_row += 1

            add_labeled_spinbox_row(
                current_row=current_row,
                label_text="Max Systems:",
                help_text="This is the maximum number of systems that the plotter will route you through; lower this for a shorter trip.",
                attr_name="_exp_max_results",
                from_=1,
                to=1000,
                initial_value=settings.get("max_results", "100"),
                integer=True,
            )
            current_row += 1

            add_labeled_spinbox_row(
                current_row=current_row,
                label_text="Max Distance (Ls):",
                help_text="Maximum light-seconds from arrival star to the target body.",
                attr_name="_exp_max_distance",
                from_=1,
                to=1000000,
                initial_value=settings.get("max_distance", default_max_distance),
                integer=True,
            )
            current_row += 1

            if is_riches or is_exobiology:
                add_labeled_spinbox_row(
                    current_row=current_row,
                    label_text="Min Landmark Value:" if is_exobiology else "Min Scan Value:",
                    help_text="Minimum value threshold for bodies or exobiology landmarks to include.",
                    attr_name="_exp_min_value",
                    from_=0,
                    to=100000000 if is_exobiology else 1000000,
                    initial_value=settings.get("min_value", default_min_value),
                    integer=True,
                )
                current_row += 1

            return current_row

        # Section dispatcher
        section_builders = {
            "source": add_source_section,
            "destination": add_destination_section,
            "range": add_range_section,
            "exact_options": add_exact_options_section,
            "exact_ship": add_exact_ship_section,
            "neutron_via": add_neutron_via_section,
            "neutron_options": add_neutron_options_section,
            "exploration_options": add_exploration_options_section,
        }
        for name, kwargs in sections:
            row = section_builders[name](current_row=row, **kwargs)
        return row

    def _close_plotter_window(self):
        is_exact = self._plotter_window_kind == "Exact Plotter"
        if self._is_plotting():
            self._mark_plot_stopped(cancelled=True, exact=is_exact)
            self._invalidate_plot_token()
            self._set_main_controls_enabled(True)
            self._set_plotter_windows_enabled(True)
        if is_exact:
            self._destroy_exact_ship_dialog("_exact_ship_list_win")
            self._destroy_exact_ship_dialog("_exact_ship_import_win")
            self._destroy_exact_ship_dialog("_exact_ship_export_win")
        if self.plotter_win:
            try:
                self.plotter_win.destroy()
            except tk.TclError:
                pass
        self.plotter_win = None
        if is_exact:
            self._exact_imported_ship_loadout = None
            self._exact_imported_ship_fsd_data = None
        self._plotter_window_kind = None

    def run_search_action(self):
        if self.search_var.get() == "Find nearest system":
            self.show_nearest_finder()

    def show_plotter_window(self):
        """Open the unified plotter window based on the selected planner."""
        if self._is_plotting():
            return
        planner = self.planner_var.get()
        if planner == "Galaxy Plotter":
            planner = "Exact Plotter"

        def setup_error_label(var_attr, lbl_attr, parent, row, **kwargs):
            grid_keys = ("column", "columnspan", "rowspan", "sticky", "in_", "padx", "pady")
            grid_kw = {k: kwargs.pop(k) for k in grid_keys if k in kwargs}
            var = tk.StringVar()
            label = tk.Label(parent, textvariable=var, fg="red", **kwargs)
            label.grid(row=row, **grid_kw)
            label.grid_remove()
            var.trace_add("write", lambda *_: label.grid() if var.get().strip() else label.grid_remove())
            setattr(self, var_attr, var)
            setattr(self, lbl_attr, label)

        def add_packed_footer(parent, row, calc_attr, calc_command, cancel_command, error_var_attr, error_lbl_attr):
            btn_frame = tk.Frame(parent)
            btn_frame.grid(row=row, column=0, pady=(10, 10))
            calc_btn = tk.Button(btn_frame, text="Calculate", width=12, command=calc_command)
            calc_btn.pack(side=tk.LEFT, padx=(0, 7))
            tk.Button(btn_frame, text="Cancel", width=12, command=cancel_command).pack(side=tk.LEFT, padx=(7, 0))
            setattr(self, calc_attr, calc_btn)
            setup_error_label(error_var_attr, error_lbl_attr, parent, row + 1, column=0, pady=(10, 0), wraplength=340, justify=tk.CENTER)

        # Exact
        def show_exact():
            if not self._prepare_window_kind("Exact Plotter"):
                return
            _window, content = self._build_plotter_window(
                title="Spansh Exact Plotter",
                close_command=self._close_plotter_window,
                minsize=(300, 0),
                content_padding=(0, 0),
                content_column_weights=(1, 0),
            )

            if not self._active_exact_ship_fsd_data():
                self._detect_fsd_from_monitor()
            self._restore_selected_ship_from_config()

            row = self._build_plotter_sections(
                content,
                row=0,
                sections=[
                    ("source", {"attr_name": "exact_source_ac", "settings": self._settings_for_planner("Exact Plotter")}),
                    ("destination", {"attr_name": "exact_dest_ac", "settings": self._settings_for_planner("Exact Plotter")}),
                    ("exact_options", {}),
                    ("exact_ship", {}),
                ],
            )

            self.exact_calculate_btn = tk.Button(
                content,
                text="Calculate",
                width=12,
                command=self.plot_exact_route,
            )
            self.exact_calculate_btn.grid(row=row, column=0, padx=5, pady=10)
            tk.Button(content, text="Cancel", width=12, command=lambda: self._cancel_plot(exact=True)).grid(
                row=row, column=1, padx=5, pady=10
            )
            row += 1

            setup_error_label("exact_error_txt", "exact_error_lbl", content, row, columnspan=2, padx=5, pady=(5, 0), wraplength=300)
            self.plotter_win.update_idletasks()
            self._configure_child_window(self.plotter_win)

        # Neutron
        def show_neutron():
            neutron_planner = "Neutron Plotter"
            if not self._prepare_window_kind(neutron_planner):
                return

            _window, content = self._build_plotter_window(
                title="Spansh Neutron Plotter",
                close_command=self._close_plotter_window,
                minsize=(330, 0),
                content_padding=(0, 0),
                content_column_weights=(1,),
            )

            settings = self._settings_for_planner(neutron_planner)
            self._neutron_vias = list(settings.get("vias", []))
            self._neutron_via_visible = bool(self._neutron_vias)

            row = self._build_plotter_sections(
                content,
                row=0,
                sections=[
                    ("source", {"attr_name": "source_ac", "settings": settings, "layout": "single"}),
                    ("neutron_via", {}),
                    ("destination", {"attr_name": "dest_ac", "settings": settings, "layout": "single"}),
                    ("range", {"attr_name": "range_entry", "planner": neutron_planner}),
                    ("neutron_options", {"settings": settings}),
                ],
            )

            add_packed_footer(
                content,
                row,
                "_neutron_calc_btn",
                self._neutron_plot,
                lambda: self._cancel_plot(update_gui=True),
                "neutron_error_txt",
                "neutron_error_lbl",
            )
            self.plotter_win.update_idletasks()
            self._configure_child_window(self.plotter_win)
            self.plotter_win.after_idle(self._refresh_neutron_vias)
            self.plotter_win.after(80, self._refresh_neutron_vias)

        # Exploration
        def show_exploration(exploration_planner):
            if not self._prepare_window_kind(exploration_planner):
                return

            _window, content = self._build_plotter_window(
                title=f"Spansh {exploration_planner}",
                close_command=self._close_plotter_window,
                minsize=(300, 0),
                content_padding=(0, 0),
                content_column_weights=(1, 0),
            )

            settings = self._settings_for_planner(exploration_planner)
            is_exobiology = exploration_planner == "Exomastery"
            is_riches = exploration_planner == "Road to Riches"

            row = self._build_plotter_sections(
                content,
                row=0,
                sections=[
                    ("source", {"attr_name": "_exp_source_ac", "settings": settings}),
                    (
                        "destination",
                        {
                            "attr_name": "_exp_dest_ac",
                            "settings": settings,
                            "label_text": "Destination System (optional):",
                        },
                    ),
                    ("exploration_options", {"planner": exploration_planner, "settings": settings}),
                ],
            )

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
            btn_frame.grid(row=row, column=0, columnspan=2, pady=(10, 10))
            self._exp_calc_btn = tk.Button(
                btn_frame,
                text="Calculate",
                width=12,
                command=lambda p=exploration_planner: self._plot_exploration_route(p),
            )
            self._exp_calc_btn.pack(side=tk.LEFT, padx=(0, 7))
            tk.Button(btn_frame, text="Cancel", width=12, command=self._cancel_plot).pack(side=tk.LEFT, padx=(7, 0))
            setup_error_label(
                "_exp_error_txt",
                "_exp_error_lbl",
                content,
                row + 1,
                column=0,
                columnspan=2,
                pady=(10, 0),
                wraplength=340,
                justify=tk.CENTER,
            )
            self.plotter_win.update_idletasks()
            self._configure_child_window(self.plotter_win)

        # Fleet
        def show_fleet():
            fleet_planner = "Fleet Carrier Router"
            if not self._prepare_window_kind(fleet_planner):
                return

            settings = self._settings_for_planner(fleet_planner)
            self._fc_destinations = list(settings.get("destinations", []))
            self._fc_refuel_destinations = set(settings.get("refuel_destinations", []))

            _window, content = self._build_plotter_window(
                title="Spansh Fleet Carrier Router",
                close_command=self._close_plotter_window,
                minsize=None,
                content_padding=(5, 2),
                content_column_weights=(1,),
            )

            row = self._build_plotter_sections(
                content,
                row=0,
                sections=[
                    ("source", {"attr_name": "_fc_source_ac", "width": 42, "settings": settings, "layout": "single"}),
                ],
            )

            fc_dest_header = tk.Frame(content)
            fc_dest_header.grid(row=row, column=0, sticky=tk.EW, padx=4, pady=(0, 2))
            fc_dest_header.columnconfigure(0, weight=1)
            tk.Label(fc_dest_header, text="Add Destination:").grid(row=0, column=0, sticky=tk.W)
            fc_dest_clear_btn = tk.Button(
                fc_dest_header, text="🗑", width=3, padx=1, pady=0,
                command=self._confirm_clear_fc_destinations,
            )
            fc_dest_clear_btn.grid(row=0, column=1, sticky=tk.E)
            Tooltip(fc_dest_clear_btn, "Clear list")
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
            capacity_max = 60000 if self._fc_carrier_type.get() == "squadron" else 25000
            type_frame = tk.Frame(content)
            type_frame.grid(row=row, column=0, sticky=tk.EW, pady=2)
            type_frame.columnconfigure(0, weight=1)
            type_frame.columnconfigure(1, weight=1)
            tk.Radiobutton(type_frame, text="Player Carrier", variable=self._fc_carrier_type, value="fleet").grid(row=0, column=0, sticky=tk.W, padx=(20, 0))
            tk.Radiobutton(type_frame, text="Squadron Carrier", variable=self._fc_carrier_type, value="squadron").grid(row=0, column=1, sticky=tk.E, padx=(0, 20))
            row += 1

            used_frame = tk.Frame(content)
            used_frame.grid(row=row, column=0, sticky=tk.EW, pady=2)
            tk.Label(used_frame, text="Used Capacity (t):").pack(side=tk.LEFT)
            used_help = tk.Label(used_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow",
                                 relief=tk.RAISED, borderwidth=1, padx=2)
            used_help.pack(side=tk.LEFT, padx=(4, 0))
            Tooltip(used_help, "Fill in the capacity shown in the upper right corner of the carrier management screen.")
            self._fc_used_capacity = tk.Spinbox(used_frame, from_=0, to=capacity_max, width=12)
            self._setup_spinbox(self._fc_used_capacity, integer=True)
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

            self._fc_tritium_frame = tk.Frame(content)
            self._fc_tritium_frame.grid(row=row, column=0, sticky=tk.EW, pady=(0, 4))
            self._fc_tritium_frame.columnconfigure(0, weight=1)

            mkt_to = capacity_max
            for label_text, help_text, attr_name, to_value, value, pady in (
                ("Tritium in tank", "The amount of tritium in your fuel tank", "_fc_tritium_tank", 1000, self._safe_int(settings.get("tritium_fuel"), 1000), 2),
                ("Tritium in market", "The amount of tritium in your commodities market", "_fc_tritium_market", mkt_to, self._safe_int(settings.get("tritium_market"), 0), (6, 2)),
            ):
                row_frame = tk.Frame(self._fc_tritium_frame)
                row_frame.pack(fill=tk.X, pady=pady)
                label_frame = tk.Frame(row_frame)
                label_frame.pack(side=tk.LEFT)
                tk.Label(label_frame, text=label_text).pack(side=tk.LEFT)
                help_lbl = tk.Label(label_frame, text="?", font=("", 8), fg="blue", cursor="question_arrow", relief=tk.RAISED, borderwidth=1, padx=2)
                help_lbl.pack(side=tk.LEFT, padx=(4, 0))
                Tooltip(help_lbl, help_text)
                spinbox = tk.Spinbox(row_frame, from_=0, to=to_value, width=12)
                self._setup_spinbox(spinbox, integer=True)
                spinbox.delete(0, tk.END)
                spinbox.insert(0, str(value))
                spinbox.pack(side=tk.RIGHT, padx=(0, 2))
                setattr(self, attr_name, spinbox)

            def update_tri_visibility(*_):
                if self._fc_determine_required_fuel.get():
                    self._fc_tritium_frame.grid_remove()
                else:
                    self._fc_tritium_frame.grid()

            self._fc_determine_required_fuel.trace_add("write", update_tri_visibility)
            update_tri_visibility()

            def update_carrier_limits(*_):
                is_sq = self._fc_carrier_type.get() == "squadron"
                new_max = 60000 if is_sq else 25000
                for widget in (self._fc_used_capacity, self._fc_tritium_market):
                    widget.configure(to=new_max)
                    val = self._safe_int(widget.get(), 0)
                    if val > new_max:
                        widget.delete(0, tk.END)
                        widget.insert(0, str(new_max))

            self._fc_carrier_type.trace_add("write", update_carrier_limits)
            row += 1

            add_packed_footer(
                content,
                row,
                "_fc_calc_btn",
                self._plot_fleet_carrier_route,
                self._cancel_plot,
                "_fc_error_txt",
                "_fc_error_lbl",
            )
            self.plotter_win.update_idletasks()
            self._configure_child_window(self.plotter_win)
            self.plotter_win.after_idle(self._fc_refresh_destinations)
            self.plotter_win.after(80, self._fc_refresh_destinations)

        if planner == "Neutron Plotter":
            show_neutron()
        elif planner == "Exact Plotter":
            show_exact()
        elif planner == "Fleet Carrier Router":
            show_fleet()
        elif planner in ("Road to Riches", "Ammonia World Route", "Earth-like World Route", "Rocky/HMC Route", "Exomastery"):
            show_exploration(planner)

    def _prepare_window_kind(self, kind):
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

    def _checkbox_with_help(self, parent, text, variable, help_text, row, *, columnspan=1):
        frame = tk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=columnspan, sticky=tk.W, pady=2)
        tk.Checkbutton(frame, text=text, variable=variable).pack(side=tk.LEFT)
        self._add_help_label(frame, help_text)
        return frame

    def _add_help_label(self, parent, help_text):
        if not help_text:
            return None
        help_lbl = tk.Label(
            parent,
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
        return help_lbl

    def _prefill_range_entry(self, widget, value=None, *, integer=False, overwrite=True, planner=None):
        if not overwrite:
            current = self._get_entry_value(widget)
            if current and current not in ("0", "0.00", "", None):
                return
        try:
            if hasattr(widget, "delete"): widget.delete(0, tk.END)
            elif isinstance(widget, AutoCompleter): widget.set_text("", False)
        except Exception: pass
        if value in (None, "", []):
            if planner:
                value = self._settings_for_planner(planner).get("range")

            if value in (None, "", []):
                value = self._suggest_jump_range()

        if value in (None, "", []):
            return
        if integer: text = str(int(round(float(value))))
        else: text = f"{float(value):.2f}"
        if isinstance(widget, PlaceHolder):
            widget.set_text(text, False)
        elif hasattr(widget, "insert"): widget.insert(0, text)
        elif isinstance(widget, AutoCompleter): widget.set_text(text, False)
        else:
            self._set_entry_value(widget, text)

    def _fill_range_from_current(self, widget):
        value = self._suggest_jump_range()
        if value is None:
            return
        try:
            if hasattr(widget, "delete"): widget.delete(0, tk.END)
            elif isinstance(widget, AutoCompleter): widget.set_text("", False)
            if hasattr(widget, "insert"): widget.insert(0, f"{float(value):.2f}")
            elif isinstance(widget, AutoCompleter): widget.set_text(f"{float(value):.2f}", False)
        except Exception: pass

    def _prefill_cargo_entry(self, widget, value=None, *, overwrite=True):
        if not overwrite:
            current = self._get_entry_value(widget)
            if current and current not in ("0", "", None):
                return
        if value in (None, "", []):
            if not getattr(self, "_cargo_prefill_ready", False):
                return
            try:
                value = int(sum((monitor.state.get("Cargo") or {}).values()))
            except Exception:
                value = 0
        if value is None:
            return

        text = str(int(value))
        if isinstance(widget, PlaceHolder):
            widget.set_text(text, False)
        else:
            self._set_entry_value(widget, text)

    def _fill_cargo_from_current(self, widget, *, force=False):
        if not widget or not widget.winfo_exists():
            return
        if not force:
            try:
                if getattr(self, "_exact_imported_ship_loadout", None) or config.get_str(self._EXACT_SELECTED_SHIP_CONFIG_KEY, default=""):
                    return
            except Exception:
                pass
        try:
            value = int(sum((monitor.state.get("Cargo") or {}).values()))
        except Exception:
            value = 0
        self._prefill_cargo_entry(widget, value=value)

    def _update_cargo_button_state(self):
        btn = getattr(self, "_exact_cargo_refresh_btn", None)
        if btn is None:
            return
        try:
            if not btn.winfo_exists():
                return
        except Exception:
            return
        is_current = not getattr(self, "_exact_imported_ship_loadout", None)
        btn.config(state=tk.NORMAL if is_current else tk.DISABLED)
        tooltip = getattr(self, "_exact_cargo_refresh_tooltip", None)
        if tooltip is not None:
            tooltip.text = "Get current cargo" if is_current else "Get current cargo\n(Not possible with manually selected ships)"

    def _plot_button_animation_attr_names(self, *, exact=False):
        prefix = "_exact" if exact else "_plotter"
        return (
            f"{prefix}_button_animation_job",
            f"{prefix}_button_animation_phase",
        )

    def _cancel_plot_button_animation(self, button=None, *, exact=False):
        job_attr, _phase_attr = self._plot_button_animation_attr_names(exact=exact)
        job = getattr(self, job_attr, None)
        target = button
        if target is None:
            target = getattr(self, "exact_calculate_btn", None) if exact else getattr(self, "_neutron_calc_btn", None)
        if target is not None and job is not None:
            try:
                target.after_cancel(job)
            except Exception:
                pass
        setattr(self, job_attr, None)

    def _tick_plot_button_animation(self, button, *, exact=False):
        job_attr, phase_attr = self._plot_button_animation_attr_names(exact=exact)
        if button is None:
            setattr(self, job_attr, None)
            return

        try:
            phase = int(getattr(self, phase_attr, 0) or 0)
            dots = "." * phase
            button.config(text=f"Computing{dots}")
        except Exception:
            setattr(self, job_attr, None)
            return
        setattr(self, phase_attr, (phase + 1) % 4)
        try:
            job = button.after(675, lambda b=button: self._tick_plot_button_animation(b, exact=exact))
        except Exception:
            job = None
        setattr(self, job_attr, job)

    def _set_plot_button_busy_state(self, button, *, active, exact=False):
        if button is None:
            return
        self._cancel_plot_button_animation(button, exact=exact)
        try:
            setattr(button, "_busy_plot_button", bool(active))
        except Exception:
            pass
        try:
            if active:
                setattr(self, self._plot_button_animation_attr_names(exact=exact)[1], 0)
                button.config(
                    state=tk.DISABLED,
                    disabledforeground=button.cget("fg"),
                )
                self._tick_plot_button_animation(button, exact=exact)
            else:
                button.config(state=tk.NORMAL, text="Calculate")
        except (tk.TclError, AttributeError):
            pass

# --- Neutron Plotter ---

    # -- Plotters --

    # Neutron Plotter

    def _neutron_plot(self):
        self.hide_error()
        try:
            source = self.source_ac.get().strip()
            dest = self.dest_ac.get().strip()
            vias = self._current_neutron_vias()
            self.source_ac.hide_list()
            self.dest_ac.hide_list()

            if self.source_ac.is_effectively_empty():
                self._set_neutron_error("Please provide a starting system.")
                return
            if self.dest_ac.is_effectively_empty():
                self._set_neutron_error("Please provide a destination system.")
                return

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
            self._set_plot_running_state(
                active=True,
                use_enable_plot_gui=True,
                button=getattr(self, "_neutron_calc_btn", None),
            )

            params = {
                "source": source,
                "dest": dest,
                "vias": vias,
                "efficiency": efficiency,
                "range": range_ly,
                "supercharge_multiplier": supercharge_multiplier,
            }

            token = self._next_plot_token()
            threading.Thread(target=self._neutron_plot_worker, args=(params, token), daemon=True).start()
        except Exception:
            self._log_unexpected("Failed to start neutron route plot")
            self._set_plot_running_state(
                active=False,
                use_enable_plot_gui=True,
                button=getattr(self, "_neutron_calc_btn", None),
            )
            self._set_neutron_error(self.plot_error)

    def _cancel_plot(self, *, exact=False, update_gui=False):
        if exact or self._is_plotting():
            self._mark_plot_stopped(cancelled=True, exact=exact)
            self._invalidate_plot_token()
            self._set_main_controls_enabled(True)
            self._set_plotter_windows_enabled(True)
        self._close_plotter_window()
        if update_gui:
            self.update_gui()

    def _neutron_plot_worker(self, params, token):
        """Background worker for neutron route plotting."""
        try:
            if self._is_plot_cancelled():
                return

            ok, nearest, error_msg = self._validate_source_system(params["source"])
            if not ok:
                if nearest:
                    self._ui_call(self.source_ac.set_text, nearest, False, token=token)
                    self._ui_call(self._copy_to_clipboard, nearest, token=token)
                else:
                    self._ui_call(self._mark_widget_text_error, self.source_ac, token=token)
                self._ui_call(self._neutron_plot_error, error_msg, token=token)
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
                return

            try:
                route = data["result"]["system_jumps"]
            except (KeyError, TypeError) as e:
                logger.warning(f"Invalid data from Spansh: {e}")
                self._ui_call(self._neutron_plot_error, self.plot_error, token=token)
                return
            self._ui_call(self._neutron_plot_success, route, self._spansh_incomplete_warning(data), token=token)

        except _SpanshPollError as e:
            if e.status_code == 400:
                self._ui_call(self._neutron_plot_validation_error, str(e), token=token)
            else:
                self._ui_call(self._neutron_plot_error, self.plot_error, token=token)
        except RequestException as e:
            self._ui_call(self._neutron_plot_error, f"Network error: {e}", token=token)
        except _SpanshPollTimeout:
            self._ui_call(self._neutron_plot_error, "The query to Spansh timed out. Please try again.", token=token)
        except Exception:
            self._log_unexpected("Unexpected neutron plotter worker failure")
            self._ui_call(self._neutron_plot_error, self.plot_error, token=token)

    def _neutron_plot_success(self, route, warning=None):
        """Called on main thread when neutron route succeeds."""
        self._set_plot_running_state(active=False, use_enable_plot_gui=True, button=getattr(self, "_neutron_calc_btn", None))
        settings = {
            "source": self.source_ac.get().strip(),
            "destination": self.dest_ac.get().strip(),
            "range": self.range_entry.get().strip(),
            "vias": self._current_neutron_vias(),
            "efficiency": self.efficiency_slider.get(),
            "supercharge_multiplier": self.supercharge_multiplier.get(),
        }
        self._reset_for_new_route()
        self._apply_neutron_route_rows(route, settings=settings)
        self.offset = 1 if self._route_starts_at_current_system() else 0
        self.next_stop = self._current_route_row_name("")
        self._finalize_applied_route()
        self._show_spansh_warning(warning)

    def _neutron_plot_error(self, msg):
        """Called on main thread when neutron route fails."""
        self._set_plot_running_state(active=False, use_enable_plot_gui=True, button=getattr(self, "_neutron_calc_btn", None))
        if self.plotter_win:
            try:
                self.neutron_error_txt.set(msg)
                return
            except (tk.TclError, AttributeError):
                pass
        self.show_error(msg)

    def _neutron_plot_validation_error(self, error_msg):
        """Called on main thread for Spansh 400 validation errors."""
        self._set_plot_running_state(active=False, use_enable_plot_gui=True, button=getattr(self, "_neutron_calc_btn", None))
        error_msg = self._with_destination_not_found_tip(error_msg)
        plotter_alive = False
        try:
            plotter_alive = bool(self.plotter_win and self.plotter_win.winfo_exists())
        except Exception:
            plotter_alive = False
        if plotter_alive:
            try:
                self.neutron_error_txt.set(error_msg)
                if "starting system" in error_msg and self.source_ac.winfo_exists():
                    self.source_ac.set_error_style()
                if ("destination system" in error_msg or "finishing system" in error_msg) and self.dest_ac.winfo_exists():
                    self.dest_ac.set_error_style()
                return
            except (tk.TclError, AttributeError):
                pass
        self.show_error(error_msg)
        if "destination system" in error_msg or "finishing system" in error_msg:
            try:
                if plotter_alive and self.dest_ac.winfo_exists():
                    self.dest_ac.set_error_style()
            except Exception:
                pass

    # Neutron Via

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
        if self._neutron_via_ac.is_effectively_empty():
            return
        if via_name not in self._neutron_vias:
            self._neutron_vias.append(via_name)
            self._refresh_neutron_vias()
            self._select_neutron_via_line(len(self._neutron_vias) - 1)
        self._neutron_via_ac.set_text(self._neutron_via_ac.placeholder, True)

    def _add_neutron_via_from_entry(self, _event=None):
        via_name = self._neutron_via_ac.get().strip()
        if self._neutron_via_ac.is_effectively_empty():
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

    def _confirm_clear_neutron_vias(self):
        if not getattr(self, "_neutron_vias", None):
            return
        if confirmDialog.askyesno("Clear Via List", f"Remove all {len(self._neutron_vias)} via system(s)?", parent=self.plotter_win):
            self._clear_all_neutron_vias()

    def _clear_all_neutron_vias(self):
        self._neutron_vias.clear()
        self._neutron_via_list.selected_index = None
        self._refresh_neutron_vias()

    def _reverse_neutron_route(self):
        if not getattr(self, "source_ac", None) or not getattr(self, "dest_ac", None):
            return
        source = "" if self.source_ac.is_effectively_empty() else self.source_ac.get().strip()
        destination = "" if self.dest_ac.is_effectively_empty() else self.dest_ac.get().strip()
        vias = list(reversed(self._neutron_vias))

        if not destination:
            self.source_ac.set_text(self.source_ac.placeholder, True)
        else:
            self.source_ac.set_text(destination, False)

        if not source:
            self.dest_ac.set_text(self.dest_ac.placeholder, True)
        else:
            self.dest_ac.set_text(source, False)
        self._neutron_vias = vias
        self._neutron_via_list.set_items(self._neutron_vias)
        self._neutron_via_list.selected_index = None
        if self._neutron_vias:
            self._neutron_via_visible = True
        self._refresh_neutron_vias()
        self._apply_neutron_via_visibility()

    def _show_neutron_via_menu(self, event, via_name, index=None):
        if index is not None and hasattr(self, "_neutron_via_list"):
            self._neutron_via_list.set_selected_index(index, update_highlight=True)
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
            display_name, truncated = truncate_text_px(name, 270)
            label = tk.Label(
                row_frame,
                text=display_name,
                anchor=tk.W,
                bg=row_bg,
                fg="black",
                cursor="hand2",
            )
            label.grid(row=0, column=1, sticky=tk.EW, pady=1)
            if truncated:
                Tooltip(label, name)
            label.bind("<Button-3>", lambda e, n=name, i=index: self._show_neutron_via_menu(e, n, i))
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
            row_frame.bind("<Button-3>", lambda e, n=name, i=index: self._show_neutron_via_menu(e, n, i))
            for widget in (row_frame, label, right_btns):
                dlw.bind_row_events(widget, index)
            dlw.bind_scroll_events(del_btn)

        self._refresh_draggable_rows(dlw, self._neutron_vias, build_row)

    def _select_neutron_via_line(self, index):
        if not hasattr(self, "_neutron_via_list"):
            return
        self._neutron_via_list.set_selected_index(index, update_highlight=True)

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


# --- Exact(Galaxy) Plotter ---

    # Exact Plotter

    def plot_exact_route(self):
        source = self.exact_source_ac.get().strip()
        dest = self.exact_dest_ac.get().strip()

        if self.exact_source_ac.is_effectively_empty():
            self._set_exact_error("Please provide a source system.")
            return
        if self.exact_dest_ac.is_effectively_empty():
            self._set_exact_error("Please provide a destination system.")
            return

        if not self._active_exact_ship_fsd_data():
            self._detect_fsd_from_monitor()
        if not self._active_exact_ship_fsd_data():
            self._set_exact_error("No ship data available. Enter the game or switch ships.")
            return

        try:
            cargo = self._clamp_spinbox_input(
                self.exact_cargo_entry,
                integer=True,
                error_message="Invalid cargo value.",
            )
        except ValueError:
            self._set_exact_error("Invalid cargo value.")
            return
        try:
            reserve = self._clamp_spinbox_input(
                self.exact_reserve_entry,
                error_message="Invalid reserve fuel value.",
            )
        except ValueError:
            self._set_exact_error("Invalid reserve fuel value.")
            return

        cargo_val = self.exact_cargo_entry.get().strip()
        reserve_val = self.exact_reserve_entry.get().strip()
        self._set_exact_error("")

        fsd = self._active_exact_ship_fsd_data()
        params = {
            "source": source,
            "destination": dest,
            "is_supercharged": 1 if self.exact_is_supercharged.get() else 0,
            "use_supercharge": 1 if self.exact_use_supercharge.get() else 0,
            "use_injections": 1 if self.exact_use_injections.get() else 0,
            "exclude_secondary": 1 if self.exact_exclude_secondary.get() else 0,
            "refuel_every_scoopable": 1 if self.exact_refuel_every_scoopable.get() else 0,
            "algorithm": self.exact_algorithm.get(),
            "tank_size": fsd["tank_size"],
            "cargo": cargo,
            "optimal_mass": fsd["optimal_mass"],
            "base_mass": fsd["unladen_mass"] + fsd["reserve_size"],
            "internal_tank_size": fsd["reserve_size"],
            "max_fuel_per_jump": fsd["max_fuel_per_jump"],
            "range_boost": fsd.get("range_boost", 0),
            "fuel_power": fsd["fuel_power"],
            "fuel_multiplier": fsd["fuel_multiplier"],
            "reserve_size": reserve,
            "supercharge_multiplier": fsd.get("supercharge_multiplier", 4),
            "injection_multiplier": 2,
            "max_time": 60,
        }

        self._pending_exact_settings = {
            "source": source,
            "destination": dest,
            "cargo": cargo_val,
            "reserve": reserve_val,
            "use_supercharge": self.exact_use_supercharge.get(),
            "is_supercharged": self.exact_is_supercharged.get(),
            "use_injections": self.exact_use_injections.get(),
            "exclude_secondary": self.exact_exclude_secondary.get(),
            "refuel_every_scoopable": self.exact_refuel_every_scoopable.get(),
            "algorithm": self.exact_algorithm.get(),
        }
        self._set_plot_running_state(active=True, exact=True, button=getattr(self, "exact_calculate_btn", None))

        token = self._next_plot_token()
        threading.Thread(target=self._exact_plot_worker, args=(params, token), daemon=True).start()

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
                else:
                    self._ui_call(self._mark_widget_text_error, self.exact_source_ac, token=token)
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
        except RequestException as e:
            self._ui_call(self._exact_plot_error, f"Network error: {e}", token=token)
        except Exception as e:
            self._log_unexpected(f"Exact plotter error: {e}")
            self._ui_call(self._exact_plot_error, str(e), token=token)

    def _exact_plot_success(self, route_data):
        """Called on main thread when exact plot succeeds."""
        self._set_plot_running_state(active=False, exact=True, button=getattr(self, "exact_calculate_btn", None))
        warning = self._spansh_incomplete_warning(route_data if isinstance(route_data, dict) else {})
        try:
            jumps = route_data["result"]["jumps"]
        except (KeyError, TypeError):
            self._exact_plot_error("Invalid response from Spansh.")
            return

        self._reset_for_new_route()

        # Persist exact plotter settings
        pending = getattr(self, '_pending_exact_settings', None)
        if pending:
            self._store_plotter_settings("Exact Plotter", pending)

        # Set mode flags
        self.exact_plotter = True
        self._set_current_plotter("Exact Plotter")
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

        self._finalize_applied_route(update_overlay=True)
        self._show_spansh_warning(warning)

    def _exact_plot_error(self, message):
        """Called on main thread when exact plot fails."""
        self._set_plot_running_state(active=False, exact=True, button=getattr(self, "exact_calculate_btn", None))
        self._set_exact_error(message)

    # Exploration Plotter
    def _plot_exploration_route(self, planner):
        """Gather exploration form values, validate, and launch the Spansh API thread."""
        try:
            source = self._exp_source_ac.get().strip()
            self._set_exploration_error("")
            self._exp_source_ac.hide_list()
            self._exp_dest_ac.hide_list()

            if self._exp_source_ac.is_effectively_empty():
                self._set_exploration_error("Please provide a starting system.")
                return

            dest = self._exp_dest_ac.get().strip()
            if self._exp_dest_ac.is_effectively_empty():
                dest = ""

            try:
                range_ly = self._clamp_spinbox_input(
                    self._exp_range,
                    error_message="Invalid range",
                )
            except ValueError:
                self._set_exploration_error("Invalid range")
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
                self._set_exploration_error("Radius, max systems, and max distance must be numbers.")
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
                    self._set_exploration_error("Minimum landmark value must be a number.")
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
                        self._set_exploration_error("Minimum scan value must be a number.")
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
            self._set_exploration_error("Error starting route calculation.")

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
                else:
                    self._ui_call(self._mark_widget_text_error, self._exp_source_ac, token=token)
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
        except RequestException as e:
            self._ui_call(self._exploration_route_error, f"Network error: {e}", token=token)
        except Exception as e:
            self._log_unexpected(f"Exploration route error: {e}")
            self._ui_call(self._exploration_route_error, str(e), token=token)

    def _exploration_route_success(self, route_data, planner, settings=None):
        """Called on main thread when exploration route succeeds."""
        self._set_plot_running_state(active=False, button=getattr(self, "_exp_calc_btn", None))
        systems = self._extract_exploration_systems(route_data)
        if not systems:
            self._set_exploration_error("No route found for the given parameters.")
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
        self._set_exploration_error(msg)

    # Fleet Carrier Plotter

    def _plot_fleet_carrier_route(self):
        try:
            source = self._fc_source_ac.get().strip()
            self._set_fleet_error("")
            self._fc_source_ac.hide_list()
            self._fc_dest_ac.hide_list()

            if self._fc_source_ac.is_effectively_empty():
                self._set_fleet_error("Please provide a starting system.")
                return
            if not self._fc_destinations:
                self._set_fleet_error("Add at least one destination.")
                return

            used_capacity = self._clamp_spinbox_input(
                self._fc_used_capacity,
                integer=True,
                error_message="Used capacity must be a number.",
            )
            determine_required_fuel = bool(self._fc_determine_required_fuel.get())
            tri_tank = self._safe_int(self._fc_tritium_tank.get(), 1000)
            tri_mkt = self._safe_int(self._fc_tritium_market.get(), 0)

            if not determine_required_fuel and tri_mkt > used_capacity:
                self._set_fleet_error("Unable to generate route: Tritium stored is more than capacity used")
                return

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
                "tritium_fuel": tri_tank,
                "tritium_market": tri_mkt,
            }

            self._set_plot_running_state(active=True, button=getattr(self, "_fc_calc_btn", None))
            token = self._next_plot_token()
            threading.Thread(target=self._fleet_carrier_route_worker, args=(params, token), daemon=True).start()
        except ValueError as e:
            self._set_fleet_error(str(e))
        except Exception:
            self._set_plot_running_state(active=False, button=getattr(self, "_fc_calc_btn", None))
            self._log_unexpected("Fleet carrier plot error")
            self._set_fleet_error("Error starting route calculation.")

# Fleet Carrier Plotter Results

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
                else:
                    self._ui_call(self._mark_widget_text_error, self._fc_source_ac, token=token)
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
                "fuel_loaded": params.get("tritium_fuel", 1000),
                "tritium_stored": params.get("tritium_market", 0),
            }
            if params.get("refuel_destinations"):
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
            self._ui_call(
                self._fleet_carrier_route_success,
                route_data,
                params,
                self._spansh_incomplete_warning(result if isinstance(result, dict) else {}),
                token=token,
            )

        except (_SpanshPollError, _SpanshPollTimeout) as e:
            self._ui_call(self._fleet_carrier_route_error, str(e), token=token)
        except RequestException as e:
            self._ui_call(self._fleet_carrier_route_error, f"Network error: {e}", token=token)
        except Exception as e:
            self._log_unexpected("Fleet carrier route error")
            self._ui_call(self._fleet_carrier_route_error, str(e), token=token)

    def _fleet_carrier_route_success(self, route_data, params, warning=None):
        """Handle fleet carrier API result — populate route, mark waypoints, and open the viewer."""
        self._set_plot_running_state(active=False, button=getattr(self, "_fc_calc_btn", None))
        jumps = route_data.get("jumps", route_data if isinstance(route_data, list) else [])
        if not jumps:
            self._set_fleet_error("No carrier route found for the given parameters.")
            return

        settings = {
            "source": params["source"],
            "destinations": list(params["destinations"]),
            "refuel_destinations": list(params.get("refuel_destinations", [])),
            "carrier_type": params["carrier_type"],
            "used_capacity": params["used_capacity"],
            "determine_required_fuel": params["determine_required_fuel"],
            "tritium_fuel": params.get("tritium_fuel", 1000),
            "tritium_market": params.get("tritium_market", 0),
        }
        self._reset_for_new_route()

        self.fleetcarrier = True
        self.exact_plotter = False

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
        self._show_spansh_warning(warning)

    def _fleet_carrier_route_error(self, msg):
        self._set_plot_running_state(active=False, button=getattr(self, "_fc_calc_btn", None))
        self._set_fleet_error(msg)

    # Fleet Carrier Destinations

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
            display_name, truncated = truncate_text_px(name, 235)
            label = tk.Label(
                row_frame,
                text=display_name,
                anchor=tk.W,
                bg=row_bg,
                fg="black",
                cursor="hand2",
            )
            label.grid(row=0, column=2, sticky=tk.EW, pady=1)
            if truncated:
                Tooltip(label, name)
            label.bind("<Button-3>", lambda e, n=name, i=index: self._fc_show_destination_menu(e, n, i))
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

            row_frame.bind("<Button-3>", lambda e, n=name, i=index: self._fc_show_destination_menu(e, n, i))

            for widget in (row_frame, label, right_btns):
                dlw.bind_row_events(widget, index)
            for widget in (del_btn, refuel_btn):
                dlw.bind_scroll_events(widget)

        self._refresh_draggable_rows(dlw, self._fc_destinations, build_row)

    def _fc_select_destination_line(self, index):
        if not hasattr(self, "_fc_dest_list"):
            return
        self._fc_dest_list.set_selected_index(index, update_highlight=True)

    def _fc_add_destination(self):
        destination = self._fc_dest_ac.get().strip()
        if self._fc_dest_ac.is_effectively_empty():
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
        if self._fc_dest_ac.is_effectively_empty():
            return "break"
        self._set_fleet_error("")
        self._resolve_system_record_async(
            destination,
            on_success=self._fc_destination_resolved,
            on_not_found=lambda query: self._set_fleet_error(
                f"Destination system '{query}' not found in Spansh."
            ),
            on_error=lambda query, _exc: self._set_fleet_error(
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

    def _confirm_clear_fc_destinations(self):
        if not getattr(self, "_fc_destinations", None):
            return
        if confirmDialog.askyesno("Clear Destinations", f"Remove all {len(self._fc_destinations)} destination(s)?", parent=self.plotter_win):
            self._clear_all_fc_destinations()

    def _clear_all_fc_destinations(self):
        self._fc_destinations.clear()
        self._fc_refuel_destinations.clear()
        self._fc_dest_list.selected_index = None
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

    def _fc_show_destination_menu(self, event, destination_name, index=None):
        if index is not None and hasattr(self, "_fc_dest_list"):
            self._fc_dest_list.set_selected_index(index, update_highlight=True)
        self._fc_menu_destination_name = destination_name or ""
        try:
            self._fc_dest_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._fc_dest_menu.grab_release()

    def _fc_copy_destination_name(self):
        if self._fc_menu_destination_name:
            self._copy_to_clipboard(self._fc_menu_destination_name)

    # --- Web Utils ---

    def _check_system_in_spansh(self, system_name):
        """Check if a system exists in Spansh by querying the autocomplete API."""
        system_name = (system_name or "").strip()
        if not system_name:
            return False
        try:
            resp = WebUtils.spansh_request(
                "GET",
                "/api/systems",
                params={"q": system_name},
                timeout=5
            )
        except RequestException as exc:
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
        response = WebUtils.spansh_request(
            "GET",
            "/api/nearest",
            params={"x": x, "y": y, "z": z},
            timeout=timeout,
        )
        if response.status_code != 200:
            raise _SpanshPollError(
                WebUtils.get_error_message(response, f"API error: {response.status_code}"),
                status_code=response.status_code,
            )
        payload = WebUtils.parse_json(response, default={})
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
        except (_SpanshPollError, RequestException):
            self._log_unexpected("Nearest system lookup failed")
        return ""

    def _resolve_valid_source_record(self, source, *, require_id64=False):
        source = (source or "").strip()
        if not source:
            return (False, None, None, "Source system is empty.")

        try:
            record = self._resolve_system_record(source)
        except RequestException as exc:
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

    def _set_plot_running_state(self, *, active, exact=False, use_enable_plot_gui=False, button=None):
        """Toggle the "Computing..." button animation and enable/disable plotter controls."""
        if active:
            self._mark_plot_started(exact=exact)
        else:
            self._mark_plot_stopped(exact=exact)

        if use_enable_plot_gui:
            self.enable_plot_gui(not active)
        else:
            self._set_main_controls_enabled(not active)
            self._set_plotter_windows_enabled(not active)

        self._set_plot_button_busy_state(button, active=active, exact=exact)

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
        return WebUtils.submit_spansh_job_request(
            api_url,
            params=params,
            data=data,
            timeout=timeout,
            poll_interval=SPANSH_POLL_INTERVAL,
            max_iterations=SPANSH_POLL_MAX_ITERATIONS,
            results_base=results_base,
            accept_direct_result=accept_direct_result,
            direct_result_keys=direct_result_keys,
            cancel_checker=lambda: self._cancel_flag_from_attr(cancel_attr),
        )

    # --- Tools ---

    def _bind_select_all_text(self, widget):
        from .widgets import bind_select_all_and_paste
        bind_select_all_and_paste(widget)
