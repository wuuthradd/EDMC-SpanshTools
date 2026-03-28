from tkinter import Entry, END, StringVar

from config import config


class PlaceHolder(Entry):
    def __init__(self, parent, placeholder, **kw):
        super().__init__(parent, **kw)
        self.var = self["textvariable"] = StringVar()
        self.placeholder = placeholder
        self.placeholder_color = "grey"
        self._placeholder_visible = False
        self._error_state = False

        self.bind("<FocusIn>", self.foc_in)
        self.bind("<FocusOut>", self.foc_out)
        self.bind("<<Paste>>", self._on_paste)

        self.put_placeholder()

    def put_placeholder(self):
        if self.get() != self.placeholder:
            self.set_text(self.placeholder, True)

    def set_text(self, text, placeholder_style=True):
        if placeholder_style:
            self._placeholder_visible = True
            self._error_state = False
            self['fg'] = self.placeholder_color
        else:
            self._placeholder_visible = False
            self.set_default_style()
        self.delete(0, END)
        self.insert(0, text)

    def set_default_style(self):
        theme = config.get_int('theme')
        self._error_state = False
        self['fg'] = config.get_str('dark_text') if theme else "black"

    def set_error_style(self, error=True):
        if error:
            self._placeholder_visible = False
            self._error_state = True
            self['fg'] = "red"
        else:
            self.set_default_style()

    def foc_in(self, *args):
        if self._error_state or self._placeholder_visible:
            self.set_default_style()
            if self._placeholder_visible and self.get() == self.placeholder:
                self.delete('0', 'end')
                self._placeholder_visible = False
                return
        # Select all real text so user can type over it
        if self.get():
            self.after(10, lambda: self.select_range(0, END))

    def _on_paste(self, event):
        try:
            clipboard = self.clipboard_get()
        except Exception:
            return "break"
        if self.selection_present():
            self.delete("sel.first", "sel.last")
        self.insert("insert", clipboard)
        return "break"

    def foc_out(self, *args):
        if not self.get():
            self.put_placeholder()
