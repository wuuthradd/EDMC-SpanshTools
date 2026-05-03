import json
import os
import webbrowser
from time import sleep
from urllib.parse import quote_plus

import requests
from requests import RequestException

from .constants import _SpanshPollError, _SpanshPollTimeout, logger

DEFAULT_TIMEOUT = 10


def _load_plugin_version():
    try:
        _vpath = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "version.json"
        )
        with open(_vpath, "r", encoding="utf-8") as f:
            return json.load(f).get("version", "")
    except Exception:
        return ""


_PLUGIN_VERSION = _load_plugin_version()
USER_AGENT = (
    f"EDMC_SpanshTools/{_PLUGIN_VERSION}" if _PLUGIN_VERSION else "EDMC_SpanshTools"
)


class WebOpenError(Exception):
    """Raised when a system cannot be opened in EDSM/Spansh (not found or network error)."""


class WebUtils:
    """Static HTTP helpers for Spansh and EDSM APIs, with polling, retries, and coordinate lookups."""

    @staticmethod
    def _headers():
        return {"User-Agent": USER_AGENT}

    @staticmethod
    def spansh_request(method, endpoint, **kwargs):
        url = (
            f"https://spansh.co.uk{endpoint}" if endpoint.startswith("/") else endpoint
        )
        if "timeout" not in kwargs:
            kwargs["timeout"] = DEFAULT_TIMEOUT
        if "headers" not in kwargs:
            kwargs["headers"] = WebUtils._headers()

        return requests.request(method, url, **kwargs)

    @staticmethod
    def spansh_get(endpoint, params=None, timeout=DEFAULT_TIMEOUT):
        try:
            resp = WebUtils.spansh_request(
                "GET", endpoint, params=params, timeout=timeout
            )
            resp.raise_for_status()
            return resp.json()
        except RequestException as e:
            logger.error(f"Spansh GET failed: {endpoint} - {e}")
            raise

    @staticmethod
    def edsm_get(endpoint, params=None, timeout=DEFAULT_TIMEOUT):
        url = (
            f"https://www.edsm.net{endpoint}" if endpoint.startswith("/") else endpoint
        )
        try:
            resp = requests.get(
                url, params=params, headers=WebUtils._headers(), timeout=timeout
            )
            resp.raise_for_status()
            data = resp.json()
            # EDSM returns [] if system not found in some endpoints
            return data if data is not None else {}
        except RequestException as e:
            logger.error(f"EDSM GET failed: {url} - {e}")
            raise

    @staticmethod
    def get_system_coordinates(system_name):
        """Returns (name, coords), trying EDSM then Spansh."""
        try:
            data = WebUtils.edsm_get(
                "/api-v1/system",
                params={"systemName": system_name, "showCoordinates": 1},
            )
            if data and isinstance(data, dict) and "coords" in data:
                c = data["coords"]
                return data.get("name", system_name), [
                    c.get("x", 0),
                    c.get("y", 0),
                    c.get("z", 0),
                ]
        except Exception:
            logger.debug("EDSM coordinate lookup failed", exc_info=True)

        try:
            data = WebUtils.spansh_get("/api/search/systems", params={"q": system_name})
            results = data.get("results", [])
            exact = next(
                (
                    r
                    for r in results
                    if (r.get("name") or "").strip().lower() == system_name.lower()
                ),
                None,
            )
            if exact:
                return exact.get("name", system_name), [
                    exact.get("x", 0),
                    exact.get("y", 0),
                    exact.get("z", 0),
                ]
        except Exception:
            logger.debug("Spansh coordinate fallback failed", exc_info=True)

        return None, None

    @staticmethod
    def get_nearest_system(coords, timeout=DEFAULT_TIMEOUT):
        """Returns (name, coords, distance). Raises RequestException on network failure."""
        x, y, z = coords
        data = WebUtils.spansh_get(
            "/api/nearest", params={"x": x, "y": y, "z": z}, timeout=timeout
        )
        sys = data.get("system", {}) or {}
        if sys:
            dist = data.get("distance", sys.get("distance", None))
            return (
                sys.get("name", ""),
                [sys.get("x", 0), sys.get("y", 0), sys.get("z", 0)],
                dist,
            )
        return "", [0, 0, 0], None

    @staticmethod
    def github_get(endpoint, timeout=DEFAULT_TIMEOUT):
        """Query GitHub API. endpoint should start with /."""
        url = (
            f"https://api.github.com{endpoint}"
            if endpoint.startswith("/")
            else endpoint
        )
        try:
            resp = requests.get(url, headers=WebUtils._headers(), timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except RequestException as e:
            logger.error(f"GitHub GET failed: {url} - {e}")
            raise

    @staticmethod
    def get_raw(url, timeout=30):
        """Fetch raw content (e.g. for binary downloads or text files)."""
        try:
            resp = requests.get(url, headers=WebUtils._headers(), timeout=timeout)
            resp.raise_for_status()
            return resp
        except RequestException as e:
            logger.error(f"Raw GET failed: {url} - {e}")
            raise

    @staticmethod
    def parse_json(response, default=None):
        try:
            return response.json()
        except (ValueError, AttributeError):
            return {} if default is None else default

    @staticmethod
    def get_error_message(response, default="Unknown error"):
        payload = WebUtils.parse_json(response, default={})
        if isinstance(payload, dict):
            error_text = payload.get("error")
            if error_text:
                return error_text
        text = getattr(response, "text", "") or ""
        return text or default

    @staticmethod
    def has_spansh_direct_result(payload, direct_result_keys=()):
        if isinstance(payload, list):
            return True
        if not isinstance(payload, dict):
            return False
        if any(key in payload for key in direct_result_keys):
            return True
        nested = payload.get("result")
        return isinstance(nested, dict) and any(
            key in nested for key in direct_result_keys
        )

    @staticmethod
    def poll_spansh_job(
        job,
        *,
        poll_interval=2,
        max_iterations=120,
        results_base="https://spansh.co.uk/api/results",
        cancel_checker=None,
    ):
        """Poll a Spansh job until completed, with retry on transient network failures."""
        consecutive_failures = 0
        max_consecutive = 5
        for attempt in range(max_iterations):
            if cancel_checker and cancel_checker():
                return None
            try:
                result = WebUtils.spansh_request(
                    "GET", f"{results_base}/{job}", timeout=10
                )
                consecutive_failures = 0
            except RequestException as exc:
                consecutive_failures += 1
                logger.debug(f"Spansh poll attempt {attempt + 1} failed: {exc}")
                if consecutive_failures >= max_consecutive:
                    raise RequestException(
                        f"Network error while polling Spansh after {consecutive_failures} consecutive failures: {exc}"
                    ) from exc
                sleep(poll_interval)
                continue
            if cancel_checker and cancel_checker():
                return None
            if result is not None and result.status_code == 200:
                data = result.json()
                if data.get("status") == "ok" or data.get("state") == "completed":
                    return data
                if "error" in data:
                    raise _SpanshPollError(data["error"])
            elif result is not None and result.status_code != 202:
                raise _SpanshPollError(
                    WebUtils.get_error_message(
                        result, f"API error: {result.status_code}"
                    ),
                    status_code=result.status_code,
                )
            if attempt < max_iterations - 1:
                sleep(poll_interval)
        raise _SpanshPollTimeout("Route computation timed out. Please try again.")

    @staticmethod
    def submit_spansh_job_request(
        api_url,
        *,
        params=None,
        data=None,
        timeout=15,
        results_base="https://spansh.co.uk/api/results",
        accept_direct_result=False,
        direct_result_keys=(),
        poll_interval=2,
        max_iterations=120,
        cancel_checker=None,
    ):
        """Submit a route computation request and poll until the result is ready."""
        response = WebUtils.spansh_request(
            "POST", api_url, params=params, data=data, timeout=timeout
        )
        if response.status_code == 400:
            raise _SpanshPollError(
                WebUtils.get_error_message(response, "Invalid request"),
                status_code=400,
            )
        if response.status_code not in (200, 202):
            raise _SpanshPollError(
                WebUtils.get_error_message(
                    response, f"API error: {response.status_code}"
                ),
                status_code=response.status_code,
            )
        result = WebUtils.parse_json(response, default={})
        if accept_direct_result and WebUtils.has_spansh_direct_result(
            result, direct_result_keys
        ):
            return result
        job = result.get("job") if isinstance(result, dict) else None
        if not job:
            raise _SpanshPollError("No job ID returned")
        return WebUtils.poll_spansh_job(
            job,
            poll_interval=poll_interval,
            max_iterations=max_iterations,
            results_base=results_base,
            cancel_checker=cancel_checker,
        )

    @staticmethod
    def fetch_system_ids(system_name, cache=None, id64=None):
        """Returns (edsm_id, id64). Skips Spansh fallback when id64 is provided."""
        if cache is not None and system_name in cache:
            return cache[system_name]

        edsm_id = None
        try:
            params = {"showId": 1, "systemName": system_name}
            if id64:
                params["systemId64"] = id64
            data = WebUtils.edsm_get("/api-v1/system", params=params, timeout=8)
            if isinstance(data, dict):
                edsm_id = data.get("id")
                if not id64:
                    id64 = data.get("id64")
        except Exception:
            logger.debug("EDSM system ID lookup failed", exc_info=True)

        if not id64:
            try:
                data = WebUtils.spansh_get(
                    "/api/search/systems", params={"q": system_name}, timeout=8
                )
                results = data.get("results", [])
                exact = next(
                    (
                        s
                        for s in results
                        if s.get("name", "").lower() == system_name.lower()
                    ),
                    None,
                )
                if exact:
                    id64 = exact.get("id64")
            except Exception:
                logger.debug("Spansh system ID fallback failed", exc_info=True)

        result = (edsm_id, id64)
        if cache is not None and (edsm_id is not None or id64 is not None):
            cache[system_name] = result
        return result

    @staticmethod
    def fetch_edsm_bodies(system_name, system_id=None, cache=None):
        if cache is not None and system_name in cache:
            return cache[system_name]

        params = {"systemName": system_name}
        if system_id:
            params["systemId"] = system_id
        resp = WebUtils.edsm_get("/api-system-v1/bodies", params=params, timeout=8)
        bodies = resp.get("bodies") if isinstance(resp, dict) else []
        bodies = bodies or []
        if cache is not None:
            cache[system_name] = bodies
        return bodies

    @staticmethod
    def _provider_error(provider, exc=None):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status is None or status >= 500 or status == 429:
            return WebOpenError(f"{provider} is unavailable")
        return WebOpenError(f"{provider} error")

    @staticmethod
    def open_edsm(system_name, body_name=None, sid64=None):
        eid, _ = WebUtils.fetch_system_ids(system_name, id64=sid64)
        if not eid:
            missing_name = body_name or system_name
            raise WebOpenError(f"{missing_name}\nNot found in EDSM")

        if body_name is not None:
            try:
                bodies = WebUtils.fetch_edsm_bodies(system_name, eid)
            except RequestException as exc:
                raise WebUtils._provider_error("EDSM", exc) from exc
            b_entry = next(
                (b for b in bodies if b.get("name", "").lower() == body_name.lower()),
                None,
            )
            if not b_entry:
                raise WebOpenError(f"{body_name}\nNot found in EDSM")
            url = f"https://www.edsm.net/en/system/bodies/id/{eid}/name/{quote_plus(system_name)}/details/idB/{b_entry['id']}/nameB/{quote_plus(body_name)}"
        else:
            url = f"https://www.edsm.net/en/system/id/{eid}/name/{quote_plus(system_name)}"

        webbrowser.open(url)

    @staticmethod
    def open_spansh(system_name, body_name=None, bid64=None, sid64=None):
        if body_name is not None:
            if bid64:
                webbrowser.open(f"https://spansh.co.uk/body/{bid64}")
                return
            eid = None
            if not sid64:
                eid, sid64 = WebUtils.fetch_system_ids(system_name)
            else:
                eid, _ = WebUtils.fetch_system_ids(system_name, id64=sid64)
            try:
                bodies = WebUtils.fetch_edsm_bodies(system_name, eid) if eid else []
            except RequestException:
                bodies = []
            entry = next(
                (b for b in bodies if b.get("name", "").lower() == body_name.lower()),
                None,
            )
            if entry:
                bid64 = entry.get("id64")

            if not bid64 and sid64:
                try:
                    data = WebUtils.spansh_get(f"/api/system/{sid64}", timeout=8)
                except RequestException as exc:
                    raise WebUtils._provider_error("Spansh", exc) from exc
                sys_data = data.get("system", data) if isinstance(data, dict) else {}
                if isinstance(sys_data, dict):
                    sys_bodies = sys_data.get("bodies", [])
                    entry = next(
                        (
                            b
                            for b in sys_bodies
                            if b.get("name", "").lower() == body_name.lower()
                        ),
                        None,
                    )
                    if entry:
                        bid64 = entry.get("id64")
            if not bid64:
                raise WebOpenError(f"{body_name}\nNot found in Spansh")
            webbrowser.open(f"https://spansh.co.uk/body/{bid64}")
            return

        # System open — use sid64 directly if available
        if sid64:
            webbrowser.open(f"https://spansh.co.uk/system/{sid64}")
            return
        # Fallback: fetch ids from API
        _, sid64 = WebUtils.fetch_system_ids(system_name)
        if sid64:
            webbrowser.open(f"https://spansh.co.uk/system/{sid64}")
            return
        raise WebOpenError(f"{(body_name or system_name)}\nNot found in Spansh")
