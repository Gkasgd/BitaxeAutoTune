#!/usr/bin/env python3
"""
Bucle de tuning: coordina miner, estrategia, UI y persistencia.

TuningManager es el orquestador. En el arranque averigua el estado del miner,
decide que pools usar (los de la linea de comandos, los de la configuracion o
los mas rapidos medidos por latencia), los aplica y fija el voltaje y la
frecuencia iniciales. Despues entra en un bucle que cada sample_interval lee el
estado, pide a la estrategia el siguiente par voltaje/frecuencia, lo aplica y
registra la muestra en CSV, en el snapshot y en el servidor de metricas.

Uso:
    from tuning_manager import TuningManager

    manager = TuningManager(tuning_strategy=..., api_client=..., ...)
    manager.start_tuning()      # bucle bloqueante
    manager.stop_tuning()       # desde un signal handler

Dependencias:
    - Estandar: logging, sys, time, typing
"""

import logging
import sys
import time
from typing import Any, Dict, List, Optional, Union

from api_client import BitaxeAPIClient
from config import YamlConfigLoader
from logger import Logger
from metrics_server import update_metrics
from stratum import get_fastest_pools, parse_stratum_url
from tuning import PIDTuningStrategy
from ui_null import NullTerminalUI
from ui_rich import RichTerminalUI


class TuningManager:
    """Manages the tuning process for a Bitaxe miner, adjusting settings and stratum pools."""

    def __init__(
        self,
        tuning_strategy: PIDTuningStrategy,
        api_client: BitaxeAPIClient,
        logger: Logger,
        config_loader: YamlConfigLoader,
        terminal_ui: Union[RichTerminalUI, NullTerminalUI],
        sample_interval: float,
        initial_voltage: float,
        initial_frequency: float,
        pools_file: str,
        config: Dict[str, Any],
        user_file: Optional[str] = None,
        primary_stratum: Optional[Dict[str, Any]] = None,
        backup_stratum: Optional[Dict[str, Any]] = None,
        manage_pools: bool = False,
    ) -> None:
        """
        Initialize the TuningManager with tuning parameters and miner settings.

        Args:
            tuning_strategy (PIDTuningStrategy): Strategy for adjusting voltage/frequency.
            api_client (BitaxeAPIClient): API client for miner communication.
            logger (Logger): Logger for recording tuning data.
            config_loader (YamlConfigLoader): Loader for YAML configuration files.
            terminal_ui: UI for displaying tuning status (rich o nula).
            sample_interval (float): Interval between tuning adjustments (seconds).
            initial_voltage (float): Starting voltage in millivolts.
            initial_frequency (float): Starting frequency in MHz.
            pools_file (str): Path to the pools YAML file.
            config (Dict[str, Any]): Configuration dictionary from YAML.
            user_file (Optional[str]): Path to user YAML file, if provided.
            primary_stratum (Optional[Dict[str, Any]]): Primary stratum settings.
            backup_stratum (Optional[Dict[str, Any]]): Backup stratum settings.
            manage_pools (bool): Si es True, BitaxePID puede reconfigurar los
                pools stratum del miner y reiniciarlo. Por defecto False: se
                respeta la configuracion de pools que ya tenga el miner.
        """
        self.tuning_strategy = tuning_strategy
        self.api_client = api_client
        self.logger = logger
        self.config_loader = config_loader
        self.terminal_ui = terminal_ui
        self.sample_interval = sample_interval
        self.running = True
        self.target_voltage = initial_voltage
        self.target_frequency = initial_frequency
        self.pools_file = pools_file
        self.config = config
        self.user_file = user_file
        self.primary_stratum = primary_stratum
        self.backup_stratum = backup_stratum
        self.manage_pools = manage_pools
        # Se rellenan en connect_and_configure, cuando ya se ha hablado con el
        # miner. Se inicializan aqui para que el objeto no tenga atributos a
        # medias si alguien consulta antes de conectar.
        self.mac_address = "unknown"
        self.stratum_users: Dict[str, str] = {}
        logging.debug(f"User file set to: {self.user_file}")

    def connect_and_configure(self) -> None:
        """
        Hablar con el miner: leer su estado, aplicar los pools y fijar el
        voltaje y la frecuencia iniciales.

        Esto vivia en __init__. Se separa porque construir un objeto no deberia
        abrir conexiones, medir latencias contra pools de internet ni reiniciar
        el hardware: hacia imposible instanciar TuningManager en un test, y
        cualquier fallo de red se manifestaba como un constructor que llamaba a
        sys.exit(). Ahora el llamante decide cuando se toca el miner.

        Debe invocarse antes de start_tuning().
        """
        primary_stratum = self.primary_stratum
        backup_stratum = self.backup_stratum

        system_info = self.api_client.get_system_info()
        if system_info is None:
            logging.error("Failed to get system info from miner API")
            sys.exit(1)
        self.mac_address = system_info.get("macAddr", "unknown")  # Store MAC address

        if not self.manage_pools:
            logging.info(
                "Gestion de pools desactivada: se respeta la configuracion "
                "stratum del miner. Usa --manage-pools o MANAGE_MINER_POOLS "
                "para permitir que BitaxePID la cambie."
            )
            self._initialize_hardware()
            return

        current_stratum_user = system_info.get("stratumUser", "")
        current_fallback_user = system_info.get("fallbackStratumUser", "")
        logging.debug(
            f"Current stratum users from API: primary='{current_stratum_user}', backup='{current_fallback_user}'"
        )

        if not current_stratum_user:
            self.stratum_users = self._load_stratum_users()
            logging.debug(f"Loaded stratum users from file: {self.stratum_users}")
        else:
            logging.debug(
                "API system stratum user assumed correct once set; skipping user file load"
            )

        if primary_stratum:
            stratum_info = (
                [primary_stratum, backup_stratum]
                if backup_stratum
                else [primary_stratum, self._get_backup_pool()]
            )
        elif "PRIMARY_STRATUM" in self.config and "BACKUP_STRATUM" in self.config:
            stratum_info = self._parse_config_stratums()
        else:
            logging.debug(
                f"Measuring pools from {self.pools_file}"
            )  # Fixed typo: self.pools_file
            stratum_info = get_fastest_pools(
                yaml_file=self.pools_file,
                stratum_user=self.stratum_users.get("stratumUser", ""),
                fallback_stratum_user=self.stratum_users.get("fallbackStratumUser", ""),
                user_yaml=self.user_file,
                force_measure=True,
                latency_expiry_minutes=15,
            )
            if len(stratum_info) < 2:
                logging.error("Failed to get at least two valid pools")
                sys.exit(1)

        primary, backup = self._standardize_pools(stratum_info)
        self._apply_stratum_settings(
            primary, backup, current_stratum_user, current_fallback_user
        )
        self._initialize_hardware()

    def _get_backup_pool(self) -> Dict[str, Any]:
        """Fetch a backup pool via latency testing if not provided."""
        logging.info("Measuring backup pool latencies...")
        backup_pools = get_fastest_pools(
            yaml_file=self.pools_file,
            stratum_user=self.stratum_users.get("stratumUser", ""),
            fallback_stratum_user=self.stratum_users.get("fallbackStratumUser", ""),
            user_yaml=self.user_file,
            force_measure=True,
            latency_expiry_minutes=15,
        )
        if not backup_pools:
            logging.error("Failed to get a valid backup pool")
            sys.exit(1)
        return backup_pools[0]

    def _parse_config_stratums(self) -> List[Dict[str, Any]]:
        """Parse stratum URLs from config."""
        try:
            primary = parse_stratum_url(self.config["PRIMARY_STRATUM"])
            backup = parse_stratum_url(self.config["BACKUP_STRATUM"])
            return [primary, backup]
        except ValueError as e:
            logging.error(f"Invalid stratum URL in config: {e}")
            sys.exit(1)

    def _standardize_pools(
        self, stratum_info: List[Dict[str, Any]]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Standardize pool dictionaries and return primary/backup."""
        for pool in stratum_info:
            if "endpoint" in pool and "hostname" not in pool:
                parsed = parse_stratum_url(pool["endpoint"])
                pool["hostname"] = parsed["hostname"]
                pool["port"] = parsed["port"]
            if "hostname" not in pool or "port" not in pool:
                logging.error("Pool missing 'hostname' or 'port'")
                sys.exit(1)
            pool.pop("endpoint", None)
        return stratum_info[0], stratum_info[1]

    def _apply_stratum_settings(
        self,
        primary: Dict[str, Any],
        backup: Dict[str, Any],
        current_stratum_user: str,
        current_fallback_user: str,
    ) -> None:
        """Apply stratum settings to the miner."""
        primary["user"] = current_stratum_user or self.stratum_users.get(
            "stratumUser", ""
        )
        backup["user"] = current_fallback_user or self.stratum_users.get(
            "fallbackStratumUser", primary["user"]
        )
        if not primary["user"] or not backup["user"]:
            logging.error(
                f"Stratum users missing: Primary='{primary['user']}', Backup='{backup['user']}'"
            )
            sys.exit(1)

        logging.info(
            f"Setting primary stratum: {primary['hostname']}:{primary['port']} (user: {primary['user']})"
        )
        logging.info(
            f"Setting backup stratum: {backup['hostname']}:{backup['port']} (user: {backup['user']})"
        )
        if not self.api_client.set_stratum(primary, backup):
            logging.error("Failed to set stratum endpoints")
            sys.exit(1)
        logging.info("Stratum set, restarting miner...")
        if isinstance(self.terminal_ui, RichTerminalUI):
            self.terminal_ui.show_banner()
        time.sleep(1)
        self.api_client.restart()

    def _initialize_hardware(self) -> None:
        """Initialize miner hardware settings."""
        logging.info(
            f"Initializing hardware: Voltage={self.target_voltage}mV, Frequency={self.target_frequency}MHz"
        )
        self.api_client.set_settings(self.target_voltage, self.target_frequency)

    def _load_stratum_users(self) -> Dict[str, str]:
        """
        Load stratum users from user.yaml if available.

        Returns:
            Dict[str, str]: Dictionary with 'stratumUser' and 'fallbackStratumUser'.
        """
        if not self.user_file:
            return {}
        try:
            users = self.config_loader.load_config(self.user_file)
            return {
                "stratumUser": users.get("stratumUser", ""),
                "fallbackStratumUser": users.get("fallbackStratumUser", ""),
            }
        except Exception as e:
            logging.warning(f"Failed to load user.yaml: {e}")
            return {}

    def stop_tuning(self) -> None:
        """Stop the tuning process gracefully."""
        self.running = False
        if isinstance(self.terminal_ui, RichTerminalUI):
            self.terminal_ui.stop()
        print("\nTuning stopped gracefully")

    def start_tuning(self) -> None:
        """Start the tuning process, adjusting settings based on system info and exposing metrics if enabled."""
        try:
            if isinstance(self.terminal_ui, RichTerminalUI):
                self.terminal_ui.start()
            logging.info("Starting BitaxePID tuner...")
            while self.running:
                system_info = self.api_client.get_system_info()
                if not system_info:
                    time.sleep(1)
                    continue

                self.terminal_ui.update(
                    system_info, self.target_voltage, self.target_frequency
                )
                metrics = {
                    "mac_address": self.mac_address,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "target_frequency": self.target_frequency,
                    "target_voltage": self.target_voltage,
                    "hashrate": system_info.get("hashRate", 0),
                    "temp": system_info.get("temp", 0),
                    "pid_settings": self.config,
                    "power": system_info.get("power", 0),
                    "board_voltage": system_info.get("voltage", 0),
                    "current": system_info.get("current", 0),
                    "core_voltage_actual": system_info.get("coreVoltageActual", 0),
                    "frequency": system_info.get("frequency", 0),
                    "fanrpm": system_info.get("fanrpm", 0),
                }
                self.logger.log_to_csv(**metrics)
                if self.config.get("METRICS_SERVE", False):
                    update_metrics(self.mac_address, metrics)

                new_voltage, new_frequency = self.tuning_strategy.apply_strategy(
                    current_voltage=self.target_voltage,
                    current_frequency=self.target_frequency,
                    temp=system_info.get("temp", 0),
                    hashrate=system_info.get("hashRate", 0),
                    power=system_info.get("power", 0),
                )

                if (
                    new_voltage != self.target_voltage
                    or new_frequency != self.target_frequency
                ):
                    self.target_voltage = new_voltage
                    self.target_frequency = new_frequency
                    self.api_client.set_settings(
                        self.target_voltage, self.target_frequency
                    )
                    self.logger.save_snapshot(
                        self.target_voltage, self.target_frequency
                    )

                time.sleep(self.sample_interval)
        except KeyboardInterrupt:
            self.stop_tuning()
        except Exception as e:
            logging.error(f"Error in tuning loop: {e}")
            time.sleep(1)
        finally:
            if isinstance(self.terminal_ui, RichTerminalUI):
                self.terminal_ui.stop()
