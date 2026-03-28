"""Reusable tkinter UI widgets and input helpers."""

import tkinter as tk
from tkinter import ttk


def validate_integer_input(proposed, *, signed=False):
    if proposed == "":
        return True
    if signed and proposed == "-":
        return True
    if signed:
        if proposed.startswith("-"):
            return proposed[1:].isdigit()
        return proposed.isdigit()
    return proposed.isdigit()


def validate_decimal_input(proposed, *, maximum_decimals=2):
    if proposed in {"", "."}:
        return True
    if proposed.count(".") > 1:
        return False
    whole, dot, fractional = proposed.partition(".")
    if whole and not whole.isdigit():
        return False
    if dot and len(fractional) > maximum_decimals:
        return False
    return fractional.isdigit() or fractional == ""


def validate_spinbox_input(
    proposed,
    *,
    allow_float=False,
    maximum_decimals=2,
    signed=False,
    max_digits=None,
):
    if allow_float:
        if not validate_decimal_input(proposed, maximum_decimals=maximum_decimals):
            return False
    else:
        if not validate_integer_input(proposed, signed=signed):
            return False

    if proposed in {"", "-", ".", "-."}:
        return True

    if max_digits is None:
        return True

    normalized = str(proposed)
    if signed and normalized.startswith("-"):
        normalized = normalized[1:]

    if allow_float:
        whole, _, _fractional = normalized.partition(".")
        if len(whole) > max_digits:
            return False
        return True

    if len(normalized) > max_digits:
        return False
    return True


def make_spinbox_validator(
    widget,
    *,
    allow_float=False,
    maximum_decimals=2,
    signed=False,
    safe_float=float,
):
    try:
        maximum = safe_float(widget.cget("to"), None)
    except Exception:
        maximum = None
    max_digits = len(str(abs(int(maximum)))) if maximum is not None else None
    return (
        widget.register(
            lambda proposed: validate_spinbox_input(
                proposed,
                allow_float=allow_float,
                maximum_decimals=maximum_decimals,
                signed=signed,
                max_digits=max_digits,
            )
        ),
        "%P",
    )


def clamp_numeric_input(
    widget,
    minimum,
    maximum,
    *,
    integer=False,
    error_message="Invalid number",
    set_entry_value,
):
    raw = widget.get().strip()
    try:
        value = int(float(raw)) if integer else float(raw)
    except ValueError:
        raise ValueError(error_message)

    value = max(minimum, min(maximum, value))
    if integer:
        value = int(value)
    set_entry_value(widget, value)
    return value


def clamp_spinbox_input(
    widget,
    *,
    integer=False,
    error_message="Invalid number",
    safe_float=float,
    set_entry_value,
):
    try:
        minimum = float(widget.cget("from"))
        maximum = float(widget.cget("to"))
    except Exception:
        raise ValueError(error_message)
    return clamp_numeric_input(
        widget,
        minimum,
        maximum,
        integer=integer,
        error_message=error_message,
        set_entry_value=set_entry_value,
    )


def live_clamp_spinbox_input(
    widget,
    *,
    integer=False,
    parse_number,
    set_entry_value,
):
    try:
        minimum = float(widget.cget("from"))
        maximum = float(widget.cget("to"))
    except Exception:
        return

    raw = widget.get().strip()
    if raw in {"", "-", ".", "-."}:
        return

    parsed = parse_number(raw)
    if parsed is None:
        return

    value = int(parsed) if integer else float(parsed)
    clamped = max(minimum, min(maximum, value))
    if integer:
        clamped = int(clamped)

    current = int(parsed) if integer else float(parsed)
    if clamped != current:
        set_entry_value(widget, clamped)


def bind_live_spinbox_clamp(widget, callback):
    widget.bind("<KeyRelease>", callback, add="+")
    widget.bind("<FocusOut>", callback, add="+")


class Tooltip:
    """Simple hover tooltip for tkinter widgets."""
    _OFFSET_X = 15
    _OFFSET_Y = 20

    def __init__(self, widget, text):
        self.widget = widget
        self._text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value
        if self.tipwindow:
            self.hide()
            self.show()

    def show(self, event=None):
        if self.tipwindow:
            return
        if event is not None and hasattr(event, "x_root") and hasattr(event, "y_root"):
            x = event.x_root + self._OFFSET_X
            y = event.y_root + self._OFFSET_Y
        else:
            x = self.widget.winfo_rootx() + self._OFFSET_X
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + self._OFFSET_Y
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self._text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         wraplength=250, padx=5, pady=3)
        label.pack()

    def hide(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class DraggableListWidget:
    """Scrollable list with drag-and-drop reordering.

    The caller builds row widgets into ``self.inner``, then calls
    ``refresh_layout(row_widgets)`` to calibrate heights and scrolling.
    Drag-and-drop reorders the backing ``items`` list automatically and
    invokes ``on_reorder()`` so the caller can rebuild the display.
    """

    def __init__(self, parent, height=164, visible_rows=6):
        self._items = []
        self._selected_index = None
        self._row_widgets = []
        self._row_height = 28
        self._visible_rows = visible_rows
        self._drag_index = None
        self._drag_active = False
        self._drag_start_root_y = 0
        self.on_reorder = None   # callback after drag reorder
        self.on_select = None    # callback(index) on click without drag

        # --- widgets ---
        self.border = tk.Frame(parent, relief=tk.SUNKEN, borderwidth=1)
        self.border.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self.border, height=height, highlightthickness=0,
            relief=tk.FLAT, borderwidth=0,
        )
        self.canvas.grid(row=0, column=0, sticky=tk.EW)
        self.scrollbar = ttk.Scrollbar(
            self.border, orient=tk.VERTICAL, command=self.canvas.yview,
        )
        self.scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.inner = tk.Frame(self.canvas)
        self.inner.columnconfigure(0, weight=1)
        self._window_id = self.canvas.create_window(
            (2, 2), window=self.inner, anchor="nw",
        )
        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all"),
            ),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(
                self._window_id, width=max(0, e.width - 4),
            ),
        )
        for w in (self.canvas, self.inner):
            w.bind("<B1-Motion>", self._on_drag_motion, add="+")
            w.bind("<ButtonRelease-1>", self._on_drop, add="+")
            w.bind("<MouseWheel>", self._on_mousewheel, add="+")
            w.bind("<Button-4>", self._on_mousewheel, add="+")
            w.bind("<Button-5>", self._on_mousewheel, add="+")

    # --- public helpers ---

    @property
    def selected_index(self):
        return self._selected_index

    @selected_index.setter
    def selected_index(self, value):
        self._selected_index = value

    def set_items(self, items):
        """Set the backing list that drag-and-drop mutates in place."""
        self._items = items

    def bind_row_events(self, widget, index):
        """Bind drag + scroll events to a row widget."""
        widget.bind(
            "<ButtonPress-1>",
            lambda e, i=index: self._start_drag(e, i), add="+",
        )
        widget.bind("<B1-Motion>", self._on_drag_motion, add="+")
        widget.bind("<ButtonRelease-1>", self._on_drop, add="+")
        self.bind_scroll_events(widget)

    def bind_scroll_events(self, widget):
        """Bind only scroll events (for non-draggable child widgets)."""
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_mousewheel, add="+")

    def refresh_layout(self, row_widgets):
        """Calibrate row heights and scroll region after rows are built."""
        self._row_widgets = row_widgets
        self.inner.update_idletasks()
        if self._row_widgets:
            try:
                row_height = max(
                    self._row_widgets[0].winfo_height(),
                    self._row_widgets[0].winfo_reqheight(),
                )
                if len(self._row_widgets) >= 2:
                    row_step = max(
                        1,
                        self._row_widgets[1].winfo_y()
                        - self._row_widgets[0].winfo_y(),
                    )
                else:
                    row_step = row_height + 4
                self._row_height = max(1, row_step)
                self.canvas.configure(yscrollincrement=self._row_height)
                self.canvas.configure(
                    height=(row_step * self._visible_rows) + 4,
                )
            except Exception:
                pass
        try:
            self.canvas.update_idletasks()
            inner_height = max(0, self.inner.winfo_reqheight())
            inner_width = max(0, self.canvas.winfo_width())
            self.canvas.configure(
                scrollregion=(0, 0, inner_width, inner_height + 4),
            )
        except Exception:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if len(self._items) <= self._visible_rows:
            self.canvas.yview_moveto(0)
        self._clamp_scroll()

    def select_line(self, index):
        """Select *index*, refresh via on_reorder, and scroll into view."""
        if not (0 <= index < len(self._items)):
            self._selected_index = None
            if self.on_reorder:
                self.on_reorder()
            return
        self._selected_index = index
        if self.on_reorder:
            self.on_reorder()
        if len(self._items) <= self._visible_rows:
            self.canvas.yview_moveto(0)
            self._clamp_scroll()
            return
        if 0 <= index < len(self._row_widgets):
            widget = self._row_widgets[index]
            try:
                top = widget.winfo_y()
                bottom = top + widget.winfo_height()
                view_top = self.canvas.canvasy(0)
                view_bottom = view_top + self.canvas.winfo_height()
                row_step = max(1, self._row_height)
                if top < view_top:
                    self.canvas.yview_scroll(
                        int((top - view_top) / row_step), "units",
                    )
                elif bottom > view_bottom:
                    self.canvas.yview_scroll(
                        int((bottom - view_bottom + row_step - 1) / row_step),
                        "units",
                    )
            except Exception:
                pass
        self._clamp_scroll()

    # --- internal: drag ---

    def _start_drag(self, event, index):
        self._drag_index = index
        self._drag_active = False
        self._drag_start_root_y = event.y_root
        self._selected_index = index

    def _on_drag_motion(self, event):
        if self._drag_index is None:
            return
        if not self._drag_active and abs(event.y_root - self._drag_start_root_y) >= 4:
            self._drag_active = True
            try:
                self.canvas.configure(cursor="fleur")
            except Exception:
                pass
        if self._drag_active:
            self._autoscroll_drag(event.y_root)
            target = self._drop_index(event.y_root)
            if (
                target is not None
                and 0 <= target < len(self._items)
                and target != self._drag_index
            ):
                item = self._items.pop(self._drag_index)
                self._items.insert(target, item)
                self._drag_index = target
                self._selected_index = target
                if self.on_reorder:
                    self.on_reorder()

    def _on_drop(self, event):
        try:
            if self._drag_index is None:
                return "break"
            if not self._drag_active:
                if self.on_select:
                    self.on_select(self._drag_index)
                else:
                    self.select_line(self._drag_index)
            return "break"
        finally:
            self._drag_index = None
            self._drag_active = False
            try:
                self.canvas.configure(cursor="")
            except Exception:
                pass

    def _drop_index(self, root_y):
        if not self._row_widgets:
            return None
        canvas_y = self.canvas.canvasy(root_y - self.canvas.winfo_rooty())
        for index, widget in enumerate(self._row_widgets):
            midpoint = widget.winfo_y() + (widget.winfo_height() / 2)
            if canvas_y < midpoint:
                return index
        return len(self._row_widgets) - 1

    def _autoscroll_drag(self, root_y):
        if not self._can_scroll():
            self.canvas.yview_moveto(0)
            return
        try:
            top = self.canvas.winfo_rooty()
            bottom = top + self.canvas.winfo_height()
        except Exception:
            return
        margin = 18
        if root_y <= top + margin:
            self.canvas.yview_scroll(-1, "units")
        elif root_y >= bottom - margin:
            self.canvas.yview_scroll(1, "units")
        self._clamp_scroll()

    # --- internal: scroll ---

    def _can_scroll(self):
        try:
            inner_height = self.inner.winfo_reqheight()
            canvas_height = self.canvas.winfo_height()
            return inner_height > canvas_height
        except Exception:
            return len(self._items) > self._visible_rows

    def _clamp_scroll(self):
        try:
            first, last = self.canvas.yview()
        except Exception:
            return
        if first < 0:
            self.canvas.yview_moveto(0)
        elif last > 1:
            self.canvas.yview_moveto(max(0, 1 - (last - first)))

    def _on_mousewheel(self, event):
        if not self._can_scroll():
            self.canvas.yview_moveto(0)
            return "break"
        if hasattr(event, "delta") and event.delta:
            step = -1 if event.delta > 0 else 1
        elif getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            return "break"
        self.canvas.yview_scroll(step, "units")
        self._clamp_scroll()
        return "break"
