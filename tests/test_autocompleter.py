"""Tests for the AutoCompleter widget."""

import os
import sys
import threading
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from SpanshTools.AutoCompleter import AutoCompleter


def _build_autocompleter(monkeypatch):
    colors = {}

    monkeypatch.setattr(
        AutoCompleter, "__setitem__",
        lambda self, key, value: colors.__setitem__(key, value),
        raising=False,
    )
    monkeypatch.setattr(AutoCompleter, "delete", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(AutoCompleter, "insert", lambda self, *a, **kw: None, raising=False)

    widget = AutoCompleter.__new__(AutoCompleter)
    widget.placeholder_color = "grey"
    widget._placeholder_visible = False
    widget._error_state = False
    widget.var = MagicMock()
    widget._trace_id = None
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


def test_set_text_toggles_placeholder_state(monkeypatch):
    widget, colors = _build_autocompleter(monkeypatch)

    widget.set_text("Via System", True)
    assert widget._placeholder_visible is True
    assert colors["fg"] == "grey"

    widget.set_text("Sol", False)
    assert widget._placeholder_visible is False
    assert colors["fg"] == "black"


def test_display_results_decorates_selected_items(monkeypatch):
    widget, _ = _build_autocompleter(monkeypatch)
    widget.selected_items_provider = lambda: ["Sol"]

    results = widget._build_display_results(["Sol", "Achenar"])
    assert results[0].startswith("\u2713")
    assert results[1] == "Achenar"


def test_selection_uses_raw_value_not_decorated(monkeypatch):
    widget, _ = _build_autocompleter(monkeypatch)
    widget.lb_up = True
    widget.lb = MagicMock()
    widget.lb.curselection.return_value = (0,)
    widget._result_values = ["Sol"]
    widget.hide_list = MagicMock()
    widget.icursor = MagicMock()
    widget.get = lambda: "Sol"
    widget.on_select = MagicMock()

    widget.selection()

    widget.on_select.assert_called_once_with("Sol")
    assert widget.has_selected is True


def test_is_effectively_empty(monkeypatch):
    widget, _ = _build_autocompleter(monkeypatch)

    for text, expected in [("", True), ("   ", True), ("Source System", True), ("Sol", False)]:
        widget.get = lambda t=text: t
        assert widget.is_effectively_empty() is expected, f"Failed for {text!r}"


def test_debounce_skips_short_input(monkeypatch):
    widget, _ = _build_autocompleter(monkeypatch)
    widget.var.get.return_value = "So"
    widget.hide_list = MagicMock()
    widget.after = MagicMock()
    widget.after_cancel = MagicMock()
    widget._debounce_id = "pending"

    widget.changed()

    widget.after.assert_not_called()
    widget.hide_list.assert_called_once()
