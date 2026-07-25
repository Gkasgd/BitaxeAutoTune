#!/usr/bin/env python3
"""
Carga y validacion de la configuracion de BitaxePID.

La configuracion se compone en dos capas: el YAML del modelo de ASIC
(BM1366.yaml, BM1370.yaml...) con los parametros PID y los limites de
voltaje y frecuencia de ese chip, y opcionalmente un YAML de usuario que
sobreescribe claves concretas. Las opciones de linea de comandos se aplican
encima de todo eso, en cli.py.

Uso:
    from config import YamlConfigLoader, load_config, validate_config

    config = load_config(YamlConfigLoader(), "BM1366.yaml", "mi_config.yaml")
    validate_config(config)   # termina el proceso si falta alguna clave

Dependencias:
    - Terceros: pyyaml
    - Estandar: logging, os, sys, typing
"""

import logging
import os
import sys
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class YamlConfigLoader:
    """Concrete implementation for loading YAML configuration files."""

    def load_config(self, file_path: str) -> Dict[str, Any]:
        """
        Load configuration settings from a YAML file.

        Args:
            file_path (str): Path to the configuration file (e.g., "BM1366.yaml").

        Returns:
            Dict[str, Any]: Configuration data as a dictionary (e.g., {"INITIAL_VOLTAGE": 1200}), empty if loading fails.

        Example:
            >>> loader = YamlConfigLoader()
            >>> config = loader.load_config("BM1366.yaml")
            >>> config["INITIAL_VOLTAGE"]
            1200
        """
        try:
            with open(file_path, "r") as f:
                config = yaml.safe_load(f)
                if config is None:
                    raise ValueError("YAML file is empty")
                return config
        except Exception as e:
            logger.error(f"Failed to load configuration file {file_path}: {e}")
            return {}


def load_config(
    config_loader: YamlConfigLoader, asic_yaml: str, user_config_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load and merge configurations from ASIC model YAML and optional user config.

    Args:
        config_loader (YamlConfigLoader): Loader for YAML files.
        asic_yaml (str): Path to ASIC model YAML file.
        user_config_path (Optional[str]): Path to optional user config YAML.

    Returns:
        Dict[str, Any]: Merged configuration dictionary.
    """
    if not os.path.exists(asic_yaml):
        logger.error(f"ASIC model YAML file {asic_yaml} not found")
        sys.exit(1)
    config = config_loader.load_config(asic_yaml)
    if user_config_path and os.path.exists(user_config_path):
        user_config = config_loader.load_config(user_config_path)
        config.update(user_config)
    return config


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate that required configuration keys are present.

    Args:
        config (Dict[str, Any]): Configuration dictionary to validate.

    Raises:
        SystemExit: If required keys are missing.
    """
    required_keys = [
        "INITIAL_VOLTAGE",
        "INITIAL_FREQUENCY",
        "SAMPLE_INTERVAL",
        "LOG_FILE",
        "SNAPSHOT_FILE",
        "POOLS_FILE",
        "PID_FREQ_KP",
        "PID_FREQ_KI",
        "PID_FREQ_KD",
        "PID_VOLT_KP",
        "PID_VOLT_KI",
        "PID_VOLT_KD",
        "MIN_VOLTAGE",
        "MAX_VOLTAGE",
        "MIN_FREQUENCY",
        "MAX_FREQUENCY",
        "VOLTAGE_STEP",
        "FREQUENCY_STEP",
        "HASHRATE_SETPOINT",
        "TARGET_TEMP",
        "POWER_LIMIT",
    ]
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        logger.error(f"Missing required config keys: {', '.join(missing_keys)}")
        sys.exit(1)
