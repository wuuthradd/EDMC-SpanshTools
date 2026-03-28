"""Bundled FSD (Frame Shift Drive) spec loading and parsing helpers."""

import json
import logging
import os
import re
import threading
import tempfile

logger = logging.getLogger(__name__)

# Rating number in journal item names -> letter rating
RATING_MAP = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A"}
_REVERSE_RATING = {"E": 1, "D": 2, "C": 3, "B": 4, "A": 5}

# Guardian FSD Booster range boost by module class (LY)
GUARDIAN_FSD_BOOSTS = {1: 4.0, 2: 6.0, 3: 7.75, 4: 9.25, 5: 10.5}

_DATA_FILE_NAME = "fsd_specs.json"

# Single flat dict: normalized_symbol -> {class, rating, optimal_mass, ...}
_all_specs = {}
_specs_loaded = False
_specs_lock = threading.Lock()

# Extracts size and class from any FSD item name
_FSD_ITEM_RE = re.compile(r'int_hyperdrive_(?:\w+_)*?size(\d+)_class(\d+)')


def _data_file_path():
    """Return path to the bundled FSD specs JSON."""
    return os.path.join(os.path.dirname(__file__), _DATA_FILE_NAME)


def bundled_data_file_path():
    """Public accessor for the bundled FSD specs JSON path."""
    return _data_file_path()


def _normalize_symbol(symbol):
    """Normalize a coriolis symbol or journal item name to a consistent key."""
    if not isinstance(symbol, str):
        return ""
    normalized = symbol.lower().strip().strip('$').rstrip(';')
    if normalized.endswith('_name'):
        normalized = normalized[:-5]
    return normalized


def _coerce_spec_entry(entry):
    """Validate and normalize one FSD spec entry."""
    if not isinstance(entry, dict):
        return None

    try:
        fsd_class = int(entry["class"])
        rating = str(entry["rating"]).strip().upper()
        if rating not in _REVERSE_RATING:
            return None
        return {
            "class": fsd_class,
            "rating": rating,
            "optimal_mass": float(entry["optimal_mass"]),
            "max_fuel_per_jump": float(entry["max_fuel_per_jump"]),
            "fuel_power": float(entry["fuel_power"]),
            "fuel_multiplier": float(entry["fuel_multiplier"]),
            "supercharge_multiplier": int(entry.get("supercharge_multiplier", 4)),
        }
    except (KeyError, TypeError, ValueError):
        return None


def normalize_specs_map(spec_map):
    """Normalize a raw mapping of symbol -> FSD spec."""
    if not isinstance(spec_map, dict):
        return {}

    normalized_specs = {}
    for symbol, entry in spec_map.items():
        key = _normalize_symbol(symbol)
        coerced = _coerce_spec_entry(entry)
        if key and coerced:
            normalized_specs[key] = coerced
    return normalized_specs


def load_specs_from_bundled_data():
    """Load FSD specs from the bundled JSON file shipped with the plugin."""
    try:
        with open(_data_file_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        logger.warning("Bundled FSD data file is missing: %s", _data_file_path())
        return {}
    except Exception:
        logger.debug("Failed to load bundled FSD data", exc_info=True)
        return {}

    if isinstance(payload, dict) and "specs" in payload:
        payload = payload.get("specs")
    return normalize_specs_map(payload)


def save_specs_to_bundled_data(spec_map):
    """Atomically write the bundled FSD specs JSON."""
    payload = normalize_specs_map(spec_map)
    target_path = _data_file_path()
    target_dir = os.path.dirname(target_path)

    fd, temp_path = tempfile.mkstemp(
        prefix=".fsd_specs.",
        suffix=".json",
        dir=target_dir,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, target_path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            logger.debug("Failed to clean up temporary FSD specs file", exc_info=True)


def invalidate_specs_cache():
    """Invalidate the in-memory FSD spec cache so the next lookup reloads it."""
    global _all_specs, _specs_loaded
    with _specs_lock:
        _all_specs = {}
        _specs_loaded = False


def reload_specs_from_bundled_data():
    """Force a reload from the bundled JSON and report whether specs are available."""
    invalidate_specs_cache()
    initialize_specs()
    return bool(_all_specs)


def initialize_specs():
    """Load FSD specs once from the bundled plugin data."""
    global _all_specs, _specs_loaded

    if _specs_loaded:
        return

    with _specs_lock:
        if _specs_loaded:
            return

        specs = load_specs_from_bundled_data()
        if specs:
            _all_specs = specs
            logger.info("FSD specs loaded from bundled data: %s entries", len(specs))
            _specs_loaded = True
            return

        _all_specs = {}
        logger.warning("FSD specs unavailable; loadout-based FSD detection disabled")
        _specs_loaded = True


def _ensure_specs():
    """Compatibility wrapper for the one-time loader."""
    initialize_specs()


def get_fsd_specs(item_name):
    """Look up FSD specs by journal item name or coriolis symbol."""
    if not item_name:
        return None

    initialize_specs()
    key = _normalize_symbol(item_name)
    spec = _all_specs.get(key)
    return dict(spec) if spec else None


def parse_fsd_item_name(item_name):
    """Extract ``(class, rating)`` from a journal FSD item name."""
    item_lower = _normalize_symbol(item_name)
    if not item_lower:
        return None

    match = _FSD_ITEM_RE.search(item_lower)
    if not match:
        return None

    fsd_class = int(match.group(1))
    rating_num = int(match.group(2))
    rating = RATING_MAP.get(rating_num)
    if rating is None:
        return None
    return (fsd_class, rating)
