# Changelog

## v1.1.0

- Added ship list for saving, importing, and managing ship loadouts with per-ship FSD data for the Galaxy Plotter.
- Added search history, "Get Coordinates" mode, and right-click context menu to the nearest system finder.
- Added "Open in EDSM" and "Open in Spansh" to the route viewer and nearest system finder.
- Improved route viewer rendering performance, added searching.
- Added test suite covering all source modules.
- Restructured codebase from single file into separate modules.
- Many fixes and improvements.

## v1.0.1

- Fixed multiple route, overlay, import/export, and updater issues.
- Improved exact plotter supercharge handling so the checkbox reflects only the current live state.
- Fixed route complete overlay persistence and several overlay edge cases.
- Fixed fleet route waypoint/refuel import-export round-trip issues.
- Improved plotter settings persistence across multiple planners.
- Fixed signed spinbox validation edge cases and several viewer refresh/export issues.
- Hardened updater and FSD spec update behavior, including safer staged installs and atomic FSD spec writes.

## v1.0.0

- Initial release
