#!/usr/bin/env python3
"""Fetch current Coriolis FSD data and merge it into the bundled specs file.

Default behavior:
- fetch latest Coriolis FSD list
- add only missing FSD symbols to ``SpanshTools/data/fsd_specs.json``
- report existing symbols whose values differ

Optional behavior:
- ``--sync-existing`` also updates existing changed entries
- ``--check`` reports changes without writing
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys
import tempfile

import requests


CORIOLIS_FSD_URL = (
    "https://raw.githubusercontent.com/EDCD/coriolis-data/master/"
    "modules/standard/frame_shift_drive.json"
)


def _load_fsd_data_module():
    import types

    parent = pathlib.Path(__file__).resolve().parent
    pkg_dir = str(parent / "SpanshTools")

    # Stub EDMC host modules when running standalone (harmless if already mocked)
    for name in ("config", "monitor"):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            if name == "config":
                stub.appname = "EDMarketConnector"
                stub.config = types.SimpleNamespace(
                    get_str=lambda *a, **kw: "",
                    get_int=lambda *a, **kw: 0,
                    set=lambda *a, **kw: None,
                )
            elif name == "monitor":
                stub.monitor = types.SimpleNamespace(cmdr=None, state={})
            sys.modules[name] = stub

    # Register a minimal package so relative imports inside ship_moduling resolve
    if "SpanshTools" not in sys.modules:
        pkg = types.ModuleType("SpanshTools")
        pkg.__path__ = [pkg_dir]
        pkg.__package__ = "SpanshTools"
        sys.modules["SpanshTools"] = pkg

    module_path = parent / "SpanshTools" / "ship_moduling.py"
    spec = importlib.util.spec_from_file_location(
        "SpanshTools.ship_moduling", str(module_path),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "SpanshTools"
    sys.modules["SpanshTools.ship_moduling"] = module
    spec.loader.exec_module(module)
    return module


fsd_data = _load_fsd_data_module()


def _atomic_write_text(path, text):
    fd, temp_path = tempfile.mkstemp(
        prefix=".fsd_specs.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp_path, path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


def _infer_supercharge_multiplier(symbol_lower):
    if "mkii" in symbol_lower or "mkiii" in symbol_lower:
        return 6
    return 4


def _coerce_payload_version(value, default=1):
    try:
        version = int(value)
        if version >= 1:
            return version
    except (TypeError, ValueError):
        pass
    return default


def _load_current_payload():
    path = pathlib.Path(fsd_data.bundled_data_file_path())
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "specs" in payload:
        return {
            "version": _coerce_payload_version(payload.get("version"), 1),
            "specs": fsd_data.normalize_specs_map(payload.get("specs")),
        }
    return {
        "version": 1,
        "specs": fsd_data.normalize_specs_map(payload),
    }


def _parse_coriolis_list(fsd_list):
    specs = {}
    if not isinstance(fsd_list, list):
        return specs

    for entry in fsd_list:
        if not isinstance(entry, dict):
            continue
        if entry.get("preEngineered"):
            continue

        symbol = entry.get("symbol", "")
        fsd_class = entry.get("class")
        rating = entry.get("rating")
        if not symbol or fsd_class in (None, "") or rating in (None, ""):
            continue

        key = symbol.lower().strip().strip("$").rstrip(";")
        if key.endswith("_name"):
            key = key[:-5]
        if key in specs:
            continue

        try:
            candidate = {
                "class": int(fsd_class),
                "rating": str(rating).strip().upper(),
                "optimal_mass": float(entry.get("optmass", 0)),
                "max_fuel_per_jump": float(entry.get("maxfuel", 0)),
                "fuel_power": float(entry.get("fuelpower", 0)),
                "fuel_multiplier": float(entry.get("fuelmul", 0)),
                "supercharge_multiplier": _infer_supercharge_multiplier(key),
            }
            normalized = fsd_data.normalize_specs_map({key: candidate})
            if key in normalized:
                specs[key] = normalized[key]
        except (TypeError, ValueError):
            continue

    return specs


def _load_specs_from_network():
    try:
        response = requests.get(CORIOLIS_FSD_URL, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}

    fsd_list = payload.get("fsd", []) if isinstance(payload, dict) else []
    return _parse_coriolis_list(fsd_list)


def _changed_keys(current_specs, network_specs):
    changed = []
    for key, network_entry in network_specs.items():
        current_entry = current_specs.get(key)
        if current_entry is not None and current_entry != network_entry:
            changed.append(key)
    return sorted(changed)


def _missing_keys(current_specs, network_specs):
    return sorted(key for key in network_specs if key not in current_specs)


def _build_updated_specs(current_specs, network_specs, *, sync_existing):
    updated = dict(current_specs)

    for key in _missing_keys(current_specs, network_specs):
        updated[key] = network_specs[key]

    if sync_existing:
        for key in _changed_keys(current_specs, network_specs):
            updated[key] = network_specs[key]

    return updated


def _print_summary(missing, changed, wrote_path=None, sync_existing=False):
    print(f"Missing bundled FSD symbols: {len(missing)}")
    if missing:
        for key in missing:
            print(f"  + {key}")

    print(f"Changed existing FSD symbols: {len(changed)}")
    if changed:
        prefix = "  *"
        note = "updated" if sync_existing else "not changed"
        for key in changed:
            print(f"{prefix} {key} ({note})")

    if wrote_path:
        print(f"Wrote updated bundled specs to: {wrote_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report missing/changed FSD entries without writing the bundled JSON.",
    )
    parser.add_argument(
        "--sync-existing",
        action="store_true",
        help="Overwrite bundled entries that differ from the current Coriolis data.",
    )
    args = parser.parse_args(argv)

    current_payload = _load_current_payload()
    current_specs = current_payload["specs"]
    current_version = current_payload["version"]
    network_specs = _load_specs_from_network()

    if not network_specs:
        print("Failed to fetch current Coriolis FSD data.", file=sys.stderr)
        return 1

    missing = _missing_keys(current_specs, network_specs)
    changed = _changed_keys(current_specs, network_specs)

    wrote_path = None
    if not args.check and (missing or (args.sync_existing and changed)):
        updated_specs = _build_updated_specs(
            current_specs,
            network_specs,
            sync_existing=args.sync_existing,
        )
        path = pathlib.Path(fsd_data.bundled_data_file_path())
        _atomic_write_text(
            path,
            json.dumps(
                {
                    "version": current_version + 1,
                    "specs": updated_specs,
                },
                indent=2,
                sort_keys=True,
            ) + "\n",
        )
        wrote_path = fsd_data.bundled_data_file_path()

    _print_summary(missing, changed, wrote_path=wrote_path, sync_existing=args.sync_existing)

    if args.check and (missing or changed):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
