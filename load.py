import logging

spansh_tools = None
logger = logging.getLogger('SpanshTools')


def _start_plugin(plugin_dir):
    global spansh_tools

    from SpanshTools import SpanshTools

    spansh_tools = SpanshTools(plugin_dir)
    return 'spansh_tools'


def plugin_start3(plugin_dir):
    return _start_plugin(plugin_dir)


def plugin_start(plugin_dir):
    return _start_plugin(plugin_dir)


def plugin_stop():
    global spansh_tools
    if spansh_tools is None:
        return
    shutdown_ok = True
    try:
        shutdown_ok = bool(spansh_tools.shutdown())
    except Exception:
        shutdown_ok = False
        logger.warning("Error while shutting down SpanshTools", exc_info=True)

    if shutdown_ok and spansh_tools.update_available and spansh_tools.has_staged_update():
        spansh_tools.install_staged_update()


def journal_entry(cmdr, is_beta, system, station, entry, state):
    global spansh_tools
    if not getattr(spansh_tools, 'frame', None):
        return
    spansh_tools.handle_journal_entry(system, entry, state)


def dashboard_entry(cmdr, is_beta, entry):
    global spansh_tools
    if not getattr(spansh_tools, 'frame', None):
        return
    spansh_tools.handle_dashboard_entry(entry)


def plugin_app(parent):
    global spansh_tools
    frame = spansh_tools.init_gui(parent)
    spansh_tools.open_last_route()
    # Check for updates after GUI is ready (runs in background thread)
    spansh_tools.check_for_update()
    return frame
