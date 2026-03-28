import logging
import os
import queue
import threading
from tkinter import *

import requests
from .PlaceHolder import PlaceHolder

from config import appname

# We need a name of plugin dir, not AutoCompleter.py dir
plugin_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
logger = logging.getLogger(f'{appname}.{plugin_name}')

MAX_VISIBLE_RESULTS = 10
DEBOUNCE_MS = 250


class AutoCompleter(PlaceHolder):
    def __init__(self, parent, placeholder, **kw):
        self.on_select = kw.pop("on_select", None)
        self.selected_items_provider = kw.pop("selected_items_provider", None)

        self.parent = parent
        entry_kw = dict(kw)
        listbox_kw = {key: kw[key] for key in ("width", "font") if key in kw}

        self.lb = Listbox(self.parent, selectmode=SINGLE, **listbox_kw)
        self.lb_up = False
        self.has_selected = False
        self.queue = queue.Queue()
        self._debounce_id = None
        self._query_generation = 0
        self._active_queries = 0
        self._query_lock = threading.Lock()
        self._query_event = threading.Event()
        self._query_worker = None
        self._pending_query = None
        self._destroyed = False
        self._result_values = []

        PlaceHolder.__init__(self, parent, placeholder, **entry_kw)
        self.var.traceid = self.var.trace('w', self.changed)

        # Create right click menu
        self.menu = Menu(self.parent, tearoff=0)
        self.menu.add_command(label="Cut")
        self.menu.add_command(label="Copy")
        self.menu.add_command(label="Paste")

        self.bind("<Any-Key>", self.keypressed)
        self.lb.bind("<Any-Key>", self.keypressed)
        self.bind('<Control-KeyRelease-a>', self.select_all)
        self.bind('<Button-3>', self.show_menu)
        self.lb.bind("<ButtonRelease-1>", self.selection)
        self.bind("<FocusOut>", self.ac_foc_out)
        self.lb.bind("<FocusOut>", self.ac_foc_out)

        self._update_id = None
        self.bind("<Destroy>", self._on_destroy)

    def _schedule_update(self):
        if not self._destroyed and self._update_id is None:
            self._update_id = self.after(100, self.update_me)

    def _on_destroy(self, event=None):
        self._destroyed = True
        self._query_generation += 1
        if self._debounce_id is not None:
            try:
                self.after_cancel(self._debounce_id)
            except Exception:
                pass
            self._debounce_id = None
        if self._update_id is not None:
            try:
                self.after_cancel(self._update_id)
            except Exception:
                pass
            self._update_id = None
        with self._query_lock:
            self._pending_query = None
            self._active_queries = 0
        self._query_event.set()

    def _log_unexpected(self, context):
        logger.warning(context, exc_info=True)

    def ac_foc_out(self, event=None):
        x, y = self.parent.winfo_pointerxy()
        widget_under_cursor = self.parent.winfo_containing(x, y)
        if (widget_under_cursor != self.lb and widget_under_cursor != self) or event is None:
            self.foc_out()
            self.hide_list()

    def show_menu(self, e):
        self.foc_in()
        w = e.widget
        self.menu.entryconfigure("Cut",
                                 command=lambda: w.event_generate("<<Cut>>"))
        self.menu.entryconfigure("Copy",
                                 command=lambda: w.event_generate("<<Copy>>"))
        self.menu.entryconfigure("Paste",
                                 command=lambda: w.event_generate("<<Paste>>"))
        self.menu.tk.call("tk_popup", self.menu, e.x_root, e.y_root)

    def keypressed(self, event):
        key = event.keysym
        if key == 'Down':
            self.down(event.widget.widgetName)
        elif key == 'Up':
            self.up(event.widget.widgetName)
        elif key in ['Return', 'Right']:
            if self.lb_up:
                self.selection()
        elif key in ['Escape', 'Tab', 'ISO_Left_Tab'] and self.lb_up:
            self.hide_list()

    def select_all(self, event):
        event.widget.event_generate('<<SelectAll>>')

    def changed(self, name=None, index=None, mode=None):
        if self._destroyed:
            return
        value = self.var.get()
        stripped = value.strip()
        if self.has_selected or stripped == self.placeholder or len(stripped) < 3:
            if self._debounce_id is not None:
                try:
                    self.after_cancel(self._debounce_id)
                except Exception:
                    pass
                self._debounce_id = None
            self._query_generation += 1
            self.hide_list()
            self.has_selected = False
        else:
            # Cancel any pending debounce and schedule a new one
            if self._debounce_id is not None:
                try:
                    self.after_cancel(self._debounce_id)
                except Exception:
                    pass
            self._debounce_id = self.after(
                DEBOUNCE_MS,
                lambda v=value: self._fire_query(v)
            )

    def _fire_query(self, value):
        """Queue the latest query for a shared background worker."""
        self._debounce_id = None
        if self._destroyed:
            return
        self._query_generation += 1
        gen = self._query_generation
        with self._query_lock:
            self._pending_query = (value, gen)
            self._active_queries = 1
            worker = self._query_worker
            if worker is None or not worker.is_alive():
                worker = threading.Thread(target=self._query_worker_loop, daemon=True)
                self._query_worker = worker
                worker.start()
        self._schedule_update()
        self._query_event.set()

    def _query_worker_loop(self):
        while True:
            self._query_event.wait()
            if self._destroyed:
                return
            while True:
                with self._query_lock:
                    item = self._pending_query
                    if item is None:
                        self._active_queries = 0
                        self._query_event.clear()
                        break
                    self._pending_query = None
                self.query_systems(*item)
                if self._destroyed:
                    return

    def selection(self, event=None):
        if self.lb_up:
            sel = self.lb.curselection()
            if not sel:
                return
            selected_index = sel[0]
            if selected_index >= len(self._result_values):
                return
            self.has_selected = True
            self.var.trace_vdelete("w", self.var.traceid)
            self.var.set(self._result_values[selected_index])
            self.hide_list()
            self.icursor(END)
            self.var.traceid = self.var.trace('w', self.changed)
            if callable(self.on_select):
                try:
                    self.on_select(self.get().strip())
                except Exception:
                    self._log_unexpected("AutoCompleter on_select callback failed")

    def up(self, widget):
        if self.lb_up:
            if self.lb.curselection() == ():
                index = 0
            else:
                index = int(self.lb.curselection()[0])
            if index > 0:
                self.lb.selection_clear(first=index)
                index -= 1
                self.lb.selection_set(first=index)
                if widget != "listbox":
                    self.lb.activate(index)

    def down(self, widget):
        if self.lb_up:
            if self.lb.curselection() == ():
                index = 0
            else:
                index = int(self.lb.curselection()[0])
                if index + 1 < self.lb.size():
                    self.lb.selection_clear(first=index)
                    index += 1

            self.lb.selection_set(first=index)
            if widget != "listbox":
                self.lb.activate(index)
        else:
            self.changed()

    def show_results(self, results):
        if self._destroyed:
            return
        if results:
            self._result_values = [str(value) for value in results]
            self.lb.delete(0, END)
            for w in self._build_display_results(self._result_values):
                self.lb.insert(END, w)

            self.show_list(len(results))
        else:
            self._result_values = []
            if self.lb_up:
                self.hide_list()

    def show_list(self, height):
        self.lb["height"] = min(height, MAX_VISIBLE_RESULTS)
        if not self.lb_up and self.parent.focus_get() is self:
            info = self.grid_info()
            if info:
                grid_kwargs = {}
                for key in ("column", "columnspan", "sticky", "padx", "pady"):
                    if key in info:
                        grid_kwargs[key] = info[key]
                self.lb.grid(row=int(info["row"]) + 1, **grid_kwargs)
                self.lb.lift()
                self.lb_up = True

    def hide_list(self):
        if self.lb_up:
            self.lb.grid_remove()
            self.lb_up = False

    def _normalized_selected_items(self):
        if not callable(self.selected_items_provider):
            return set()
        try:
            values = self.selected_items_provider() or []
        except Exception:
            self._log_unexpected("AutoCompleter selected-items provider failed")
            return set()
        return {
            str(value).strip().lower()
            for value in values
            if str(value).strip()
        }

    def _build_display_results(self, results):
        selected_items = self._normalized_selected_items()
        if not selected_items:
            return list(results)
        display_results = []
        for result in results:
            normalized = str(result).strip().lower()
            if normalized not in selected_items:
                display_results.append(result)
                continue
            display_results.append(f"✓ {result}")
        return display_results

    def query_systems(self, inp, generation=None):
        inp = inp.strip()
        try:
            if inp != self.placeholder and len(inp) >= 3:
                url = "https://spansh.co.uk/api/systems?"
                try:
                    results = requests.get(url,
                                           params={'q': inp},
                                           headers={'User-Agent': "EDMC_SpanshTools 1.0"},
                                           timeout=3)

                    if generation is not None and generation != self._query_generation:
                        return

                    if results.status_code != 200:
                        logger.debug("AutoCompleter query returned status %s", results.status_code)
                        self.write([], generation=generation)
                        return

                    lista = results.json()
                    self.write(lista if isinstance(lista, list) else [], generation=generation)
                except (requests.RequestException, ValueError):
                    self._log_unexpected("AutoCompleter query failed")
                    self.write([], generation=generation)
            else:
                self.write([], generation=generation)
        finally:
            with self._query_lock:
                self._active_queries = 1 if self._pending_query is not None else 0
            self._schedule_update()

    def write(self, lista, generation=None):
        self.queue.put((generation, lista))


    def update_me(self):
        if self._destroyed:
            self._update_id = None
            return
        try:
            while 1:
                generation, lista = self.queue.get_nowait()
                if generation is not None and generation != self._query_generation:
                    continue
                self.show_results(lista)
        except queue.Empty:
            pass
        self._update_id = None
        with self._query_lock:
            keep_polling = self._active_queries > 0
        if keep_polling or not self.queue.empty():
            self._schedule_update()

    def set_text(self, text, placeholder_style=True):
        if placeholder_style:
            self._placeholder_visible = True
            self._error_state = False
            self['fg'] = self.placeholder_color
        else:
            self._placeholder_visible = False
            self.set_default_style()

        try:
            self.var.trace_vdelete("w", self.var.traceid)
        except Exception:
            pass
        finally:
            self.delete(0, END)
            self.insert(0, text)
            self.var.traceid = self.var.trace('w', self.changed)


if __name__ == '__main__':
    root = Tk()

    widget = AutoCompleter(root, "Test")
    widget.grid(row=0)
    root.mainloop()
