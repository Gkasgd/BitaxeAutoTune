#!/usr/bin/env python3
"""
Interfaz de terminal enriquecida (TUI) del auto-tuner.

Dibuja un panel a pantalla completa con el estado del miner: hashrate en cifras
grandes, tablas por seccion (red, chip, potencia, temperatura, rendimiento,
sistema, ventiladores) y las ultimas lineas de log. Se refresca en su sitio
mediante el Live de rich, sin hacer scroll.

Aqui viven tambien el tema de color del proyecto y la instancia unica de
Console, porque este es el modulo que de verdad pinta en el terminal.

Uso:
    from ui_rich import RichTerminalUI

    ui = RichTerminalUI()
    ui.show_banner()
    ui.start()
    ui.update(system_info, voltage, frequency)
    ui.stop()

Dependencias:
    - Terceros: rich, pyfiglet
    - Estandar: time, typing
"""

import time
from typing import Any, Dict

import pyfiglet
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from interfaces import ITerminalUI

# Color constants for Cyberdeck TUI theme
BACKGROUND = "#121212"
TEXT_COLOR = "#E0E0E0"
PRIMARY_ACCENT = "#39FF14"
SECONDARY_ACCENT = "#00BFFF"
WARNING_COLOR = "#FF9933"
ERROR_COLOR = "#FF0000"
DECORATIVE_COLOR = "#FF0099"
TABLE_HEADER = DECORATIVE_COLOR
TABLE_ROW_EVEN = "#222222"
TABLE_ROW_ODD = "#444444"
PROGRESS_BAR_BG = "#333333"

# Instancia unica de Console para todo el proyecto. Rich no lleva bien que
# varios Console escriban al mismo terminal: el Live de RichTerminalUI toma el
# control de la pantalla y un Console distinto imprimiendo por su cuenta le
# corrompe el area redibujada. Todo lo que escriba en el terminal debe pasar
# por esta.
console = Console()


class RichTerminalUI(ITerminalUI):
    """Rich terminal UI for displaying miner status."""

    def __init__(self) -> None:
        """Initialize the rich terminal UI with layout and sections."""
        self.log_messages: list[str] = []
        self.has_data = False
        self.sections = {
            "Network": [
                "ssid",
                "macAddr",
                "wifiStatus",
                "stratumDiff",
                "isUsingFallbackStratum",
                "stratumURL",
                "stratumPort",
                "fallbackStratumURL",
                "fallbackStratumPort",
            ],
            "Chip": ["ASICModel", "asicCount", "smallCoreCount"],
            "Power": ["power", "voltage", "current"],
            "Thermal": ["temp", "vrTemp", "overheat_mode"],
            "Mining Performance": [
                "bestDiff",
                "bestSessionDiff",
                "sharesAccepted",
                "sharesRejected",
            ],
            "System": [
                "freeHeap",
                "uptimeSeconds",
                "version",
                "idfVersion",
                "boardVersion",
            ],
            "Display & Fans": ["autofanspeed", "fanspeed", "fanrpm"],
        }
        self.layout = self.create_layout()
        self.live = Live(self.layout, console=console, refresh_per_second=1)
        self._started = False

    def show_banner(self) -> None:
        """Display an initial banner until data is available."""
        try:
            with open("banner.txt", "r") as f:
                console.print(f.read())
            console.print("\nWaiting for miner data...", style=PRIMARY_ACCENT)
        except FileNotFoundError:
            console.print("Banner file not found", style=ERROR_COLOR)

    def create_layout(self) -> Layout:
        """
        Create a layout for the terminal UI.

        Returns:
            Layout: Rich layout object with defined sections.
        """
        layout = Layout()
        layout.split_column(
            Layout(name="top", size=7),
            Layout(name="middle"),
            Layout(name="bottom", size=3),
        )
        layout["top"].split_row(Layout(name="hashrate"), Layout(name="header"))
        layout["middle"].split_row(
            Layout(name="left_column"), Layout(name="right_column")
        )
        layout["left_column"].split_column(
            Layout(name="network"), Layout(name="chip"), Layout(name="power")
        )
        layout["right_column"].split_column(
            Layout(name="thermal"),
            Layout(name="mining_performance"),
            Layout(name="system"),
            Layout(name="display_fans"),
        )
        layout["bottom"].name = "log"
        return layout

    def update(
        self, system_info: Dict[str, Any], voltage: float, frequency: float
    ) -> None:
        """
        Update terminal UI with the latest miner data.

        Args:
            system_info (Dict[str, Any]): Current system information (e.g., {"hashRate": 500, "temp": 48}).
            voltage (float): Current target voltage setting (mV).
            frequency (float): Current target frequency setting (MHz).

        Example:
            >>> ui = RichTerminalUI()
            >>> ui.update({"hashRate": 500, "temp": 48}, 1200, 485)
        """
        try:
            if not self.has_data:
                console.clear()
                self.has_data = True

            # Handle hashrate display with unit conversion (hashRate in GH/s)
            hashrate = system_info.get("hashRate", 0)  # hashRate is in GH/s
            if hashrate > 999:  # Convert to Th/s when above 999 GH/s
                hashrate_ths = hashrate / 1000  # Convert GH/s to Th/s
                hashrate_str = f"{hashrate_ths:.2f} Th/s"  # Two decimal places for Th/s
            else:
                hashrate_str = (
                    f"{int(hashrate)} GH/s"  # For values <= 999, display in GH/s
                )
            ascii_art = pyfiglet.figlet_format(hashrate_str, font="ansi_regular")
            self.layout["hashrate"].update(
                Panel(ascii_art, title="Hashrate", border_style=PRIMARY_ACCENT)
            )

            # Header section
            header_table = Table(show_header=False, box=None)
            header_table.add_column("", style=DECORATIVE_COLOR, justify="right")
            header_table.add_column("", style=TEXT_COLOR)
            header_table.add_row("Hostname", system_info.get("hostname", "N/A"))
            header_table.add_row("Voltage", f"{int(voltage)}mV")
            header_table.add_row("Frequency", f"{int(frequency)}MHz")
            header_table.add_row("Temperature", f"{system_info.get('temp', 'N/A')}°C")
            header_table.add_row("Stratum User", system_info.get("stratumUser", "N/A"))
            header_table.add_row(
                "Backup User", system_info.get("fallbackStratumUser", "N/A")
            )
            self.layout["header"].update(Panel(header_table, title="System Status"))

            # Other sections (Network, Chip, Power, etc.)
            section_layouts = {
                "Network": "network",
                "Chip": "chip",
                "Power": "power",
                "Thermal": "thermal",
                "Mining Performance": "mining_performance",
                "System": "system",
                "Display & Fans": "display_fans",
            }
            for section_name, layout_name in section_layouts.items():
                table = Table(show_header=False, box=None)
                table.add_column("", style=DECORATIVE_COLOR)
                table.add_column("", style=TEXT_COLOR)
                for key in self.sections[section_name]:
                    if key in system_info:
                        value = system_info[key]
                        if key in ["stratumURL", "fallbackStratumURL"]:
                            port_key = (
                                "stratumPort"
                                if key == "stratumURL"
                                else "fallbackStratumPort"
                            )
                            value = f"{value}:{system_info.get(port_key, '')}"
                        elif isinstance(value, (int, float)):
                            value = f"{int(value)}"
                        table.add_row(key, str(value))
                self.layout[layout_name].update(Panel(table, title=section_name))

            # Log section
            status = (
                f"{time.strftime('%Y-%m-d %H:%M:%S')} - Voltage: {int(voltage)}mV, "
                f"Frequency: {int(frequency)}MHz, Hashrate: {hashrate_str}, "
                f"Temp: {system_info.get('temp', 'N/A')}°C"
            )
            self.log_messages.append(status)
            if len(self.log_messages) > 6:
                self.log_messages.pop(0)
            self.layout["log"].update(
                Panel(Text("\n".join(self.log_messages)), title="Log")
            )

        except Exception as e:
            console.print(f"[{ERROR_COLOR}]Error updating TUI: {e}[/]")

    def start(self) -> None:
        """Start the live display."""
        if not self._started:
            self.live.start()
            self._started = True

    def stop(self) -> None:
        """Stop the live display."""
        if self._started:
            self.live.stop()
            self._started = False
