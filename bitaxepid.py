#!/usr/bin/env python3
"""
BitaxePID Auto-Tuner Module

This module provides an automated tuning system for Bitaxe ASIC miners. It interfaces with the miner via an API,
adjusts voltage and frequency settings using a PID strategy, and optimizes stratum pool selection based on latency.
Configuration is loaded from YAML files, with command-line overrides for flexibility. The module supports both
console logging and a rich terminal UI for real-time monitoring, and optionally exposes metrics via an HTTP server
on port 8093 for Prometheus and Grafana dashboards when enabled via --serve-metrics or METRICS_SERVE config.

Por defecto NO toca la configuracion de pools stratum del miner: hay que
autorizarlo con --manage-pools o con MANAGE_MINER_POOLS en la configuracion.

Usage:
    python bitaxepid.py --ip <miner_ip> [--pools-file pools2.yaml] [--logging-level debug] [--serve-metrics] [--manage-pools]

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
from config import YamlConfigLoader, load_config, opcional, validate_config
from logger import Logger
from metrics_server import start_metrics_server
from stratum import parse_stratum_url
from tuning import PIDTuningStrategy
from tuning_estabilidad import EstabilidadTuningStrategy
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

    # Los defectos de las claves opcionales viven en config.CLAVES_OPCIONALES,
    # no repetidos aqui: tenerlos en dos sitios permitia que el YAML documentara
    # un numero y el codigo aplicara otro.
    serve_metrics = args.serve_metrics or opcional(config, "METRICS_SERVE")
    config["METRICS_SERVE"] = serve_metrics
    manage_pools = args.manage_pools or opcional(config, "MANAGE_MINER_POOLS")
    config["MANAGE_MINER_POOLS"] = manage_pools

    logger_instance = Logger(config["LOG_FILE"], config["SNAPSHOT_FILE"])

    # Dos estrategias posibles. La de estabilidad se activa con
    # ERROR_TUNING: TRUE y necesita ERROR_TARGET_PERCENT; entonces el hashrate
    # deja de ser un objetivo y las decisiones las toman la temperatura y el
    # porcentaje de errores de hardware del miner. Por defecto sigue la
    # estrategia PID de siempre, para no cambiar el comportamiento de nadie que
    # no lo pida explicitamente.
    if opcional(config, "ERROR_TUNING"):
        if "ERROR_TARGET_PERCENT" not in config:
            logging.error(
                "ERROR_TUNING esta activado pero falta ERROR_TARGET_PERCENT: "
                "sin objetivo de errores la estrategia no puede decidir"
            )
            api_client.close()
            sys.exit(1)
        tuning_strategy = EstabilidadTuningStrategy(
            min_voltage=config["MIN_VOLTAGE"],
            max_voltage=config["MAX_VOLTAGE"],
            min_frequency=config["MIN_FREQUENCY"],
            max_frequency=config["MAX_FREQUENCY"],
            voltage_step=config["VOLTAGE_STEP"],
            frequency_step=config["FREQUENCY_STEP"],
            target_temp=config["TARGET_TEMP"],
            power_limit=config["POWER_LIMIT"],
            error_target=config["ERROR_TARGET_PERCENT"],
            error_hysteresis=opcional(config, "ERROR_HYSTERESIS"),
            error_window=opcional(config, "ERROR_WINDOW"),
            error_settle=opcional(config, "ERROR_SETTLE"),
            temp_margin=opcional(config, "TEMP_MARGIN"),
            retry_ceiling=opcional(config, "ERROR_RETRY_CEILING"),
            lower_voltage_after=opcional(config, "LOWER_VOLTAGE_AFTER"),
        )
        logging.info(
            f"Estrategia de estabilidad: objetivo {config['ERROR_TARGET_PERCENT']}% "
            f"de errores de hardware, temperatura objetivo {config['TARGET_TEMP']}C. "
            f"El hashrate no interviene en las decisiones."
        )
    else:
        # Las ganancias PID_* y HASHRATE_SETPOINT ya no se pasan: no hay PID ni
        # objetivo de hashrate. Se siguen exigiendo en los YAML de ESTA rama
        # (validate_config las pide cuando ERROR_TUNING esta desactivado) para no
        # invalidar los ficheros existentes ni dejar huecos en las columnas del
        # CSV con las que se comparan historiales antiguos.
        tuning_strategy = PIDTuningStrategy(
            min_voltage=config["MIN_VOLTAGE"],
            max_voltage=config["MAX_VOLTAGE"],
            min_frequency=config["MIN_FREQUENCY"],
            max_frequency=config["MAX_FREQUENCY"],
            voltage_step=config["VOLTAGE_STEP"],
            frequency_step=config["FREQUENCY_STEP"],
            target_temp=config["TARGET_TEMP"],
            power_limit=config["POWER_LIMIT"],
            temp_margin=opcional(config, "TEMP_MARGIN"),
            # ERROR_TARGET_PERCENT es opcional aqui (a diferencia de la
            # estrategia de estabilidad, que sin el no puede decidir nada). Si
            # no esta, esta estrategia decide solo con temperatura y potencia.
            # No lleva defecto en CLAVES_OPCIONALES a proposito: su ausencia
            # significa "sin criterio de errores", no un numero concreto.
            error_target=config.get("ERROR_TARGET_PERCENT"),
            error_hysteresis=opcional(config, "ERROR_HYSTERESIS"),
            estable_para_bajar=opcional(config, "ERROR_SETTLE"),
        )
        logging.info(
            f"Estrategia por limites: temperatura objetivo {config['TARGET_TEMP']}C, "
            f"limite {config['POWER_LIMIT']}W, objetivo de errores "
            f"{config.get('ERROR_TARGET_PERCENT', 'sin definir')}. "
            f"El hashrate no interviene en las decisiones."
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
        user_file=args.user_file if args.user_file else opcional(config, "USER_FILE"),
        primary_stratum=primary_stratum,
        backup_stratum=backup_stratum,
        manage_pools=manage_pools,
    )
    tuning_manager.connect_and_configure()

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
