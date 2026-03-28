"""Module-level constants, CSV headers, and lightweight exceptions."""

import logging
import os

from config import appname

plugin_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
logger = logging.getLogger(f'{appname}.{plugin_name}')

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
RICHES_CSV_HEADER = (
    "System Name,Body Name,Body Subtype,Is Terraformable,"
    "Distance (Ls),Scan Value,Mapping Value,Jumps"
)
SPECIALIZED_RICHES_CSV_HEADER = (
    "System Name,Body Name,Distance (Ls),Scan Value,Mapping Value,Jumps"
)
SPANSH_SPECIALIZED_RICHES_CSV_HEADER = "System Name,Body Name,Distance To Arrival,Jumps"
PLUGIN_SPECIALIZED_RICHES_CSV_HEADER = "Done,System Name,Body Name,Distance To Arrival,Jumps"
EXOBIOLOGY_CSV_HEADER = (
    "Done,System Name,Name,Subtype,Distance (LS),"
    "Landmark Subtype,Count,Landmark Value,Jumps"
)
LEGACY_EXOBIOLOGY_CSV_HEADER_V2 = (
    "System Name,Body Name,Body Subtype,Distance (Ls),"
    "Landmark Subtype,Landmark Count,Landmark Value,Jumps"
)
LEGACY_RICHES_CSV_HEADER = "System Name,Jumps,Body Name,Body Subtype"
LEGACY_RICHES_CSV_HEADER_V2 = (
    "System Name,Body Name,Body Subtype,Is Terraformable,"
    "Distance To Arrival,Estimated Scan Value,Estimated Mapping Value,Jumps"
)
LEGACY_EXOBIOLOGY_CSV_HEADER = (
    "System Name,Body Name,Body Subtype,Distance To Arrival,"
    "Landmark Subtype,Landmark Count,Landmark Value,Jumps"
)

SPANSH_POLL_INTERVAL = 2
SPANSH_POLL_MAX_ITERATIONS = 120
FUEL_OVERLAY_ID = "spansh-fuel-warning"
NEUTRON_OVERLAY_ID = "spansh-neutron-warning"


class _SpanshPollError(Exception):
    """Raised when Spansh job polling encounters an error."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class _SpanshPollTimeout(Exception):
    """Raised when Spansh job polling times out."""
    pass
