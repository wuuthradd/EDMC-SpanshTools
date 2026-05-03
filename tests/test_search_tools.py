"""Tests for search history persistence."""

import json
import os

from SpanshTools.search_tools import SearchToolsMixin


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    target = tmp_path / "history.json"
    monkeypatch.setattr(SearchToolsMixin, "_NEAREST_HISTORY_PATH", str(target))
    data = [
        {"name": "Sol", "coords": [0.0, 0.0, 0.0]},
        {"name": "Sagittarius A*", "coords": [25.22, -20.90, 25899.97]},
    ]
    SearchToolsMixin.save_nearest_history(data)
    assert SearchToolsMixin.load_nearest_history() == data


def test_save_caps_at_50_entries(tmp_path, monkeypatch):
    target = tmp_path / "history.json"
    monkeypatch.setattr(SearchToolsMixin, "_NEAREST_HISTORY_PATH", str(target))
    big = [{"name": f"System_{i}", "coords": [i, 0, 0]} for i in range(80)]
    SearchToolsMixin.save_nearest_history(big)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert len(loaded) == 50
    assert loaded[0]["name"] == "System_0"


def test_save_uses_atomic_replace(tmp_path, monkeypatch):
    target = tmp_path / "history.json"
    monkeypatch.setattr(SearchToolsMixin, "_NEAREST_HISTORY_PATH", str(target))
    replace_calls = []
    original_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda s, d: (replace_calls.append((s, d)), original_replace(s, d)))
    SearchToolsMixin.save_nearest_history([{"name": "Sol", "coords": [0, 0, 0]}])
    assert len(replace_calls) == 1
    assert replace_calls[0][0].endswith(".tmp")
