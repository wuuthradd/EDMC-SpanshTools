"""Tests for SpanshTools.web_utils -- regression-critical behaviour only."""

from unittest.mock import MagicMock

import pytest
from requests import RequestException

import SpanshTools.web_utils as web_utils_mod
from SpanshTools.web_utils import WebUtils, WebOpenError
from SpanshTools.constants import _SpanshPollError, _SpanshPollTimeout


# ---------------------------------------------------------------------------
# poll_spansh_job
# ---------------------------------------------------------------------------

class TestPollSpanshJob:
    def test_polls_before_first_sleep_and_completes_after_pending(self, monkeypatch):
        """First action is a request (not sleep); pending 202 then completed 200."""
        events = []
        pending = MagicMock(status_code=202)
        pending.json.return_value = {"state": "queued"}
        completed = MagicMock(status_code=200)
        completed.json.return_value = {"status": "ok", "result": {"system_jumps": []}}
        responses = [pending, completed]

        monkeypatch.setattr(
            WebUtils, "spansh_request",
            lambda *a, **kw: (events.append("request"), responses.pop(0))[-1],
        )
        monkeypatch.setattr(web_utils_mod, "sleep", lambda s: events.append(("sleep", s)))

        data = WebUtils.poll_spansh_job("j1", poll_interval=5, max_iterations=3)
        assert data["status"] == "ok"
        assert events == ["request", ("sleep", 5), "request"]

    def test_consecutive_network_failures_raises(self, monkeypatch):
        """Exceeding max consecutive network errors raises RequestException."""
        monkeypatch.setattr(
            WebUtils, "spansh_request",
            MagicMock(side_effect=RequestException("down")),
        )
        monkeypatch.setattr(web_utils_mod, "sleep", lambda _: None)

        with pytest.raises(RequestException, match="consecutive failures"):
            WebUtils.poll_spansh_job("j1", max_iterations=10, poll_interval=0)

    def test_timeout_raises(self, monkeypatch):
        """Exceeding max_iterations raises _SpanshPollTimeout."""
        resp = MagicMock(status_code=202)
        monkeypatch.setattr(WebUtils, "spansh_request", lambda *a, **kw: resp)
        monkeypatch.setattr(web_utils_mod, "sleep", lambda _: None)

        with pytest.raises(_SpanshPollTimeout, match="timed out"):
            WebUtils.poll_spansh_job("j1", max_iterations=2, poll_interval=0)


# ---------------------------------------------------------------------------
# submit_spansh_job_request
# ---------------------------------------------------------------------------

class TestSubmitSpanshJobRequest:
    def test_accepts_direct_result(self, monkeypatch):
        """Direct list payload returned immediately without polling."""
        resp = MagicMock(status_code=200)
        resp.json.return_value = [{"system": "Sol"}]
        monkeypatch.setattr(WebUtils, "spansh_request", lambda *a, **kw: resp)

        result = WebUtils.submit_spansh_job_request(
            "/api/route", accept_direct_result=True,
        )
        assert result == [{"system": "Sol"}]

    def test_raises_on_400(self, monkeypatch):
        """400 response surfaces the error message in _SpanshPollError."""
        resp = MagicMock(status_code=400)
        resp.json.return_value = {"error": "Bad params"}
        monkeypatch.setattr(WebUtils, "spansh_request", lambda *a, **kw: resp)

        with pytest.raises(_SpanshPollError, match="Bad params"):
            WebUtils.submit_spansh_job_request("/api/route")


# ---------------------------------------------------------------------------
# get_system_coordinates
# ---------------------------------------------------------------------------

class TestGetSystemCoordinates:
    def test_edsm_success(self, monkeypatch):
        monkeypatch.setattr(WebUtils, "edsm_get", lambda *a, **kw: {
            "name": "Sol", "coords": {"x": 0.0, "y": 0.0, "z": 0.0},
        })
        name, coords = WebUtils.get_system_coordinates("Sol")
        assert name == "Sol"
        assert coords == [0.0, 0.0, 0.0]

    def test_fallback_to_spansh_on_edsm_failure(self, monkeypatch):
        monkeypatch.setattr(WebUtils, "edsm_get", MagicMock(side_effect=Exception("down")))
        monkeypatch.setattr(WebUtils, "spansh_get", lambda *a, **kw: {
            "results": [{"name": "Sol", "x": 0.0, "y": 0.0, "z": 0.0}],
        })
        name, coords = WebUtils.get_system_coordinates("Sol")
        assert name == "Sol"
        assert coords == [0.0, 0.0, 0.0]

    def test_both_providers_fail_returns_none(self, monkeypatch):
        monkeypatch.setattr(WebUtils, "edsm_get", MagicMock(side_effect=Exception("down")))
        monkeypatch.setattr(WebUtils, "spansh_get", MagicMock(side_effect=Exception("also down")))
        name, coords = WebUtils.get_system_coordinates("Nonexistent System")
        assert name is None
        assert coords is None


# ---------------------------------------------------------------------------
# open_edsm / open_spansh
# ---------------------------------------------------------------------------

class TestOpenEdsm:
    def test_system_not_found_raises(self, monkeypatch):
        monkeypatch.setattr(WebUtils, "fetch_system_ids", lambda *a, **kw: (None, None))
        with pytest.raises(WebOpenError, match="Not found"):
            WebUtils.open_edsm("UnknownSystem")


class TestOpenSpansh:
    def test_uses_sid64_directly(self, monkeypatch):
        opened = []
        monkeypatch.setattr(web_utils_mod.webbrowser, "open", lambda url: opened.append(url))
        WebUtils.open_spansh("Sol", sid64=10477373803)
        assert opened == ["https://spansh.co.uk/system/10477373803"]


# ---------------------------------------------------------------------------
# fetch_system_ids
# ---------------------------------------------------------------------------

class TestFetchSystemIds:
    def test_cache_hit_returns_cached_value(self):
        cache = {"Sol": (12345, 10477373803)}
        assert WebUtils.fetch_system_ids("Sol", cache=cache) == (12345, 10477373803)


# ---------------------------------------------------------------------------
# has_spansh_direct_result
# ---------------------------------------------------------------------------

class TestHasSpanshDirectResult:
    @pytest.mark.parametrize("payload,keys,expected", [
        ([{"name": "Sol"}], (), True),                                    # list
        ({"system_jumps": []}, ("system_jumps",), True),                  # dict key
        ({"result": {"system_jumps": []}}, ("system_jumps",), True),      # nested
        ({"other_key": 1}, ("system_jumps",), False),                     # no match
    ], ids=["list", "dict-key", "nested", "no-match"])
    def test_detection(self, payload, keys, expected):
        assert WebUtils.has_spansh_direct_result(payload, direct_result_keys=keys) is expected