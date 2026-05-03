"""Overlay mixin -- fuel scoop and neutron supercharge overlays."""

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
        if not self.overlay:
            return False
        try:
            self.overlay.send_message(message_id, text, color, x, y, ttl=ttl, size=size)
            return True
        except Exception:
            self._log_unexpected(error_message)
            return False

    def _send_overlay_clear(self, message_id, *, debug_message):
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
        self._overlay_loading = True
        try:
            try:
                enabled = bool(config.get_int('spansh_overlay_enabled', default=0))
                x = config.get_int('spansh_overlay_x', default=590)
                y = config.get_int('spansh_overlay_y', default=675)
                self.overlay_var.set(enabled and self.overlay is not None)
                self.overlay_x_var.set(x)
                self.overlay_y_var.set(y)
            except Exception as e:
                logger.debug(f"Could not load fuel overlay settings: {e}")

            try:
                neutron_enabled = bool(config.get_int('spansh_supercharge_overlay_enabled', default=0))
                nx = config.get_int('spansh_supercharge_overlay_x', default=600)
                ny = config.get_int('spansh_supercharge_overlay_y', default=675)
                self.neutron_overlay_var.set(neutron_enabled and self.overlay is not None)
                self.neutron_x_var.set(nx)
                self.neutron_y_var.set(ny)
            except Exception as e:
                logger.debug(f"Could not load supercharge overlay settings: {e}")
        finally:
            self._overlay_loading = False

    def _save_overlay_settings(self):
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

    def _toggle_overlay_impl(self, var, pos_frame, overlay_id):
        if self.overlay is None:
            var.set(False)
            self.show_error(
                "EDMCModernOverlay not installed.\n"
                "Get it from: github.com/SweetJonnySauce/EDMCModernOverlay"
            )
            return
        if var.get():
            pos_frame.grid()
            self._update_overlay()
        else:
            pos_frame.grid_remove()
            self._send_overlay_clear(overlay_id, debug_message="Unable to clear overlay on toggle")
        self._save_overlay_settings()

    def toggle_overlay(self):
        self._toggle_overlay_impl(self.overlay_var, self.overlay_pos_frame, FUEL_OVERLAY_ID)

    def toggle_neutron_overlay(self):
        self._toggle_overlay_impl(self.neutron_overlay_var, self.neutron_pos_frame, NEUTRON_OVERLAY_ID)

    def _update_overlay(self):
        if not self.overlay:
            return
        if not (self.exact_plotter or self._is_neutron_route_active()):
            self._clear_route_overlays()
            return
        if getattr(self, '_manual_nav', False):
            return

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

        if self._route_complete_for_ui():
            if self.overlay_var.get() and not self._overlay_route_complete_announced:
                self._clear_route_overlays()
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
            elif not self.overlay_var.get():
                self._clear_route_overlays()
                self._overlay_route_complete_announced = False
            return

        self._overlay_route_complete_announced = False

        if not self._has_live_location_state():
            self._clear_route_overlays()
            return

        current_system_idx = self._overlay_current_system_index()
        row_state = self._route_row_state_at(current_system_idx) if current_system_idx is not None else {}
        show_fuel = (
            self.exact_plotter
            and self.overlay_var.get()
            and current_system_idx is not None
            and row_state.get("refuel_required", False)
        )
        if show_fuel and getattr(self, "current_fuel_main", None) is not None:
            fsd = getattr(self, "ship_fsd_data", None) or {}
            tank_size = self._safe_float(fsd.get("tank_size"), 0)
            if tank_size > 0 and self.current_fuel_main >= tank_size:
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

        # Offset neutron Y when both overlays overlap
        actual_neutron_y = neutron_y
        if show_fuel and show_neutron and abs(fuel_y - neutron_y) < 15:
            actual_neutron_y = max(fuel_y - 15, 0)

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
        self._send_overlay_clear(
            FUEL_OVERLAY_ID,
            debug_message="Unable to clear fuel overlay",
        )

    def _clear_neutron_overlay(self):
        self._send_overlay_clear(
            NEUTRON_OVERLAY_ID,
            debug_message="Unable to clear neutron overlay",
        )
