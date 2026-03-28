"""Overlay mixin — fuel scoop and neutron supercharge overlays."""
import tkinter as tk

from config import config

from .constants import (
    FUEL_OVERLAY_ID,
    NEUTRON_OVERLAY_ID,
    logger,
)


class OverlayMixin:
    """Mixin providing overlay display and settings for SpanshTools."""

    def _send_overlay_message(self, message_id, text, color, x, y, *, ttl, size="normal", error_message="Overlay send failed"):
        """Send a legacy overlay message through the active overlay client."""
        if not self.overlay:
            return False
        try:
            self.overlay.send_message(message_id, text, color, x, y, ttl=ttl, size=size)
            return True
        except Exception:
            self._log_unexpected(error_message)
            return False

    def _send_overlay_clear(self, message_id, *, debug_message):
        """Clear an overlay item through the Modern Overlay legacy raw clear path."""
        if not self.overlay:
            return False
        try:
            self.overlay.send_raw({"id": message_id, "ttl": 0})
            return True
        except Exception:
            logger.debug(debug_message, exc_info=True)
            return False

    def _clear_route_overlays(self):
        self._clear_overlay()
        self._clear_neutron_overlay()

    def _load_overlay_settings(self):
        """Load overlay settings from EDMC config."""
        self._overlay_loading = True
        try:
            enabled = bool(config.get_int('spansh_overlay_enabled', default=0))
            x = config.get_int('spansh_overlay_x', default=590)
            y = config.get_int('spansh_overlay_y', default=675)
            self.overlay_var.set(enabled)
            self.overlay_x_var.set(x)
            self.overlay_y_var.set(y)
        except Exception as e:
            logger.debug(f"Could not load fuel overlay settings: {e}")

        try:
            neutron_enabled = bool(config.get_int('spansh_supercharge_overlay_enabled', default=0))
            nx = config.get_int('spansh_supercharge_overlay_x', default=600)
            ny = config.get_int('spansh_supercharge_overlay_y', default=675)
            self.neutron_overlay_var.set(neutron_enabled)
            self.neutron_x_var.set(nx)
            self.neutron_y_var.set(ny)
        except Exception as e:
            logger.debug(f"Could not load supercharge overlay settings: {e}")
        self._overlay_loading = False

    def _save_overlay_settings(self):
        """Save overlay settings to EDMC config."""
        if self._overlay_loading:
            return
        try:
            config.set('spansh_overlay_enabled', int(self.overlay_var.get()))
            config.set('spansh_overlay_x', self.overlay_x_var.get())
            config.set('spansh_overlay_y', self.overlay_y_var.get())
        except Exception as e:
            logger.debug(f"Could not save fuel overlay settings: {e}")
        try:
            config.set('spansh_supercharge_overlay_enabled', int(self.neutron_overlay_var.get()))
            config.set('spansh_supercharge_overlay_x', self.neutron_x_var.get())
            config.set('spansh_supercharge_overlay_y', self.neutron_y_var.get())
        except Exception as e:
            logger.debug(f"Could not save supercharge overlay settings: {e}")

    def toggle_overlay(self):
        """Toggle the fuel scoop overlay on/off."""
        if self.overlay is None:
            self.overlay_var.set(False)
            self.show_error(
                "EDMCModernOverlay not installed.\n"
                "Get it from: github.com/SweetJonnySauce/EDMCModernOverlay"
            )
            return

        if self.overlay_var.get():
            self.overlay_pos_frame.grid()
            self._update_overlay()
        else:
            self.overlay_pos_frame.grid_remove()
            self._clear_overlay()
        self._save_overlay_settings()

    def toggle_neutron_overlay(self):
        """Toggle the neutron supercharge overlay on/off."""
        if self.overlay is None:
            self.neutron_overlay_var.set(False)
            self.show_error(
                "EDMCModernOverlay not installed.\n"
                "Get it from: github.com/SweetJonnySauce/EDMCModernOverlay"
            )
            return

        if self.neutron_overlay_var.get():
            self.neutron_pos_frame.grid()
            self._update_overlay()
        else:
            self.neutron_pos_frame.grid_remove()
            self._clear_neutron_overlay()
        self._save_overlay_settings()

    def _update_overlay(self):
        """Show or hide fuel scoop and neutron overlays based on current waypoint."""
        if not self.overlay:
            return
        if not (self.exact_plotter or self.galaxy or self._is_neutron_route_active()):
            self._clear_route_overlays()
            return
        # Don't update overlay during manual waypoint navigation
        if getattr(self, '_manual_nav', False):
            return

        # Neither overlay enabled -- nothing to do
        if not self.overlay_var.get() and not self.neutron_overlay_var.get():
            self._clear_route_overlays()
            return

        try:
            fuel_x = self.overlay_x_var.get()
            fuel_y = self.overlay_y_var.get()
        except (tk.TclError, ValueError):
            fuel_x, fuel_y = 590, 675

        try:
            neutron_x = self.neutron_x_var.get()
            neutron_y = self.neutron_y_var.get()
        except (tk.TclError, ValueError):
            neutron_x, neutron_y = 600, 675

        # Route complete
        if self._route_complete_for_ui():
            self._clear_route_overlays()
            if self.overlay_var.get() and not self._overlay_route_complete_announced:
                self._send_overlay_message(
                    FUEL_OVERLAY_ID,
                    "Route Complete!",
                    "#00FF00",
                    fuel_x,
                    fuel_y,
                    ttl=10,
                    size="huge",
                    error_message="Overlay send failed",
                )
            self._overlay_route_complete_announced = True
            return

        self._overlay_route_complete_announced = False

        if not self._has_live_location_state():
            self._clear_route_overlays()
            return

        current_system_idx = self._overlay_current_system_index()
        row_state = self._route_row_state_at(current_system_idx) if current_system_idx is not None else {}
        if self.exact_plotter or self.galaxy:
            show_fuel = (
                self.overlay_var.get()
                and current_system_idx is not None
                and row_state.get("refuel_required", False)
            )
            show_neutron = (
                self.neutron_overlay_var.get()
                and current_system_idx is not None
                and row_state.get("has_neutron", False)
                and (
                    not getattr(self, "_supercharge_state_known", False)
                    or not getattr(self, "is_supercharged", False)
                )
            )
        else:
            show_fuel = False
            show_neutron = (
                self.neutron_overlay_var.get()
                and current_system_idx is not None
                and row_state.get("has_neutron", False)
                and (
                    not getattr(self, "_supercharge_state_known", False)
                    or not getattr(self, "is_supercharged", False)
                )
            )

        # Smart Y collision avoidance: when both show and Y gap < 15,
        # offset neutron Y to be 15 above fuel Y.
        actual_neutron_y = neutron_y
        if show_fuel and show_neutron and abs(fuel_y - neutron_y) < 15:
            actual_neutron_y = fuel_y - 15

        # Fuel overlay
        if self.overlay_var.get():
            if show_fuel:
                self._send_overlay_message(
                    FUEL_OVERLAY_ID,
                    "SCOOP FUEL HERE",
                    "#FFD700",
                    fuel_x,
                    fuel_y,
                    ttl=99999,
                    size="huge",
                    error_message="Overlay send failed",
                )
            else:
                self._clear_overlay()

        # Neutron overlay
        if self.neutron_overlay_var.get():
            if show_neutron:
                self._send_overlay_message(
                    NEUTRON_OVERLAY_ID,
                    "SUPERCHARGE",
                    "#00BFFF",
                    neutron_x,
                    actual_neutron_y,
                    ttl=99999,
                    size="huge",
                    error_message="Neutron overlay send failed",
                )
            else:
                self._clear_neutron_overlay()

    def _clear_overlay(self):
        """Remove the fuel overlay message."""
        self._send_overlay_clear(
            FUEL_OVERLAY_ID,
            debug_message="Unable to clear fuel overlay",
        )

    def _clear_neutron_overlay(self):
        """Remove the neutron overlay message."""
        self._send_overlay_clear(
            NEUTRON_OVERLAY_ID,
            debug_message="Unable to clear neutron overlay",
        )
