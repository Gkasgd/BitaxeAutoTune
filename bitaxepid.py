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
    - Terceros: rich, pyyaml, pyfiglet, urllib3
    - Estandar: logging, signal, sys, typing
"""

import logging
import signal
import sys
from typing import Any

from api_client import BitaxeAPIClient
from cli import parse_arguments
from config import (
    YamlConfigLoader,
    imprimir_configuracion_efectiva,
    load_config_con_procedencia,
    opcional,
    registrar_procedencia,
    ruta_yaml_de_chip,
    validate_config,
)
from logger import Logger
from metrics_server import start_metrics_server
from stratum import parse_stratum_url
from tuning import PIDTuningStrategy
from tuning_estabilidad import EstabilidadTuningStrategy
from tuning_manager import TuningManager
from ui_null import NullTerminalUI
from ui_rich import RichTerminalUI


def preparar_configuracion(args: Any, asic_model: str) -> Any:
    """
    Cargar, fusionar, validar y registrar la configuracion de un modelo de chip.

    Extraido de `main()` para que `--dry-run` recorra exactamente el mismo
    camino: si validara por otro lado, un dry-run en verde no diria nada del
    arranque de verdad, que es lo unico para lo que sirve.

    Args:
        args (Any): Argumentos ya parseados (usa config, voltage, frequency,
            sample_interval).
        asic_model (str): Modelo de ASIC, del miner o de --asic.

    Returns:
        Tuple[Dict[str, Any], Dict[str, str]]: configuracion efectiva y la
            procedencia de cada clave.

    Raises:
        SystemExit: Si falta un YAML o la configuracion no es valida.
    """
    asic_yaml = ruta_yaml_de_chip(asic_model)
    config_loader = YamlConfigLoader()
    config, procedencia = load_config_con_procedencia(
        config_loader, asic_yaml, args.config
    )
    registrar_procedencia(procedencia, asic_yaml, args.config)

    # Apply overrides. Se anota la procedencia de cada uno: sin esto la tabla de
    # --dry-run atribuia al YAML un valor que venia de la linea de comandos, que
    # es exactamente la confusion que la tabla existe para deshacer.
    for opcion, clave, valor in (
        ("--voltage", "INITIAL_VOLTAGE", args.voltage),
        ("--frequency", "INITIAL_FREQUENCY", args.frequency),
        ("--sample-interval", "SAMPLE_INTERVAL", args.sample_interval),
    ):
        if valor is not None:
            config[clave] = valor
            procedencia[clave] = f"{opcion} (linea de comandos)"

    # validate_config recorta INITIAL_VOLTAGE e INITIAL_FREQUENCY al rango, y ese
    # recorte es un tercer origen del valor: no lo escribio ningun YAML ni ningun
    # argumento. Se detecta comparando, en vez de que clamp_initial_values
    # devuelva la procedencia, para no cambiar la firma de una funcion que
    # llaman los tests de limites.
    antes = {k: config.get(k) for k in ("INITIAL_VOLTAGE", "INITIAL_FREQUENCY")}
    validate_config(config)
    for clave, valor_previo in antes.items():
        if config.get(clave) != valor_previo:
            procedencia[clave] = (
                f"recortado al rango (se pidio {valor_previo}, "
                f"ver {procedencia.get(clave, asic_yaml)})"
            )
    return config, procedencia


def main() -> None:
    args = parse_arguments()
    handlers = [logging.FileHandler("bitaxepid_monitor.log")]
    # En --dry-run el log va tambien a la terminal sin pedirlo: todo el modo
    # existe para mostrar lo que se cargaria, y los avisos de claves ausentes o
    # recortadas son parte de eso. Escondidos en el fichero no sirven de nada.
    if args.log_to_console or args.dry_run:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if args.logging_level == "debug" else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )

    # --dry-run sale ANTES de construir el cliente de la API. El orden no es
    # cosmetico: BitaxeAPIClient abre la sesion HTTP en su constructor, asi que
    # crearlo y salir despues ya habria hecho lo que este modo promete no hacer.
    if args.dry_run:
        config, procedencia = preparar_configuracion(args, args.asic)
        imprimir_configuracion_efectiva(config, procedencia)
        sys.exit(0)

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
    config, _procedencia = preparar_configuracion(args, asic_model)

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
        # Instancia propia: YamlConfigLoader no tiene estado (es un open() y un
        # yaml.safe_load()), asi que compartir la que usa la carga inicial no
        # aportaba nada. TuningManager lo usa para releer pools.yaml y user.yaml.
        config_loader=YamlConfigLoader(),
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
