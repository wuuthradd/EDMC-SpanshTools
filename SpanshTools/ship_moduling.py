"""Ship moduling — Bundled FSD specs and ship/loadout processing mixin."""
import json
import os
import re
import threading
import tempfile
import copy
from config import config
from monitor import monitor
from .constants import SLEF_CLEAN_KEYS, SHIP_LIST_MAX_OWNED, SHIP_LIST_MAX_IMPORTED, logger

# --- FSD Data & Helpers ---

_REVERSE_RATING = {"E": 1, "D": 2, "C": 3, "B": 4, "A": 5}

# Guardian FSD Booster range boost by module class (LY)
GUARDIAN_FSD_BOOSTS = {1: 4.0, 2: 6.0, 3: 7.75, 4: 9.25, 5: 10.5}

_DATA_FILE_NAME = os.path.join("data", "fsd_specs.json")

# Single flat dict: normalized_symbol -> {class, rating, optimal_mass, ...}
_all_specs = {}
_specs_loaded = False
_specs_lock = threading.Lock()

def _data_file_path():
    return os.path.join(os.path.dirname(__file__), _DATA_FILE_NAME)


def bundled_data_file_path():
    return _data_file_path()


def _normalize_symbol(symbol):
    if not isinstance(symbol, str):
        return ""
    normalized = symbol.lower().strip().strip('$').rstrip(';').strip()
    if normalized.endswith('_name'):
        normalized = normalized[:-5]
    return normalized


def _coerce_spec_entry(entry):
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


def invalidate_specs_cache():
    global _all_specs, _specs_loaded
    with _specs_lock:
        _all_specs = {}
        _specs_loaded = False


def reload_specs_from_bundled_data():
    invalidate_specs_cache()
    initialize_specs()
    return bool(_all_specs)


def initialize_specs():
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


def get_fsd_specs(item_name):
    if not item_name:
        return None

    initialize_specs()
    key = _normalize_symbol(item_name)
    spec = _all_specs.get(key)
    return dict(spec) if spec else None



# --- Ship Moduling Mixin (Consolidated logic) ---

class ShipModulingMixin:
    """Mixin for ship and module related processing, builds, and calculations."""

    # --- Utilities & Ship Type Names ---

    def _safe_float(self, value, default=0.0):
        try:
            if value is None:
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    def _load_ship_type_names(self):
        try:
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            path = os.path.join(plugin_dir, "SpanshTools", "data", "ship_type_names.json")
            if not os.path.exists(path):
                # Fallback to local data dir if relative path fails
                path = os.path.join(os.path.dirname(__file__), "data", "ship_type_names.json")

            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return {k.lower(): v for k, v in data.items()}
        except Exception:
            logger.debug("Failed to load ship type names", exc_info=True)
        return {}

    def _resolve_ship_type_display(self, ship_type_raw):
        names = getattr(self, "_ship_type_names", None)
        if names is None:
            names = self._ship_type_names = self._load_ship_type_names()
        raw = str(ship_type_raw or "").strip()
        return names.get(raw.lower(), raw)

    # --- Ship List Management ---

    def _load_ship_list(self):
        try:
            if not hasattr(self, "ship_list_path") or not self.ship_list_path:
                return []
            if os.path.exists(self.ship_list_path):
                with open(self.ship_list_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    entries = [e for e in data if isinstance(e, dict) and not (e.get("is_owned") and not str(e.get("commander") or "").strip())]
                    for i, e in enumerate(entries):
                        if not isinstance(e.get("sort_order"), (int, float)):
                            e["sort_order"] = i
                    return entries
        except (FileNotFoundError, ValueError, OSError):
            pass
        return []

    def _save_ship_list(self):
        try:
            if hasattr(self, "ship_list_path") and self.ship_list_path:
                if hasattr(self, "_write_json_atomic"):
                    self._write_json_atomic(self.ship_list_path, self._ship_list, prefix=".ship_list.")
                else:
                    target_dir = os.path.dirname(self.ship_list_path)
                    fd, temp_path = tempfile.mkstemp(prefix=".ship_list.", suffix=".json", dir=target_dir, text=True)
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as handle:
                            json.dump(self._ship_list, handle)
                        os.replace(temp_path, self.ship_list_path)
                    except Exception:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        raise
        except Exception:
            logger.debug("Failed to save ship list", exc_info=True)

    def _ship_list_identity_key(self, entry):
        if not isinstance(entry, dict):
            return ""
        return self._ship_identity_key_str(
            entry.get("loadout", entry),
            commander=entry.get("commander"),
            fallback_name=entry.get("name"),
        )

    def _ship_list_display_name(self, entry):
        name = str(entry.get("name") or "").strip()
        ident = str(entry.get("ident") or "").strip()
        ship_type_raw = str(entry.get("ship_type") or "").strip()

        ship_disp = self._resolve_ship_type_display(ship_type_raw) if ship_type_raw else ""
        label = name or ship_disp or "Unknown Ship"

        if ship_disp and name and ship_disp.lower() != name.lower():
            label = f"{label} ({ship_disp})"

        if ident:
            s_id = entry.get("loadout", {}).get("ShipID") if entry.get("is_owned") else None
            if s_id is not None:
                label = f"{label} [{ident} - ID: {s_id}]"
            else:
                label = f"{label} [{ident}]"
        return label

    def _next_ship_sort_order(self, is_owned, commander):
        max_order = -1
        for e in self._ship_list:
            if e.get("is_owned") != is_owned:
                continue
            if is_owned and e.get("commander") != commander:
                continue
            order = e.get("sort_order")
            if isinstance(order, (int, float)) and order > max_order:
                max_order = int(order)
        return max_order + 1

    def _ship_list_add(self, loadout, is_owned=False, commander=None):
        """Returns False if the category is at capacity."""
        if not isinstance(loadout, dict):
            return False
        entry = self._ship_list_entry(loadout, is_owned=is_owned, commander=commander)

        key = self._ship_list_identity_key(entry)
        for i, existing in enumerate(self._ship_list):
            if self._ship_list_identity_key(existing) == key:
                entry["sort_order"] = existing.get("sort_order", i)
                self._ship_list[i] = entry
                self._save_ship_list()
                return True

        limit = SHIP_LIST_MAX_OWNED if is_owned else SHIP_LIST_MAX_IMPORTED
        context_count = sum(
            1 for e in self._ship_list
            if e.get("is_owned") == is_owned
            and (not is_owned or e.get("commander") == commander)
        )
        if context_count >= limit:
            return False

        entry["sort_order"] = self._next_ship_sort_order(is_owned=is_owned, commander=commander)
        self._ship_list.append(entry)
        self._save_ship_list()
        return True

    def _ship_list_remove_by_id(self, ship_id, commander=None):
        if ship_id is None:
            return False
        for i, existing in enumerate(self._ship_list):
            is_match = (existing.get("is_owned") and
                        existing.get("commander") == commander and
                        existing.get("loadout", {}).get("ShipID") == ship_id)
            if is_match:
                self._ship_list.pop(i)
                self._save_ship_list()
                return True
        return False


    # --- FSD Extraction & Loadout Processing ---

    def _extract_fsd_data_from_loadout(self, entry):
        """Extract FSD specs from a loadout, applying engineering overrides and guardian booster if present."""
        modules = entry.get('Modules', [])
        fsd_module = None
        for mod in modules:
            if mod.get('Slot') == 'FrameShiftDrive':
                fsd_module = mod
                break

        if not fsd_module:
            return None

        item_name = fsd_module.get('Item', '')
        specs = get_fsd_specs(item_name)
        if not specs:
            return None

        fsd_class = specs['class']
        fsd_rating = specs['rating']

        fsd_data = dict(specs)
        engineering = fsd_module.get('Engineering', {})
        modifiers = engineering.get('Modifiers', [])
        for modifier in modifiers:
            label = modifier.get('Label', '')
            value = modifier.get('Value')
            if value is None:
                continue
            if label == 'FSDOptimalMass':
                fsd_data['optimal_mass'] = float(value)
            elif label == 'MaxFuelPerJump':
                fsd_data['max_fuel_per_jump'] = float(value)

        fuel_capacity = entry.get('FuelCapacity', {})
        fsd_data['tank_size'] = fuel_capacity.get('Main', 16)
        fsd_data['reserve_size'] = fuel_capacity.get('Reserve', 0.63)
        fsd_data['unladen_mass'] = entry.get('UnladenMass', 0)
        fsd_data['cargo_capacity'] = entry.get('CargoCapacity', 0)

        range_boost = 0.0
        for mod in modules:
            item = mod.get('Item', '').lower()
            if 'fsdbooster' in item or 'fsd_booster' in item:
                match = re.search(r'size(\d+)', item)
                if match:
                    size = int(match.group(1))
                    range_boost = GUARDIAN_FSD_BOOSTS.get(size, 0.0)
        fsd_data['range_boost'] = range_boost

        return fsd_data, fsd_class, fsd_rating, range_boost

    def process_loadout(self, entry):
        """Full loadout pipeline: extract FSD data, update ship_fsd_data, and sync the ship list."""
        extracted = self._extract_fsd_data_from_loadout(entry)
        if not extracted:
            return

        fsd_data, fsd_class, fsd_rating, range_boost = extracted

        self.ship_fsd_data = fsd_data
        try:
            self.current_ship_loadout = copy.deepcopy(entry)
        except Exception:
            self.current_ship_loadout = dict(entry)

        if self._ship_loadout_has_ship_info(entry):
            cmdr = getattr(self, "current_commander", "")
            if not cmdr:
                try:
                    cmdr = str(getattr(monitor, "cmdr", "") or monitor.state.get("Commander", "") or "").strip()
                except Exception:
                    logger.debug("Failed to get commander from monitor", exc_info=True)
            if cmdr:
                added = self._ship_list_add(entry, is_owned=True, commander=cmdr)
                try:
                    self._dashboard_last_ship_id = entry.get("ShipID")
                except Exception:
                    pass
                if hasattr(self, "_refresh_ship_list_rows"):
                    self._refresh_ship_list_rows()
                if hasattr(self, "_update_exact_ship_status_label"):
                    try:
                        self._update_exact_ship_status_label()
                    except Exception:
                        pass
                if not added and hasattr(self, "_notify_ship_list_full"):
                    self._notify_ship_list_full()

        logger.info(f"FSD data detected: class {fsd_class}{fsd_rating}, "
                     f"optimal_mass={fsd_data['optimal_mass']}, "
                     f"max_fuel={fsd_data['max_fuel_per_jump']}, "
                     f"tank={fsd_data['tank_size']}, "
                     f"boost={range_boost}")

    def try_fsd_from_state(self, state):
        if getattr(self, "ship_fsd_data", None) is not None:
            return
        if not state:
            return
        self._detect_fsd_from_state(state)

    def _detect_fsd_from_monitor(self):
        try:
            self._detect_fsd_from_state(monitor.state)
        except Exception as e:
            logger.debug(f"Could not detect FSD from monitor: {e}")

    def _detect_fsd_from_state(self, state):
        if not state:
            return
        modules = state.get('Modules')
        if not modules:
            return
        try:
            if isinstance(modules, dict):
                module_list = []
                for slot_name, module in modules.items():
                    if isinstance(module, dict):
                        enriched = dict(module)
                        enriched.setdefault("Slot", slot_name)
                        module_list.append(enriched)
                    else:
                        module_list.append(module)
            else:
                module_list = list(modules)

            fuel_cap = state.get('FuelCapacity', 16)
            if isinstance(fuel_cap, dict):
                fuel_main = fuel_cap.get('Main', 16)
                fuel_reserve = fuel_cap.get('Reserve', 0.63)
            else:
                fuel_main = fuel_cap if fuel_cap else 16
                fuel_reserve = 0.63

            synthetic = {
                'event': 'Loadout',
                'Modules': module_list,
                'FuelCapacity': {
                    'Main': fuel_main,
                    'Reserve': fuel_reserve,
                },
                'UnladenMass': state.get('UnladenMass', 0),
                'CargoCapacity': state.get('CargoCapacity', 0),
                'Ship': state.get('ShipType', '') or state.get('Ship', ''),
                'ShipName': state.get('ShipName', ''),
                'ShipIdent': state.get('ShipIdent', ''),
                'ShipID': state.get('ShipID'),
            }
            self.process_loadout(synthetic)
        except Exception as e:
            logger.debug(f"Could not extract FSD from state: {e}")

    # --- Jump Range Calculation ---

    def _suggest_jump_range(self):
        """Estimate max jump range from monitor or ship list — used to prefill plotter range fields."""
        if not getattr(self, "_range_prefill_ready", False):
            return None

        loadout = None
        if getattr(monitor, "live", False):
            loadout = monitor.ship()

        if not loadout:
            current_ship_id = monitor.state.get("ShipID")
            current_ship_model = monitor.state.get("Ship")

            if current_ship_id is not None:
                for entry in getattr(self, "_ship_list", []):
                    l = (entry.get("loadout", {}) if isinstance(entry, dict) else {})
                    if l.get("ShipID") == current_ship_id:
                        loadout = l
                        break

            if not loadout and current_ship_model:
                for entry in getattr(self, "_ship_list", []):
                    l = (entry.get("loadout", {}) if isinstance(entry, dict) else {})
                    if str(l.get("Ship")).lower() == current_ship_model.lower():
                        loadout = l
                        break

        if not loadout:
            return None

        try:
            extracted = self._extract_fsd_data_from_loadout(loadout)
            if not extracted:
                return None
            fsd = extracted[0]
            range_boost = float(extracted[3]) if len(extracted) > 3 else 0.0

            optimal_mass = self._safe_float(fsd.get("optimal_mass"), 0)
            max_fuel_per_jump = self._safe_float(fsd.get("max_fuel_per_jump"), 0)
            fuel_multiplier = self._safe_float(fsd.get("fuel_multiplier"), 0)
            fuel_power = self._safe_float(fsd.get("fuel_power"), 0)

            fuel_main = self._safe_float(getattr(self, "current_fuel_main", None), None)
            if fuel_main is None or fuel_main < 0:
                fuel_main = self._safe_float(monitor.state.get("FuelLevel"), None)
                if fuel_main is None:
                    fuel_main = self._safe_float(fsd.get("tank_size"), 32.0)

            fuel_reservoir = self._safe_float(getattr(self, "current_fuel_reservoir", None), 0.0) or 0.0
            if not getattr(monitor, "live", False) and not fuel_reservoir:
                fuel_reservoir = self._safe_float(fsd.get("reserve_size"), 0.63)

            fuel_mass = fuel_main + fuel_reservoir
            if fuel_mass <= 0:
                fuel_mass = 32.63

            try:
                cargo_mass = sum((monitor.state.get("Cargo") or {}).values())
            except Exception:
                cargo_mass = 0

            unladen_mass = self._safe_float(fsd.get("unladen_mass"), 0)
            if unladen_mass <= 0:
                try:
                    unladen_mass = self._safe_float(monitor.state.get("UnladenMass"), 0)
                except Exception:
                    unladen_mass = 0

            if unladen_mass <= 0:
                return None

            base_mass = unladen_mass + fuel_mass + cargo_mass

            if optimal_mass > 0 and max_fuel_per_jump > 0 and fuel_multiplier > 0 and fuel_power > 0 and base_mass > 0:
                jump_range = (optimal_mass / base_mass) * ((max_fuel_per_jump / fuel_multiplier) ** (1 / fuel_power))
                return round(jump_range + range_boost, 2)

        except Exception:
            logger.debug("Jump range calculation failed", exc_info=True)

        return None

    # --- Active Ship & Validation ---

    def _ship_loadout_has_ship_info(self, entry):
        if not isinstance(entry, dict):
            return False
        modules = entry.get("Modules")
        if not isinstance(modules, list) or not modules:
            return False
        if entry.get("ShipID") is not None:
            return bool(entry.get("Ship"))
        return any(str(entry.get(key) or "").strip() for key in ("Ship", "ShipName", "ShipIdent"))

    def _active_exact_ship_loadout(self):
        if getattr(self, "_exact_imported_ship_loadout", None):
            return self._exact_imported_ship_loadout
        try:
            loadout = monitor.ship()
            if loadout:
                return loadout
        except Exception:
            logger.debug("Failed to get ship loadout from monitor", exc_info=True)
        return getattr(self, "current_ship_loadout", None)

    def _active_exact_ship_fsd_data(self):
        def _valid(fsd):
            return fsd and self._safe_float(fsd.get("unladen_mass"), 0) > 0

        if _valid(getattr(self, "_exact_imported_ship_fsd_data", None)):
            return self._exact_imported_ship_fsd_data
        try:
            loadout = monitor.ship()
            if loadout:
                extracted = self._extract_fsd_data_from_loadout(loadout)
                if extracted and _valid(extracted[0]):
                    return extracted[0]
        except Exception:
            logger.debug("Failed to extract FSD data from monitor ship", exc_info=True)
        stored = getattr(self, "current_ship_loadout", None)
        if stored:
            try:
                extracted = self._extract_fsd_data_from_loadout(stored)
                if extracted and _valid(extracted[0]):
                    return extracted[0]
            except Exception:
                logger.debug("Failed to extract FSD data from stored loadout", exc_info=True)
        fsd = getattr(self, "ship_fsd_data", None)
        return fsd if _valid(fsd) else None

    # --- Ship Import/Export ---

    def _sanitize_loadout_for_export(self, payload):
        if isinstance(payload, list):
            return [self._sanitize_loadout_for_export(item) for item in payload]
        if not isinstance(payload, dict):
            return payload
        if "header" in payload and isinstance(payload.get("data"), dict):
            new_payload = copy.deepcopy(payload)
            new_payload["data"] = self._sanitize_loadout_for_export(payload["data"])
            return new_payload
        return {k: v for k, v in payload.items() if k in SLEF_CLEAN_KEYS}

    def _ship_loadout_from_import_payload(self, payload):
        """Parse a SLEF/JSON import payload (possibly wrapped in a list) and extract the loadout dict."""
        if isinstance(payload, list):
            for item in payload:
                loadout = self._ship_loadout_from_import_payload(item)
                if loadout is not None:
                    return loadout
            return None
        if not isinstance(payload, dict):
            return None
        wrapped_candidate = payload.get("data") if isinstance(payload.get("data"), dict) else None
        if wrapped_candidate and self._ship_loadout_has_ship_info(wrapped_candidate):
            return copy.deepcopy(wrapped_candidate)
        if self._ship_loadout_has_ship_info(payload):
            return copy.deepcopy(payload)
        return None

    def _ship_export_payload(self, loadout):
        if not self._ship_loadout_has_ship_info(loadout):
            return None
        return [
            {
                "header": {
                    "appName": "EDMC-SpanshTools",
                    "appVersion": self.plugin_version,
                },
                "data": self._sanitize_loadout_for_export(copy.deepcopy(loadout)),
            }
        ]

    def _get_ship_index_by_name(self, name, exclude_index=None):
        ships = getattr(self, "_ship_list", [])
        search_name = str(name or "").strip().lower()
        if not search_name:
            return None
        for i, ship in enumerate(ships):
            if exclude_index is not None and i == exclude_index:
                continue
            if str(ship.get("name") or "").strip().lower() == search_name:
                return i
        return None

    def _is_ship_name_duplicate(self, name, exclude_index=None):
        return self._get_ship_index_by_name(name, exclude_index) is not None

    def _ship_identity_key_str(self, loadout, *, commander=None, fallback_name=""):
        if not isinstance(loadout, dict):
            return ""
        ship_id = loadout.get("ShipID")
        if ship_id is not None:
            commander = str(
                commander if commander is not None else getattr(self, "current_commander", "")
            ).strip().lower()
            return f"owned_{commander}_{ship_id}"
        name = str(loadout.get("ShipName") or fallback_name or "").strip().lower()
        return f"imported_{name}" if name else ""

    def _ship_list_entry(self, loadout, *, is_owned=False, commander=None):
        return {
            "name": str(loadout.get("ShipName") or "").strip(),
            "ident": str(loadout.get("ShipIdent") or "").strip(),
            "ship_type": str(loadout.get("Ship") or "").strip(),
            "loadout": loadout,
            "is_owned": is_owned,
            "commander": commander,
        }

    def _save_selected_ship_to_config(self, loadout, *, commander=None):
        try:
            config.set(self._EXACT_SELECTED_SHIP_CONFIG_KEY, self._ship_identity_key_str(loadout, commander=commander))
        except Exception:
            logger.debug("Failed to save selected ship to config", exc_info=True)

    def _clear_selected_ship_config(self):
        try:
            config.set(self._EXACT_SELECTED_SHIP_CONFIG_KEY, "")
        except Exception:
            logger.debug("Failed to clear ship config", exc_info=True)

    def _restore_selected_ship_from_config(self):
        try:
            key = config.get_str(self._EXACT_SELECTED_SHIP_CONFIG_KEY, default="")
        except Exception:
            logger.debug("Failed to read ship config", exc_info=True)
            return
        if not key:
            return
        for entry in getattr(self, "_ship_list", []):
            if self._ship_identity_key_str(
                entry.get("loadout", {}),
                commander=entry.get("commander"),
                fallback_name=entry.get("name"),
            ) == key:
                loadout = entry.get("loadout")
                if loadout:
                    try:
                        self._apply_exact_ship_import_core(loadout, custom_name=entry.get("name"))
                    except Exception:
                        logger.debug("Failed to restore selected ship", exc_info=True)
                return

    def _apply_exact_ship_import_core(self, loadout, custom_name=None):
        extracted = self._extract_fsd_data_from_loadout(loadout)
        if not extracted:
            raise ValueError("The provided ship data does not contain a valid Frame Shift Drive loadout.")
        self._exact_imported_ship_loadout = copy.deepcopy(loadout)
        if custom_name:
            self._exact_imported_ship_loadout["ShipName"] = custom_name
        self._exact_imported_ship_fsd_data = extracted[0]
        return self._exact_imported_ship_loadout

    def _import_exact_ship_from_payload_core(self, payload, *, overwrite_index=None, custom_name=None):
        loadout = self._ship_loadout_from_import_payload(payload)
        if not loadout:
            raise ValueError("No ship information was found in the provided SLEF or JSON file.")
        if custom_name and custom_name.strip():
            loadout["ShipName"] = custom_name.strip()
        if not self._extract_fsd_data_from_loadout(loadout):
            raise ValueError("The provided ship data does not contain a valid Frame Shift Drive loadout.")
        if overwrite_index is not None:
            all_ships = getattr(self, "_ship_list", [])
            if 0 <= overwrite_index < len(all_ships):
                existing = all_ships[overwrite_index]
                new_entry = self._ship_list_entry(
                    loadout,
                    is_owned=existing.get("is_owned", False),
                    commander=existing.get("commander"),
                )
                new_entry["sort_order"] = existing.get("sort_order", overwrite_index)
                all_ships[overwrite_index] = new_entry
                self._save_ship_list()
                return loadout
        if not self._ship_list_add(loadout):
            raise ValueError(f"Imported ship list is full ({SHIP_LIST_MAX_IMPORTED}). Remove a ship to make room.")
        return loadout
