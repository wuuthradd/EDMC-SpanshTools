"""Reusable tkinter UI widgets and input helpers."""

import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk

from config import config
from .constants import logger


# --- Text Measurement Utilities ---

def measure_text_px(text):
    try:
        font = tkFont.nametofont("TkDefaultFont")
        return font.measure(text)
    except Exception:
        # Fallback for test environments where Tcl 'font' command is missing
        return len(text) * 9


def truncate_text_px(text, max_px, suffix="..."):
    if not text:
        return "", False
    if measure_text_px(text) <= max_px:
        return text, False

    trimmed = ""
    for char in text:
        candidate = trimmed + char + suffix
        if measure_text_px(candidate) > max_px:
            return trimmed + suffix, True
        trimmed += char
    return text, False



# --- Input Validation ---

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


def validate_decimal_input(proposed, *, maximum_decimals=2, signed=False):
    if proposed in {"", "."}:
        return True
    if signed and proposed in {"-", "-."}:
        return True
    
    if proposed.count(".") > 1:
        return False
        
    whole, dot, fractional = proposed.partition(".")
    
    # Handle sign for decimal validation
    if signed and whole.startswith("-"):
        whole = whole[1:]
        
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
        if not validate_decimal_input(proposed, maximum_decimals=maximum_decimals, signed=signed):
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



# --- Spinbox Helpers ---

def make_spinbox_validator(
    widget,
    *,
    allow_float=False,
    maximum_decimals=2,
    signed=False,
    safe_float=None,
):
    def _coerce_numeric(value):
        if safe_float is None:
            return float(value)
        try:
            return safe_float(value, None)
        except TypeError:
            return safe_float(value)

    try:
        minimum = _coerce_numeric(widget.cget("from"))
        maximum = _coerce_numeric(widget.cget("to"))
    except Exception:
        minimum = None
        maximum = None
    digit_bound = None
    if minimum is not None or maximum is not None:
        magnitudes = []
        if minimum is not None:
            magnitudes.append(abs(int(minimum)))
        if maximum is not None:
            magnitudes.append(abs(int(maximum)))
        digit_bound = max(magnitudes) if magnitudes else None
    max_digits = len(str(digit_bound)) if digit_bound is not None else None
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

def clamp_spinbox_input(
    widget,
    *,
    integer=False,
    parse_number=None,
    tolerate_intermediate=False,
    return_none_on_invalid=False,
    error_message="Invalid number",
    set_entry_value,
):
    """Parse, clamp to the spinbox from/to range, and write back if the value was out of bounds."""
    try:
        minimum = float(widget.cget("from"))
        maximum = float(widget.cget("to"))
    except Exception:
        if return_none_on_invalid:
            return None
        raise ValueError(error_message)

    raw = widget.get().strip()
    if tolerate_intermediate and raw in {"", "-", ".", "-."}:
        return None
    if tolerate_intermediate and not integer and raw.endswith("."):
        return None

    if parse_number is None:
        try:
            parsed = int(float(raw)) if integer else float(raw)
        except ValueError:
            if return_none_on_invalid:
                return None
            raise ValueError(error_message)
    else:
        parsed = parse_number(raw)
        if parsed is None:
            if return_none_on_invalid:
                return None
            raise ValueError(error_message)
        parsed = int(parsed) if integer else float(parsed)

    clamped = max(minimum, min(maximum, parsed))
    if integer:
        clamped = int(clamped)

    if clamped != parsed:
        set_entry_value(widget, clamped)
    elif not tolerate_intermediate:
        set_entry_value(widget, clamped)

    return clamped


def bind_select_all_and_paste(widget, *, on_after_paste=None):
    entry_like_types = (tk.Entry, tk.Spinbox)

    def _select_all(_event=None):
        try:
            if isinstance(widget, entry_like_types):
                widget.selection_range(0, tk.END)
                widget.icursor(tk.END)
            else:
                widget.tag_add(tk.SEL, "1.0", "end-1c")
                widget.mark_set(tk.INSERT, tk.END)
                widget.see(tk.INSERT)
        except Exception:
            pass
        return "break"

    def _paste_replace_selection(_event=None):
        try:
            pasted_text = widget.clipboard_get()
        except Exception:
            return "break"
        try:
            if isinstance(widget, entry_like_types):
                if widget.selection_present():
                    widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                widget.insert(tk.INSERT, pasted_text)
            else:
                if widget.tag_ranges(tk.SEL):
                    widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                widget.insert(tk.INSERT, pasted_text)
        except Exception:
            pass
        if callable(on_after_paste):
            try:
                widget.after_idle(on_after_paste)
            except Exception:
                try:
                    on_after_paste()
                except Exception:
                    logger.debug("Exception in paste callback", exc_info=True)
        return "break"

    if not hasattr(widget, "bind"):
        return

    widget.bind("<Control-a>", _select_all, add="+")
    widget.bind("<Control-A>", _select_all, add="+")
    widget.bind("<Control-v>", _paste_replace_selection, add="+")
    widget.bind("<Control-V>", _paste_replace_selection, add="+")
    widget.bind("<<Paste>>", _paste_replace_selection)


def setup_spinbox(
    widget,
    *,
    allow_float=False,
    maximum_decimals=2,
    signed=False,
    integer=False,
    safe_float=None,
    parse_number=None,
    set_entry_value=None,
):
    """Wire up validation, keyboard/mouse empty-field handling, and auto-clamp on the spinbox."""
    widget.configure(
        validate="key",
        validatecommand=make_spinbox_validator(
            widget,
            allow_float=allow_float,
            maximum_decimals=maximum_decimals,
            signed=signed,
            safe_float=safe_float,
        ),
    )

    def _apply(_event=None):
        if parse_number is None or set_entry_value is None:
            return
        try:
            widget.after_idle(
                lambda w=widget: clamp_spinbox_input(
                    w,
                    integer=integer,
                    parse_number=parse_number,
                    tolerate_intermediate=True,
                    return_none_on_invalid=True,
                    set_entry_value=set_entry_value,
                )
            )
        except Exception:
            try:
                clamp_spinbox_input(
                    widget,
                    integer=integer,
                    parse_number=parse_number,
                    tolerate_intermediate=True,
                    return_none_on_invalid=True,
                    set_entry_value=set_entry_value,
                )
            except Exception:
                logger.debug("Exception in spinbox callback", exc_info=True)

    _empty = lambda: widget.get().strip() in {"", "-", ".", "-."}
    _set = lambda v: (widget.delete(0, tk.END), widget.insert(0, v))
    _incr = float(widget.cget("increment")) or 1.0
    _from, _to = float(widget.cget("from")), float(widget.cget("to"))
    _up_v, _down_v = max(_from, min(_to, _incr)), max(_from, min(_to, -_incr))
    _up = str(int(_up_v)) if _up_v == int(_up_v) else str(_up_v)
    _down = str(int(_down_v)) if _down_v == int(_down_v) else str(_down_v)
    widget.bind("<Up>", lambda e: (_set(_up), "break")[-1] if _empty() else None)
    widget.bind("<Down>", lambda e: (_set(_down), "break")[-1] if _empty() else None)
    _spin_flag = [False]
    widget.bind("<ButtonPress-1>", lambda e: _spin_flag.__setitem__(0, widget.identify(e.x, e.y)) if _empty() and widget.identify(e.x, e.y) in ("buttonup", "buttondown") else None, add="+")
    widget.configure(command=lambda: (_set(_up if _spin_flag[0] == "buttonup" else _down), _spin_flag.__setitem__(0, False)) if _spin_flag[0] in ("buttonup", "buttondown") else _spin_flag.__setitem__(0, False))

    widget.bind("<KeyRelease>", _apply, add="+")
    widget.bind("<FocusOut>", _apply, add="+")
    bind_select_all_and_paste(widget, on_after_paste=_apply)



# --- PlaceHolder Widget ---

class PlaceHolder(tk.Entry):
    """Entry widget that shows greyed placeholder text when empty and clears it on focus."""

    def __init__(self, parent, placeholder, **kw):
        super().__init__(parent, **kw)
        self.var = self["textvariable"] = tk.StringVar()
        self.placeholder = placeholder
        self.placeholder_color = "grey"
        self._placeholder_visible = False
        self._error_state = False

        self.bind("<FocusIn>", self.foc_in)
        self.bind("<FocusOut>", self.foc_out)
        bind_select_all_and_paste(self)

        self.put_placeholder()

    def put_placeholder(self):
        if self.get() != self.placeholder:
            self.set_text(self.placeholder, True)

    def set_text(self, text, placeholder_style=True):
        if placeholder_style:
            self._placeholder_visible = True
            self._error_state = False
            self["fg"] = self.placeholder_color
        else:
            self._placeholder_visible = False
            self.set_default_style()
        self.delete(0, tk.END)
        self.insert(0, text)

    def set_default_style(self):
        theme = config.get_int("theme")
        self._error_state = False
        self["fg"] = (config.get_str("dark_text") or "white") if theme else "black"

    def set_error_style(self, error=True):
        if error:
            self._placeholder_visible = False
            self._error_state = True
            self["fg"] = "red"
        else:
            self.set_default_style()

    def foc_in(self, *args):
        if self._error_state or self._placeholder_visible:
            self.set_default_style()
            if self._placeholder_visible and self.get() == self.placeholder:
                self.delete("0", "end")
                self._placeholder_visible = False
                return
        if self.get():
            self.after(10, lambda: self.select_range(0, tk.END))

    def foc_out(self, *args):
        if not self.get():
            self.put_placeholder()



# --- Tooltip Widget ---

class Tooltip:
    """Hover tooltip that appears near the cursor and hides on leave or click."""

    _OFFSET_X = 15
    _OFFSET_Y = 20

    def __init__(self, widget, text):
        self.widget = widget
        self._text = text
        self.tipwindow = None
        try:
            setattr(widget, "_tooltip_instance", self)
        except Exception:
            pass
        if hasattr(widget, "bind"):
            widget.bind("<Enter>", self.show, add="+")
            widget.bind("<Leave>", self.hide, add="+")
            widget.bind("<ButtonPress>", self.hide, add="+")
            widget.bind("<FocusOut>", self.hide, add="+")

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
        if self.tipwindow or not self._text:
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
                         wraplength=600, padx=5, pady=3)
        label.pack()

    def hide(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None



# --- DraggableListWidget ---

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
        self.on_drop_complete = None  # callback after drag-and-drop finishes
        self.drag_enabled = True

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

    @property
    def selected_index(self):
        return self._selected_index

    @selected_index.setter
    def selected_index(self, value):
        self._selected_index = value

    def set_items(self, items):
        self._items = items

    def set_selected_index(self, index, *, update_highlight=False, ensure_visible=False):
        if index is not None and 0 <= index < len(self._items):
            self._selected_index = index
        else:
            self._selected_index = None
        if update_highlight:
            self.update_selection_highlight()
        if ensure_visible and self._selected_index is not None:
            self.scroll_selected_into_view()

    def update_selection_highlight(self, *, highlight_bg="#a5c9ff", normal_bg=None):
        if not self._row_widgets:
            return
        if normal_bg is None:
            try:
                normal_bg = self.inner.cget("bg")
            except Exception:
                normal_bg = "SystemButtonFace"
        for index, row in enumerate(self._row_widgets):
            row_bg = highlight_bg if index == self._selected_index else normal_bg
            self._set_widget_background_recursive(row, row_bg)

    def scroll_selected_into_view(self):
        index = self._selected_index
        if index is None:
            return
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

    def bind_row_events(self, widget, index):
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
        self._row_widgets = row_widgets
        self.inner.update_idletasks()
        try:
            self.canvas.itemconfigure(
                self._window_id,
                width=max(0, self.canvas.winfo_width() - 4),
            )
            self.canvas.update_idletasks()
            self.inner.update_idletasks()
        except Exception:
            pass
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
        if not (0 <= index < len(self._items)):
            self._selected_index = None
            if self.on_reorder:
                self.on_reorder()
            return
        self._selected_index = index
        if self.on_reorder:
            self.on_reorder()
        self.scroll_selected_into_view()

    def _start_drag(self, event, index):
        self._drag_index = index
        self._drag_active = False
        self._drag_start_root_y = event.y_root
        self._selected_index = index

    def _on_drag_motion(self, event):
        if not getattr(self, "drag_enabled", True):
            return
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
                # Visual row swap — avoids full widget rebuild per drag step
                if self._row_widgets and max(self._drag_index, target) < len(self._row_widgets):
                    widget = self._row_widgets.pop(self._drag_index)
                    self._row_widgets.insert(target, widget)
                    lo = min(self._drag_index, target)
                    hi = max(self._drag_index, target)
                    for i in range(lo, hi + 1):
                        self._row_widgets[i].grid_configure(row=i)
                self._drag_index = target
                self._selected_index = target
                self.update_selection_highlight()

    def _on_drop(self, event):
        try:
            if self._drag_index is None:
                return "break"
            if not self._drag_active:
                if self.on_select:
                    self.on_select(self._drag_index)
                else:
                    self.select_line(self._drag_index)
            else:
                if self.on_reorder:
                    self.on_reorder()
                if self.on_drop_complete:
                    self.on_drop_complete()
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

    def _set_widget_background_recursive(self, widget, color):
        tooltip = getattr(widget, "_tooltip_instance", None)
        if tooltip is not None:
            try:
                tooltip.hide()
            except Exception:
                pass
        if not isinstance(widget, (tk.Button, ttk.Button, ttk.Scrollbar)):
            try:
                widget.config(bg=color)
            except Exception:
                pass
        try:
            children = widget.winfo_children()
        except Exception:
            return
        for child in children:
            self._set_widget_background_recursive(child, color)

