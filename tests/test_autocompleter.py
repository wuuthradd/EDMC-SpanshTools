import os
import sys
import threading
from unittest.mock import MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from SpanshTools.AutoCompleter import AutoCompleter


def _build_autocompleter(monkeypatch):
    colors = {}

    monkeypatch.setattr(
        AutoCompleter,
        "__setitem__",
        lambda self, key, value: colors.__setitem__(key, value),
        raising=False,
    )
    monkeypatch.setattr(AutoCompleter, "delete", lambda self, *_args, **_kwargs: None, raising=False)
    monkeypatch.setattr(AutoCompleter, "insert", lambda self, *_args, **_kwargs: None, raising=False)

    widget = AutoCompleter.__new__(AutoCompleter)
    widget.placeholder_color = "grey"
    widget._placeholder_visible = False
    widget._error_state = False
    widget.var = MagicMock()
    widget.var.trace.return_value = "new-trace"
    widget.traceid = "old-trace"
    widget.set_default_style = lambda: colors.__setitem__("fg", "black")
    widget.selected_items_provider = None
    widget._destroyed = False
    widget._debounce_id = None
    widget._query_generation = 0
    widget._query_lock = threading.Lock()
    widget._query_event = MagicMock()
    widget._query_worker = None
    widget._pending_query = None
    widget._active_queries = 0
    widget._schedule_update = MagicMock()
    widget.lb_up = False
    widget.has_selected = False
    widget.placeholder = "Source System"
    return widget, colors


def test_set_text_tracks_placeholder_state(monkeypatch):
    widget, colors = _build_autocompleter(monkeypatch)

    widget.set_text("Via System", True)

    assert widget._placeholder_visible is True
    assert widget._error_state is False
    assert colors["fg"] == "grey"


def test_set_text_clears_placeholder_state_for_real_text(monkeypatch):
    widget, colors = _build_autocompleter(monkeypatch)
    widget._placeholder_visible = True
    widget._error_state = True

    widget.set_text("Sol", False)

    assert widget._placeholder_visible is False
    assert colors["fg"] == "black"


def test_build_display_results_marks_selected_items(monkeypatch):
    widget, _colors = _build_autocompleter(monkeypatch)
    widget.selected_items_provider = lambda: ["Sol"]

    results = widget._build_display_results(["Sol", "Achenar"])

    assert results[0] == "✓ Sol"
    assert results[1] == "Achenar"


def test_selection_uses_actual_result_value_not_decorated_display(monkeypatch):
    widget, _colors = _build_autocompleter(monkeypatch)
    widget.lb_up = True
    widget.lb = MagicMock()
    widget.lb.curselection.return_value = (0,)
    widget._result_values = ["Sol"]
    widget.hide_list = MagicMock()
    widget.icursor = MagicMock()
    widget.get = lambda: "Sol"
    widget.on_select = MagicMock()

    widget.selection()

    widget.var.set.assert_called_once_with("Sol")
    widget.on_select.assert_called_once_with("Sol")


def test_show_list_preserves_entry_grid_column(monkeypatch):
    widget, _colors = _build_autocompleter(monkeypatch)
    widget.parent = MagicMock()
    widget.parent.focus_get.return_value = widget
    widget.lb = MagicMock()
    widget.grid_info = lambda: {
        "row": "4",
        "column": "1",
        "columnspan": "3",
        "sticky": "ew",
        "padx": "5",
        "pady": "2",
    }

    widget.show_list(6)

    widget.lb.grid.assert_called_once_with(
        row=5,
        column="1",
        columnspan="3",
        sticky="ew",
        padx="5",
        pady="2",
    )


def test_changed_does_not_schedule_query_for_short_input(monkeypatch):
    widget, _colors = _build_autocompleter(monkeypatch)
    widget.var.get.return_value = "So"
    widget.hide_list = MagicMock()
    widget.after = MagicMock()
    widget.after_cancel = MagicMock()
    widget._debounce_id = "pending"

    widget.changed()

    widget.after_cancel.assert_called_once_with("pending")
    widget.after.assert_not_called()
    widget.hide_list.assert_called_once()


def test_fire_query_reuses_shared_worker_and_overwrites_pending_query(monkeypatch):
    widget, _colors = _build_autocompleter(monkeypatch)
    created_workers = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon
            created_workers.append(self)

        def is_alive(self):
            return True

        def start(self):
            return None

    monkeypatch.setattr("SpanshTools.AutoCompleter.threading.Thread", _FakeThread)

    widget._fire_query("Sol")
    widget._fire_query("Achenar")

    assert len(created_workers) == 1
    assert widget._pending_query == ("Achenar", widget._query_generation)
    widget._query_event.set.assert_called()
