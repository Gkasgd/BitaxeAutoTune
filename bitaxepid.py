#!/usr/bin/env python3
"""
BitaxePID Auto-Tuner Module

This module provides an automated tuning system for Bitaxe ASIC miners. It interfaces with the miner via an API,
adjusts voltage and frequency settings using a PID strategy, and optimizes stratum pool selection based on latency.
Configuration is loaded from YAML files, with command-line overrides for flexibility. The module supports both
console logging and a rich terminal UI for real-time monitoring, and optionally exposes metrics via an HTTP server
on port 8093 for Prometheus and Grafana dashboards when enabled via --serve-metrics or METRICS_SERVE config.

Usage:
    python bitaxepid.py --ip <miner_ip> [--pools-file pools2.yaml] [--logging-level debug] [--serve-metrics]

Dependencies:
    - Terceros: rich, pyyaml, simple_pid, pyfiglet, urllib3
    - Estandar: logging, signal, sys, typing
"""

import logging
import signal
import sys
from typing import Any

from api_client import BitaxeAPIClient
from cli import parse_arguments
from config import YamlConfigLoader, load_config, validate_config
from logger import Logger
from metrics_server import start_metrics_server
from stratum import parse_stratum_url
from tuning import PIDTuningStrategy
from tuning_manager import TuningManager
from ui_null import NullTerminalUI
from ui_rich import RichTerminalUI


def main() -> None:
    args = parse_arguments()
    handlers = [logging.FileHandler("bitaxepid_monitor.log")]
    if args.log_to_console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if args.logging_level == "debug" else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )

    # Initialize the API client with enhanced settings
    api_client = BitaxeAPIClient(
        ip=args.ip,
        timeout=10,  # Longer timeout to avoid ConnectTimeoutError
        retries=5,  # More retries for resilience
        pool_maxsize=10,  # Connection pooling
    )

    system_info = api_client.get_system_info()
    if system_info is None:
        logging.error("Failed to fetch system info from API")
        api_client.close()
        sys.exit(1)

    asic_model = system_info.get("ASICModel", "default")
    asic_yaml = f"{asic_model}.yaml"
    config_loader = YamlConfigLoader()
    config = load_config(config_loader, asic_yaml, args.config)

    # Apply overrides (unchanged)
    if args.voltage is not None:
        config["INITIAL_VOLTAGE"] = args.voltage
    if args.frequency is not None:
        config["INITIAL_FREQUENCY"] = args.frequency
    if args.sample_interval is not None:
        config["SAMPLE_INTERVAL"] = args.sample_interval
    validate_config(config)

    serve_metrics = args.serve_metrics or config.get("METRICS_SERVE", False)
    config["METRICS_SERVE"] = serve_metrics

    logger_instance = Logger(config["LOG_FILE"], config["SNAPSHOT_FILE"])
    tuning_strategy = PIDTuningStrategy(
        kp_freq=config["PID_FREQ_KP"],
        ki_freq=config["PID_FREQ_KI"],
        kd_freq=config["PID_FREQ_KD"],
        kp_volt=config["PID_VOLT_KP"],
        ki_volt=config["PID_VOLT_KI"],
        kd_volt=config["PID_VOLT_KD"],
        min_voltage=config["MIN_VOLTAGE"],
        max_voltage=config["MAX_VOLTAGE"],
        min_frequency=config["MIN_FREQUENCY"],
        max_frequency=config["MAX_FREQUENCY"],
        voltage_step=config["VOLTAGE_STEP"],
        frequency_step=config["FREQUENCY_STEP"],
        setpoint=config["HASHRATE_SETPOINT"],
        sample_interval=config["SAMPLE_INTERVAL"],
        target_temp=config["TARGET_TEMP"],
        power_limit=config["POWER_LIMIT"],
    )
    terminal_ui = NullTerminalUI() if args.log_to_console else RichTerminalUI()

    primary_stratum = (
        parse_stratum_url(args.primary_stratum) if args.primary_stratum else None
    )
    if primary_stratum and args.stratum_user:
        primary_stratum["user"] = args.stratum_user
    backup_stratum = (
        parse_stratum_url(args.backup_stratum) if args.backup_stratum else None
    )
    if backup_stratum and args.fallback_stratum_user:
        backup_stratum["user"] = args.fallback_stratum_user

    tuning_manager = TuningManager(
        tuning_strategy=tuning_strategy,
        api_client=api_client,
        logger=logger_instance,
        config_loader=config_loader,
        terminal_ui=terminal_ui,
        sample_interval=config["SAMPLE_INTERVAL"],
        initial_voltage=config["INITIAL_VOLTAGE"],
        initial_frequency=config["INITIAL_FREQUENCY"],
        pools_file=args.pools_file if args.pools_file else config["POOLS_FILE"],
        config=config,
        user_file=args.user_file if args.user_file else config.get("USER_FILE", None),
        primary_stratum=primary_stratum,
        backup_stratum=backup_stratum,
    )

    def signal_handler(sig: int, frame: Any) -> None:
        logging.info("Shutting down gracefully...")
        tuning_manager.stop_tuning()
        api_client.close()  # Clean up the connection pool
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if serve_metrics:
        start_metrics_server()
    logging.info("Starting BitaxePID tuner...")
    tuning_manager.start_tuning()


if __name__ == "__main__":
    main()
