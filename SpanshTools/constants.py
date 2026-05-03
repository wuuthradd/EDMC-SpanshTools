"""Module-level constants, CSV headers, and lightweight exceptions."""

import logging
import os

from config import appname

_plugin_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
logger = logging.getLogger(f'{appname}.{_plugin_name}')

ROUTE_PLANNERS = [
    "Neutron Plotter",
    "Galaxy Plotter",
    "Road to Riches",
    "Ammonia World Route",
    "Earth-like World Route",
    "Rocky/HMC Route",
    "Fleet Carrier Router",
    "Exomastery",
]
SEARCH_OPTIONS = [
    "Find nearest system",
]

SPANSH_POLL_INTERVAL = 2
SPANSH_POLL_MAX_ITERATIONS = 120
FUEL_OVERLAY_ID = "spansh-fuel-warning"
NEUTRON_OVERLAY_ID = "spansh-neutron-warning"

# GitHub and Update settings
GITHUB_REPO = "wuuthradd/EDMC-SpanshTools"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RAW_FSD_SPECS = f"https://raw.githubusercontent.com/{GITHUB_REPO}/master/SpanshTools/data/fsd_specs.json"
RELEASE_ARCHIVE_ROOT = "EDMC-SpanshTools"
RUNTIME_PACKAGE_DIRS = ("SpanshTools", "tksheet")
REQUIRED_ARCHIVE_PATHS = (
    "load.py",
    "version.json",
    "SpanshTools/__init__.py",
    "SpanshTools/data/fsd_specs.json",
    "SpanshTools/data/ship_type_names.json",
    "tksheet/__init__.py",
)
USER_DATA_FILES = {
    os.path.join("SpanshTools", "data", "route_state.json"),
    os.path.join("SpanshTools", "data", "ship_list.json"),
    os.path.join("SpanshTools", "data", "plotter_settings.json"),
}

STAGED_ARCHIVE_NAME = "update.zip"
STAGED_METADATA_NAME = "update_pending.json"

# AutoCompleter settings
MAX_VISIBLE_RESULTS = 8
DEBOUNCE_MS = 250

# Ship list limits per category
SHIP_LIST_MAX_OWNED = 1000
SHIP_LIST_MAX_IMPORTED = 1000

SLEF_CLEAN_KEYS = {
    "Ship",
    "ShipID",
    "ShipName",
    "ShipIdent",
    "HullValue",
    "ModulesValue",
    "Rebuy",
    "Hot",
    "MaxJumpRange",
    "UnladenMass",
    "FuelCapacity",
    "CargoCapacity",
    "Modules",
    "event",
}

COLUMN_MIN_WIDTHS = {
    idx: width for width, names in {
        440: ["System Name", "System", "Name", "Body Name"],
        260: ["Landmark Subtype", "Subtype"],
        160: ["Tritium in market", "Restock Amount", "Mapping Value", "Scan Value", "Landmark Value"],
        140: ["Remaining (LY)", "Fuel Left (T)", "Fuel Used (T)",
                "Distance (Ls)", "Distance (LY)"],
        120: ["Jumps Left"],
        100: ["Icy ring", "Restock?"],
        90: ["Count","Refuel?", "Neutron"],
        80: ["Terra", "Jumps"],
    }.items() for name in names for idx in [name]
}


class _SpanshPollError(Exception):
    """Raised when Spansh job polling encounters an error."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class _SpanshPollTimeout(Exception):
    """Raised when Spansh job polling times out."""
