import queue
import threading
import tkinter as tk

from .web_utils import WebUtils
from .widgets import PlaceHolder
from .constants import MAX_VISIBLE_RESULTS, DEBOUNCE_MS, logger


class AutoCompleter(PlaceHolder):
    """Entry with dropdown auto-complete, populated by a background Spansh system search."""

    def _current_trace_id(self):
        return getattr(self, "_trace_id", None)

    def is_effectively_empty(self):
        value = self.get().strip()
        return not value or value == self.placeholder

    def _bind_change_trace(self):
        self._trace_id = self.var.trace('w', self.changed)

    def _replace_text_without_trace(self, text):
        try:
            trace_id = self._current_trace_id()
            if trace_id is not None:
                self.var.trace_remove("write", trace_id)
        except Exception:
            pass
        self.delete(0, tk.END)
        self.insert(0, text)
        self._bind_change_trace()

    def _cancel_debounce(self):
        if self._debounce_id is None:
            return
        try:
            self.after_cancel(self._debounce_id)
        except Exception:
            pass
        self._debounce_id = None

    def _discard_query_state(self):
        self._query_generation += 1
        self.hide_list()
        self.has_selected = False

    def _next_list_index(self, step):
        selection = self.lb.curselection()
        if not selection:
            return 0 if step > 0 else None
        index = int(selection[0])
        next_index = index + step
        if not (0 <= next_index < self.lb.size()):
            return index
        self.lb.selection_clear(first=index)
        return next_index

    def _move_selection(self, step, widget):
        if not self.lb_up:
            if step > 0:
                self.changed()
            return
        index = self._next_list_index(step)
        if index is None:
            return
        self.lb.selection_set(first=index)
        self.lb.see(index)
        if widget != "listbox":
            self.lb.activate(index)

    def __init__(self, parent, placeholder, **kw):
        self.on_select = kw.pop("on_select", None)
        self.selected_items_provider = kw.pop("selected_items_provider", None)

        self.parent = parent
        entry_kw = dict(kw)
        listbox_kw = {key: kw[key] for key in ("width", "font") if key in kw}

        self.lb = tk.Listbox(self.parent, selectmode=tk.SINGLE, **listbox_kw)
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
        self._trace_id = None

        PlaceHolder.__init__(self, parent, placeholder, **entry_kw)
        if self._trace_id is None:
            self._bind_change_trace()

        self.menu = tk.Menu(self.parent, tearoff=0)
        self.menu.add_command(label="Cut")
        self.menu.add_command(label="Copy")
        self.menu.add_command(label="Paste")

        self.bind("<Any-Key>", self.keypressed)
        self.lb.bind("<Any-Key>", self.keypressed)
        self.bind("<Return>", self._handle_return)
        self.bind("<KP_Enter>", self._handle_return)
        self.lb.bind("<Return>", self._handle_return)
        self.lb.bind("<KP_Enter>", self._handle_return)
        self.bind('<Button-3>', self.show_menu)
        self.lb.bind("<ButtonRelease-1>", self.selection)
        self.bind("<FocusOut>", self.ac_foc_out)
        self.lb.bind("<FocusOut>", self.ac_foc_out)

        self._update_id = None
        self.bind("<Destroy>", self._on_destroy)

    def _schedule_update(self):
        if not self._destroyed and self._update_id is None:
            self._update_id = self.after(100, self._flush_results_queue)

    def _on_destroy(self, event=None):
        self._destroyed = True
        self._query_generation += 1
        self._cancel_debounce()
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
        self.lb_up = False
        for widget in (getattr(self, "lb", None), getattr(self, "menu", None)):
            try:
                if widget is not None:
                    widget.destroy()
            except Exception:
                pass

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
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def keypressed(self, event):
        key = event.keysym
        if self._placeholder_visible and event.char and event.char.isprintable():
            self.set_default_style()
            self.delete(0, tk.END)
            self._placeholder_visible = False
            self.has_selected = False
            return
        if key == 'Down':
            self.down(event.widget.widgetName)
        elif key == 'Up':
            self.up(event.widget.widgetName)
        elif key in ['Return', 'Right']:
            if self.lb_up:
                self.selection()
        elif key in ['Escape', 'Tab', 'ISO_Left_Tab'] and self.lb_up:
            self.hide_list()

    def _handle_return(self, event=None):
        if self.lb_up:
            self.selection()
            return "break"

    def changed(self, name=None, index=None, mode=None):
        if self._destroyed:
            return
        if self._error_state:
            self.set_default_style()
        value = self.var.get()
        stripped = value.strip()
        self._cancel_debounce()
        if self.has_selected or stripped == self.placeholder or len(stripped) < 3:
            self._discard_query_state()
            return
        self._debounce_id = self.after(DEBOUNCE_MS, lambda v=value: self._queue_query(v))

    def _queue_query(self, value):
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
                self._fetch_query_results(*item)
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
            self._replace_text_without_trace(self._result_values[selected_index])
            self.hide_list()
            self.icursor(tk.END)
            if callable(self.on_select):
                try:
                    self.on_select(self.get().strip())
                except Exception:
                    self._log_unexpected("AutoCompleter on_select callback failed")

    def up(self, widget):
        self._move_selection(-1, widget)

    def down(self, widget):
        self._move_selection(1, widget)

    def show_results(self, results):
        if self._destroyed:
            return
        if results:
            self._result_values = [str(value) for value in results]
            self.lb.delete(0, tk.END)
            for w in self._build_display_results(self._result_values):
                self.lb.insert(tk.END, w)

            self.show_list(len(results))
        else:
            self._result_values = []
            if self.lb_up:
                self.hide_list()

    def show_list(self, height):
        self.lb["height"] = min(height, MAX_VISIBLE_RESULTS)
        if not self.lb_up and self.parent.focus_get() is self:
            # The popup list inherits the entry's grid position and is shown on the next row.
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

    def _fetch_query_results(self, inp, generation=None):
        inp = inp.strip()
        try:
            if inp != self.placeholder and len(inp) >= 3:
                try:
                    lista = WebUtils.spansh_get("/api/systems", params={'q': inp}, timeout=3)
                    if generation is not None and generation != self._query_generation:
                        return
                    self._enqueue_results(lista if isinstance(lista, list) else [], generation=generation)
                except Exception:
                    # WebUtils handles logging, we just need to ensure we don't crash the background thread
                    if generation is not None and generation != self._query_generation:
                        return
                    self._enqueue_results([], generation=generation)
            else:
                self._enqueue_results([], generation=generation)
        finally:
            with self._query_lock:
                self._active_queries = 1 if self._pending_query is not None else 0

    def _enqueue_results(self, lista, generation=None):
        self.queue.put((generation, lista))

    def _flush_results_queue(self):
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
        self._replace_text_without_trace(text)
