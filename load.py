"""EDMC plugin entry point — bridges EDMC lifecycle hooks to SpanshTools."""

spansh_tools = None


def _require_plugin():
    if spansh_tools is None:
        raise RuntimeError("SpanshTools plugin is not initialized")
    return spansh_tools


def _start_plugin(plugin_dir):
    global spansh_tools

    from SpanshTools import SpanshTools

    spansh_tools = SpanshTools(plugin_dir)
    return 'spansh_tools'


def plugin_start3(plugin_dir):
    """EDMC hook: initialize the plugin (Python 3)."""
    return _start_plugin(plugin_dir)


def plugin_start(plugin_dir):
    """EDMC hook: initialize the plugin (legacy Python 2 compatibility)."""
    return _start_plugin(plugin_dir)


def plugin_stop():
    """EDMC hook: shut down the plugin and install any staged update."""
    global spansh_tools
    if spansh_tools is None:
        return
    shutdown_ok = True
    try:
        shutdown_ok = bool(spansh_tools.shutdown())
    except Exception:
        shutdown_ok = False
        from SpanshTools.constants import logger
        logger.warning("Error while shutting down SpanshTools", exc_info=True)

    if shutdown_ok and spansh_tools.update_available and spansh_tools.has_staged_update():
        spansh_tools.install_staged_update()

    spansh_tools = None


def journal_entry(cmdr, is_beta, system, station, entry, state):
    """EDMC hook: forward journal events to the plugin for route tracking."""
    plugin = spansh_tools
    if plugin is None or not getattr(plugin, 'frame', None):
        return
    if cmdr:
        plugin.current_commander = cmdr
    plugin.handle_journal_entry(system, entry, state)


def dashboard_entry(cmdr, is_beta, entry):
    """EDMC hook: forward Status.json updates (fuel, flags) to the plugin."""
    plugin = spansh_tools
    if plugin is None or not getattr(plugin, 'frame', None):
        return
    if cmdr:
        plugin.current_commander = cmdr
    plugin.handle_dashboard_entry(entry)


def plugin_app(parent):
    """EDMC hook: build the plugin GUI frame and restore the last route."""
    plugin = _require_plugin()
    frame = plugin.init_gui(parent)
    plugin.open_last_route()
    # Check for updates after GUI is ready (runs in background thread)
    plugin.check_for_update()
    return frame
