#!/usr/bin/env python3
"""
Implementations Module for BitaxePID Auto-Tuner

This module provides concrete implementations of the interfaces defined in `interfaces.py` for the BitaxePID
auto-tuner. It includes the rich terminal UI, su equivalente silencioso y la
estrategia de tuning PID.

El cliente de la API vive en api_client.py; la persistencia en CSV y JSON, en
logger.py; la carga de configuracion, en config.py.

Usage:
    >>> from implementations import PIDTuningStrategy
    >>> strategy = PIDTuningStrategy(...)

Dependencies:
    - Terceros: simple_pid, rich, pyfiglet
    - Estandar: time, typing
"""

import time
from typing import Dict, Any, Optional, Tuple
from interfaces import (
    ITerminalUI,
    TuningStrategy,
)
from simple_pid import PID
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live
import pyfiglet

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


class NullTerminalUI(ITerminalUI):
    """Null implementation of the terminal UI for console-only logging."""

    def update(
        self, system_info: Dict[str, Any], voltage: float, frequency: float
    ) -> None:
        """
        Do nothing (placeholder for UI updates).

        Args:
            system_info (Dict[str, Any]): Current system information (ignored).
            voltage (float): Current target voltage setting (mV, ignored).
            frequency (float): Current target frequency setting (MHz, ignored).
        """
        pass


class PIDTuningStrategy(TuningStrategy):
    """Concrete implementation of a PID-based tuning strategy for miner settings."""

    def __init__(
        self,
        kp_freq: float,
        ki_freq: float,
        kd_freq: float,
        kp_volt: float,
        ki_volt: float,
        kd_volt: float,
        min_voltage: float,
        max_voltage: float,
        min_frequency: float,
        max_frequency: float,
        voltage_step: float,
        frequency_step: float,
        setpoint: float,
        sample_interval: float,
        target_temp: float,
        power_limit: float,
    ) -> None:
        """
        Initialize the PID tuning strategy with control parameters.
        Args:
            kp_freq (float): Proportional gain for frequency PID.
            ki_freq (float): Integral gain for frequency PID.
            kd_freq (float): Derivative gain for frequency PID.
            kp_volt (float): Proportional gain for voltage PID.
            ki_volt (float): Integral gain for voltage PID.
            kd_volt (float): Derivative gain for voltage PID.
            min_voltage (float): Minimum allowed voltage (mV).
            max_voltage (float): Maximum allowed voltage (mV).
            min_frequency (float): Minimum allowed frequency (MHz).
            max_frequency (float): Maximum allowed frequency (MHz).
            voltage_step (float): Voltage adjustment step size (mV).
            frequency_step (float): Frequency adjustment step size (MHz).
            setpoint (float): Target hashrate setpoint (GH/s).
            sample_interval (float): PID sample interval (seconds).
            target_temp (float): Target temperature (°C).
            power_limit (float): Power limit (W).
        """
        self.pid_freq = PID(
            kp_freq, ki_freq, kd_freq, setpoint=setpoint, sample_time=sample_interval
        )
        self.pid_volt = PID(
            kp_volt, ki_volt, kd_volt, setpoint=setpoint, sample_time=sample_interval
        )
        self.pid_freq.output_limits = (min_frequency, max_frequency)
        self.pid_volt.output_limits = (min_voltage, max_voltage)
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.min_frequency = min_frequency
        self.max_frequency = max_frequency
        self.voltage_step = voltage_step
        self.frequency_step = frequency_step
        self.target_temp = target_temp
        self.power_limit = power_limit
        self.last_hashrate: Optional[float] = None
        self.stagnation_count = 0
        # Removed drop_count since we're not tracking hashrate drops anymore, this was an overall network factor and not addressable in the hardware.

    def apply_strategy(
        self,
        current_voltage: float,
        current_frequency: float,
        temp: float,
        hashrate: float,
        power: float,
    ) -> Tuple[float, float]:
        """
        Calculate new voltage and frequency settings based on the current miner status.
        Uses PID to maintain hashrate setpoint and reduces frequency to control temperature.
        """
        # Calculate PID outputs
        freq_output = self.pid_freq(hashrate)
        volt_output = self.pid_volt(hashrate)
        proposed_frequency = (
            round(freq_output / self.frequency_step) * self.frequency_step
        )
        proposed_frequency = max(
            self.min_frequency, min(self.max_frequency, proposed_frequency)
        )
        proposed_voltage = round(volt_output / self.voltage_step) * self.voltage_step
        proposed_voltage = max(
            self.min_voltage, min(self.max_voltage, proposed_voltage)
        )

        # Track hashrate stagnation but not drops
        stagnated = self.last_hashrate == hashrate
        self.stagnation_count = self.stagnation_count + 1 if stagnated else 0

        new_voltage = current_voltage
        new_frequency = current_frequency

        # Temperature control - reduce frequency first, then voltage if needed
        if temp > self.target_temp:
            if current_frequency > self.min_frequency:
                new_frequency = current_frequency - self.frequency_step
                console.print(
                    f"[{WARNING_COLOR}]Reducing frequency to {new_frequency}MHz due to temp {temp}°C > {self.target_temp}°C[/]"
                )
            elif current_voltage > self.min_voltage:
                new_voltage = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Reducing voltage to {new_voltage}mV due to temp {temp}°C > {self.target_temp}°C[/]"
                )
        # Power limit control
        elif power > self.power_limit * 1.075:
            if current_voltage > self.min_voltage:
                new_voltage = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Reducing voltage to {new_voltage}mV due to power {power}W > {self.power_limit * 1.075}W[/]"
                )
        # Hashrate control using PID
        elif hashrate < self.pid_freq.setpoint:
            # If hashrate is significantly low, try increasing voltage first
            if (
                hashrate < 0.85 * self.pid_freq.setpoint
                and current_voltage < self.max_voltage
            ):
                new_voltage = min(proposed_voltage, current_voltage + self.voltage_step)
                console.print(
                    f"[{SECONDARY_ACCENT}]Increasing voltage to {new_voltage}mV due to hashrate {hashrate} < {0.85 * self.pid_freq.setpoint}[/]"
                )
            # Apply PID-calculated frequency
            new_frequency = proposed_frequency
            console.print(
                f"[{SECONDARY_ACCENT}]Adjusting frequency to {new_frequency}MHz via PID[/]"
            )
            # If at max frequency but still below setpoint, increase voltage
            if (
                current_frequency >= self.max_frequency
                and current_voltage < self.max_voltage
            ):
                new_voltage = current_voltage + self.voltage_step
                console.print(
                    f"[{SECONDARY_ACCENT}]Increasing voltage to {new_voltage}mV as frequency at max[/]"
                )
        else:
            console.print(
                f"[{PRIMARY_ACCENT}]System stable at Voltage={current_voltage}mV, Frequency={new_frequency}MHz[/]"
            )

        self.last_hashrate = hashrate
        return new_voltage, new_frequency
