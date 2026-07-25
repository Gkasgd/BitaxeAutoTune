#!/usr/bin/env python3
"""
Persistencia de los datos de tuning: CSV historico y snapshot JSON.

El CSV acumula una fila por muestra (metricas medidas del miner mas los
parametros PID vigentes) y sirve de historico para analisis posterior. El
snapshot guarda solo el ultimo voltaje y frecuencia aplicados, para poder
retomar el tuning donde se dejo tras un reinicio.

Uso:
    from logger import Logger

    logger_instance = Logger("tuning.csv", "snapshot.json")
    logger_instance.log_to_csv(mac_address=..., timestamp=..., ...)
    logger_instance.save_snapshot(voltage=1200, frequency=485)

Dependencias:
    - Estandar: csv, json, logging, os, typing
"""

import csv
import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


class Logger:
    """Concrete implementation for logging miner data to CSV and snapshots to JSON."""

    def __init__(self, log_file: str, snapshot_file: str) -> None:
        """
        Initialize the logger with file paths.

        Args:
            log_file (str): Path to the CSV log file (e.g., "bitaxepid_tuning_log.csv").
            snapshot_file (str): Path to the JSON snapshot file (e.g., "bitaxepid_snapshot.json").
        """
        self.log_file = log_file
        self.snapshot_file = snapshot_file
        self._initialize_csv()

    def _initialize_csv(self) -> None:
        """Initialize the CSV file with an alphabetized header row (MAC address first) if it doesn't exist."""
        if not os.path.exists(self.log_file):
            headers = [
                "mac_address",
                "timestamp",
                "target_frequency",
                "target_voltage",
                "hashrate",
                "temp",
                "power",
                "board_voltage",
                "current",
                "core_voltage_actual",
                "frequency",
                "fanrpm",
                "pid_freq_kp",
                "pid_freq_ki",
                "pid_freq_kd",
                "pid_volt_kp",
                "pid_volt_ki",
                "pid_volt_kd",
                "initial_frequency",
                "min_frequency",
                "max_frequency",
                "initial_voltage",
                "min_voltage",
                "max_voltage",
                "frequency_step",
                "voltage_step",
                "target_temp",
                "sample_interval",
                "power_limit",
                "hashrate_setpoint",
            ]
            with open(self.log_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)

    def log_to_csv(
        self,
        mac_address: str,
        timestamp: str,
        target_frequency: float,
        target_voltage: float,
        hashrate: float,
        temp: float,
        pid_settings: Dict[str, Any],
        power: float,
        board_voltage: float,
        current: float,
        core_voltage_actual: float,
        frequency: float,
        fanrpm: int,
    ) -> None:
        """
        Log miner performance data, including flattened PID settings and MAC address, to a CSV file.

        Args:
            mac_address (str): MAC address of the miner.
            timestamp (str): Time of the data point (e.g., "2025-03-11 10:00:00").
            target_frequency (float): Target frequency commanded by PID (MHz).
            target_voltage (float): Target core voltage commanded by PID (mV).
            hashrate (float): Measured hashrate (GH/s).
            temp (float): Measured temperature (°C).
            pid_settings (Dict[str, Any]): PID controller settings (e.g., {"PID_FREQ_KP": 0.2, "PID_VOLT_KI": 0.01}).
            power (float): Measured power consumption (W).
            board_voltage (float): Measured board voltage (mV).
            current (float): Measured current (mA).
            core_voltage_actual (float): Actual core voltage (mV).
            frequency (float): Actual frequency (MHz).
            fanrpm (int): Fan speed (RPM).
        """
        with open(self.log_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    mac_address,
                    timestamp,
                    target_frequency,
                    target_voltage,
                    hashrate,
                    temp,
                    power,
                    board_voltage,
                    current,
                    core_voltage_actual,
                    frequency,
                    fanrpm,
                    pid_settings.get("PID_FREQ_KP", ""),
                    pid_settings.get("PID_FREQ_KI", ""),
                    pid_settings.get("PID_FREQ_KD", ""),
                    pid_settings.get("PID_VOLT_KP", ""),
                    pid_settings.get("PID_VOLT_KI", ""),
                    pid_settings.get("PID_VOLT_KD", ""),
                    pid_settings.get("INITIAL_FREQUENCY", ""),
                    pid_settings.get("MIN_FREQUENCY", ""),
                    pid_settings.get("MAX_FREQUENCY", ""),
                    pid_settings.get("INITIAL_VOLTAGE", ""),
                    pid_settings.get("MIN_VOLTAGE", ""),
                    pid_settings.get("MAX_VOLTAGE", ""),
                    pid_settings.get("FREQUENCY_STEP", ""),
                    pid_settings.get("VOLTAGE_STEP", ""),
                    pid_settings.get("TARGET_TEMP", ""),
                    pid_settings.get("SAMPLE_INTERVAL", ""),
                    pid_settings.get("POWER_LIMIT", ""),
                    pid_settings.get("HASHRATE_SETPOINT", ""),
                ]
            )

    def save_snapshot(self, voltage: float, frequency: float) -> None:
        """
        Save current miner settings as a snapshot to a JSON file.

        Args:
            voltage (float): Current target voltage setting (mV).
            frequency (float): Current target frequency setting (MHz).
        """
        snapshot = {"voltage": voltage, "frequency": frequency}
        try:
            with open(self.snapshot_file, "w") as f:
                json.dump(snapshot, f)
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")
