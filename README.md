# EDMC-SpanshTools

An [Elite Dangerous Market Connector](https://github.com/EDCD/EDMarketConnector) plugin that brings multiple [Spansh](https://spansh.co.uk) route tools directly into EDMC.

It supports route planning, route import/export, route progress tracking, optional overlays, and an integrated route viewer.

## Features

- **Multiple Spansh plotters** for travel, exploration, and fleet carrier routing.
- **Route viewer** -- `Show route` opens an integrated spreadsheet view with route rows, totals, done-checkboxes, search filtering, and CSV/JSON export.
- **Ship list** -- Save, import, and export ship loadouts (SLEF/JSON) for the Galaxy Plotter. The plotter auto-detects your current ship's FSD and prefills jump range and cargo.
- **Automations** -- Waypoint progression, clipboard updates, refuel/restock warnings, and overlay refresh happen automatically as you fly.
- **Overlays** -- Fuel and neutron route overlays through EDMCModernOverlay integration.
- **Import / Export** -- Import and export route data as JSON. Exports preserve plotter settings and done-progress.
- **Persistence** -- Routes, done-progress, plotter settings, and ship list are restored between EDMC sessions.
- **Search tools** -- Nearest-system finder with coordinate or system-name input and search history.
- **Built-in updater** -- Checks for updates on startup, stages the download in the background, and installs on quit.

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

When an update is available, an `Update` button appears next to the plugin title. Clicking it opens a popup showing the version change and changelog. Accepting stages the download in the background and installs it automatically the next time EDMC closes cleanly.

For a manual update, replace the `EDMC-SpanshTools` plugin folder with the latest release.

## Usage

The main panel shows a plotter dropdown and a `Plot route` button. Select a plotter, click `Plot route`, fill in the settings, and start the route. Once a route is active, the panel shows waypoint navigation with previous/next buttons and distance info. Use `Import file` to load a JSON route, `Show route` to open the route viewer, and `Clear route` to discard the current route. The search dropdown provides access to search tools. Overlay checkboxes toggle fuel and supercharge overlays, with X/Y spinboxes to position them on screen with smart collision auto margin.

All settings; selected plotter, overlay toggles, overlay positions, collapse states, and plotter form values are saved through EDMC's config and restored on next launch. Routes and done progress are saved separately and also restored between sessions.

The plugin has two collapse buttons. The one on the title bar hides the entire UI down to just the title, one next to the controls hides the plotter dropdowns, overlay checkboxes, and buttons while keeping the route info visible. Both persist across sessions.

### Plotters

Available route planners:

- **Neutron Plotter** -- this plotter will allow you to plot between two different star systems. The result will show you every time you need to go to the galaxy map in order to plot a new route (for instance when you are at a neutron star). It will prioritise neutron stars so should be avoided for journeys which are lower than 500 light years (It will likely try to route you to Jackson's Lighthouse first if you're in the bubble). Supports via (intermediate) systems and reverse route.
- **Galaxy Plotter** -- Exact jump-by-jump routing between two systems with fuel usage, neutron supercharges, and injection boosts. Uses your ship's FSD data for accurate range calculation.
- **Road to Riches** -- Exploration routing that finds high-value scannable bodies along a path. Leave destination blank for a circular tour that returns to your starting system.
- **Ammonia World Route** -- Finds ammonia worlds near your location, prioritised by scan value.
- **Earth-like World Route** -- Finds earth-like worlds near your location, prioritised by scan value.
- **Rocky/HMC Route** -- Finds rocky and high metal content worlds near your location, prioritised by scan value.
- **Fleet Carrier Router** -- Routes your fleet carrier between systems, showing every jump and when to gather more tritium. Supports multiple destinations.
- **Exomastery** -- Finds high-value exobiology sites along a route for scanning and sampling biological signals on planetary surfaces.

#### Plotter Notes

- Most plotter windows include tooltips explaining inputs and options.
- System input fields support autocomplete -- you can search and pick systems directly.
- Opening a plotter while a route is active prefills its settings from the current route where possible.

### Ship list

The Galaxy Plotter includes a ship list for managing saved loadouts.

- Save your current ship or import loadouts in SLEF or JSON format.
- Select a saved ship to prefill FSD data, jump range, and cargo in the plotter.
- Filter by commander or switch to the shared "Imported" list.
- Search ships by name, ident, or type.
- Drag-and-drop to reorder entries.
- Right-click for Copy SLEF, Open in Coriolis, Open in EDSY, and Copy to Imported.
- Export individual loadouts or the full list as JSON.

### Route viewer

- `Show route` opens the current route in a spreadsheet window.
- Works with plotted, imported, and saved routes.
- Columns adapt to the plotter type (fuel info for exact, body details for exploration, tritium for fleet carrier).
- Done-checkboxes let you mark individual bodies or systems as completed.
- Search filter narrows the view to matching rows.
- Right-click context menu for copy actions, waypoint setting, Open in EDSM, and Open in Spansh.
- `File` menu for CSV and JSON (recommended) export.
- `View` menu for light/dark mode, text size, and clearing all done-checkboxes.
- The viewer updates in real time as you fly through the route.

### Search tools

`Find nearest system` opens a search window with two modes:

- **Find Nearest** -- enter X/Y/Z galactic coordinates to find the closest system in the Spansh database.
- **Get Coordinates** -- enter a system name (with autocomplete) to look up its coordinates. Falls back to EDSM if Spansh doesn't have it.

Results are copied to clipboard automatically. Search history is saved between sessions in a collapsible list. Right-click history entries for Copy Name, Copy Coordinates, Open in EDSM, or Open in Spansh.

### Overlays

Overlay support requires [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay).

Supported overlays:
- `Fuel Overlay` -- shows "SCOOP FUEL HERE" when the current system is a refuel stop on Galaxy Plotter routes. Clears automatically when the fuel tank is full.
- `Supercharge Overlay` -- shows "SUPERCHARGE" when a neutron boost is needed. Clears automatically after supercharging.

When the route is finished, the fuel overlay displays "Route Complete!".

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

- Routes exported from [Spansh](https://spansh.co.uk) can be imported directly. JSON imports can restore the plotter settings that were saved with the original plotted route.
- Autocomplete suggestions can be broader than what Spansh routing endpoints accept, so a suggested system is not always guaranteed to be routable. Routing a plot in game logs up systems in the Spansh database first, but it may still take some time before those systems become fully routable through the route APIs.

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
- Relevant JSON sample if import/export is involved

## Development

Create your own local virtual environment for development and testing:

```bash
python -m venv .venv
./.venv/bin/python -m pip install -r dev-requirements.txt
```

Run the test suite with:

```bash
./.venv/bin/python -m pytest -q
```

The tests initialize `tkinter` during collection, so your Python build must include Tk/Tcl support.

## Thanks

- [Spansh Thanks](https://spansh.co.uk/thanks) for the people and projects behind those tools
- Forked from: [norohind/EDMC_SpanshTools](https://github.com/norohind/EDMC_SpanshTools)
- Original plugin repo: [CMDR-Kiel42/EDMC_SpanshTools](https://github.com/CMDR-Kiel42/EDMC_SpanshTools)
