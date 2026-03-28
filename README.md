# EDMC-SpanshTools

An [Elite Dangerous Market Connector](https://github.com/EDCD/EDMarketConnector) plugin that brings multiple [Spansh](https://spansh.co.uk) route tools directly into EDMC.

It supports route planning, route import/export, route progress tracking, optional overlays, and an integrated route viewer.

## Features

- **Supports many Spansh plotters** for travel, exploration, and fleet carrier routing.
- **Route viewer** - `Show route` opens an integrated table view for reviewing route rows, totals, copy actions, export actions, and route progress.
- **Automations** - Includes route and ship-state automations such as waypoint progression, route guidance refresh, clipboard updates, and overlay refresh behavior.
- **Overlays** - Supports fuel and neutron route overlays through Modern Overlay integration.
- **Import / Export** - Supports importing and exporting route data across the plugin’s current CSV and JSON(recommended) workflows.
- **Persistence** - Restores saved routes and planner settings between EDMC sessions.
- **Search tools** - Includes nearest-system search today, with room for broader Spansh search tools later.
- **Built-in updater** - Checks for updates on startup, stages the update in the background, and installs it on quit after you accept it.

## Installation

1. Download the [latest release](../../releases/latest).
2. Extract it into your EDMC plugins folder:
   - **Windows**: `%LOCALAPPDATA%\\EDMarketConnector\\plugins\\`
   - **Linux**: `~/.local/share/EDMarketConnector/plugins/`
   - **Linux (Flatpak)**: `~/.var/app/io.edcd.EDMarketConnector/data/EDMarketConnector/plugins/`
3. On Linux/X11, make sure `xclip` is installed.
   - Example: `sudo apt install xclip`
   - Example: `sudo pacman -S xclip`
4. Restart EDMC.

## Updating

SpanshTools checks for new releases on startup.

When an update is available:
- a `⚠` button appears next to the plugin title
- clicking it opens the changelog/update popup
- if you accept, the plugin downloads the update in the background and prepares it
- the prepared update is installed automatically the next time EDMC closes cleanly

This is not an immediate live update while EDMC is running. The plugin prepares the update first, then installs it on quit. Route state and plugin settings are preserved.

For a manual update, replace the `EDMC-SpanshTools` plugin folder with the latest release.

## Usage

### Plotters

Available route planners:
- `Neutron Plotter`
- `Galaxy Plotter`
- `Road to Riches`
- `Ammonia World Route`
- `Earth-like World Route`
- `Rocky/HMC Route`
- `Fleet Carrier Router`
- `Exomastery`

#### Plotter Notes

- Most plotter windows include small info popups/tooltips for explaining inputs and options.
- System input fields support autocomplete, so you can search and pick systems directly from the plotter windows instead of typing every name fully.
- If a route is already active, opening the same plotter again will prefill that plotter window with the current route's settings where possible.

### Route viewer

- `Show route` opens the current route in a separate table view.
- It supports plotted routes, imported routes, and plugin-saved routes.
- You can review route rows, totals, current progress, and route-specific columns depending on the planner.
- Right click context menu that has copy actions and waypoint setting, 
- `File` menu has CSV and JSON(recommended) exports,
- The `View` menu lets you switch the viewer between light and dark mode and `Text Size` menu lets you change route viewer text size. Also `Clear Done` for unchecking all boxes.
- Viewer state follows real route progress in real time as you move through the route.

### Overlays

Overlay support requires [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay).

Supported overlays:
- `Fuel Overlay`
- `Supercharge Overlay`

Behavior:
- fuel overlay warns when the current plotted jump requires scooping/refuel behavior
- supercharge overlay warns when a neutron boost is needed
- after `JetConeBoost`, the `SUPERCHARGE` warning clears until the next relevant jump

## Linux Support

On Linux, SpanshTools uses external clipboard tools instead of Tk clipboard ownership:
- `wl-copy` on Wayland
- `xclip` on X11

You can override the clipboard command with:

```bash
export EDMC_SPANSH_TOOLS_XCLIP="/usr/bin/wl-copy"
```

### Flatpak Notes

Flatpak users need host clipboard tool access.

### Option A - Using Flatseal

- open Flatseal
- select `EDMarketConnector`
- under **Filesystem**, enable `All system libraries, executables and static data` (`filesystem=host-os`)
- if using Wayland, also enable the **Wayland windowing system** socket
- on Wayland, add this environment variable:

```bash
EDMC_SPANSH_TOOLS_XCLIP=/run/host/usr/bin/wl-copy
```

### Option B - Using command line

X11:

```bash
flatpak override --user io.edcd.EDMarketConnector --filesystem=host-os
```

Wayland:

```bash
flatpak override --user io.edcd.EDMarketConnector --socket=wayland --filesystem=host-os --env=EDMC_SPANSH_TOOLS_XCLIP=/run/host/usr/bin/wl-copy
```

Restart EDMC after changing Flatpak permissions.

## Good To Know

- If you want to use exports from [Spansh](https://spansh.co.uk), prefer JSON over CSV. Spansh JSON exports preserve more route metadata, and JSON imports can restore the plotter settings that were saved with the original plotted route. If a JSON file was produced from a CSV-based route and some settings are missing, the plugin falls back to route-derived values and plotter defaults where possible.
- Autocomplete suggestions can be broader than what Spansh routing endpoints accept, so a suggested system is not always guaranteed to be routable. Routing a plot in game logs up sytems in the Spansh database first, but it may still take some time before those systems become fully routable through the route APIs.

### Recommended Plugins

- [EDMC-SystemStatusOverlay](https://github.com/wuuthradd/EDMC-SystemStatusOverlay) - Quick overlay-based check for whether a target system exists in the Spansh database.
- [EDMC-BioScan](https://github.com/Silarn/EDMC-BioScan) - Useful companion for Exomastery and biology-heavy routes, with overlay-assisted exobiology workflow support.
- [EDMC-Pioneer](https://github.com/Silarn/EDMC-Pioneer) - Helpful companion for exploration routes, especially for value tracking and exploration-focused workflow support.

## Reporting Issues

If something is broken, open an issue in the repository and include as much of this as possible:

- EDMC is assumed to be on the latest stable release. Older EDMC versions are not a supported target for backwards-compatibility fixes.
- SpanshTools is also assumed to be on the latest release. Reports against older plugin versions may be closed unless the issue is reproduced on current.
- Operating system
- Type of plotter / tool used
- Whether the route was plotted, imported from Spansh, or imported from plugin export
- Relevant CSV/JSON sample if import/export is involved

## Development

Create your own local virtual environment for development and testing:

```bash
python -m venv .venv
./.venv/bin/python -m pip install -r dev-requirements.txt
```

Run the test suite with:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall load.py SpanshTools tests
```

The tests initialize `tkinter` during collection, so your Python build must include Tk/Tcl support.

## Thanks

- [Spansh Thanks](https://spansh.co.uk/thanks) for the people and projects behind those tools
- Forked from: [norohind/EDMC_SpanshTools](https://github.com/norohind/EDMC_SpanshTools)
- Original plugin repo: [CMDR-Kiel42/EDMC_SpanshTools](https://github.com/CMDR-Kiel42/EDMC_SpanshTools)
