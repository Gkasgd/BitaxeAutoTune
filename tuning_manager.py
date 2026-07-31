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
from config import YamlConfigLoader, opcional
from logger import Logger
from metrics_server import update_metrics
from stratum import get_fastest_pools, parse_stratum_url
from tuning import PIDTuningStrategy
from tuning_estabilidad import EstabilidadTuningStrategy
from ui_null import NullTerminalUI
from ui_rich import RichTerminalUI


def _a_rejilla(valor: Any, paso: Any) -> Any:
    """Redondear `valor` al multiplo de `paso` mas cercano, como entero.

    Voltaje y frecuencia son magnitudes que se escriben en el hardware, y todos
    los YAML las declaran como enteros. Un valor con decimales no viene de la
    configuracion: viene de fuera (la web de AxeOS, un --frequency con coma, o el
    reloj efectivo que reporta el firmware). Si se adopta sin cuantizar, la
    estrategia le suma pasos enteros y el desfase no se corrige nunca.

    Sin paso valido se limita a redondear a entero: es siempre mejor que arrastrar
    decimales. Si el valor no es un numero se devuelve tal cual y lo rechaza quien
    lo use, en vez de romper aqui el bucle de tuning.
    """
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return valor
    try:
        p = float(paso)
    except (TypeError, ValueError):
        p = 0.0
    if p <= 0:
        return int(round(v))
    return int(round(v / p) * p)


class TuningManager:
    """Manages the tuning process for a Bitaxe miner, adjusting settings and stratum pools."""

    def __init__(
        self,
        tuning_strategy: Union[PIDTuningStrategy, EstabilidadTuningStrategy],
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
            # El mensaje decia solo que faltaban, no de donde salen ni que hacer.
            # Se llega aqui cuando el miner reporta stratumUser vacio y el
            # user.yaml tampoco lo trae, que es el estado por defecto del
            # repositorio a proposito: antes venia con una direccion del proyecto
            # original y el hashrate se habria ido a un tercero.
            logging.error(
                f"Stratum users missing: Primary='{primary['user']}', "
                f"Backup='{backup['user']}'. Con --manage-pools hay que dar una "
                f"direccion de pago: ponla en {self.user_file} (las dos claves, "
                "stratumUser y fallbackStratumUser), o en el propio miner desde "
                "AxeOS, o con --stratum-user. Sin usuario el miner no mina, asi "
                "que no se aplica nada y se sale."
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

    def _adoptar_ajuste_externo(self, system_info: Dict[str, Any]) -> None:
        """
        Si el miner tiene otro voltaje o frecuencia de los que creemos, adoptarlo.

        El usuario puede cambiar voltaje y frecuencia desde la web de AxeOS sin
        pasar por el tuner. Hasta ahora el bucle decidia siempre sobre sus propias
        variables y no volvia a mirar el miner, asi que el errorPercentage medido
        correspondia al ajuste DEL USUARIO mientras la decision se aplicaba sobre
        el ajuste DEL PROGRAMA: los dos lados de la ecuacion dejaban de
        corresponder.

        Se adopta el valor del usuario y se sigue optimizando desde ahi, en vez de
        reimponer el propio. La temperatura sigue mandando: es la rama de mayor
        prioridad de la estrategia y no consulta la ventana de errores, asi que un
        ajuste externo que caliente demasiado se corrige en la muestra siguiente
        sin necesidad de nada especial aqui.

        Se invalida la ventana porque lo medido antes describe otro ajuste.

        El valor que devuelve AxeOS se cuantiza a la rejilla de FREQUENCY_STEP y
        VOLTAGE_STEP antes de adoptarlo. Si se adopta tal cual y trae decimales
        (493.75, porque la web permite valores libres o porque el firmware
        reporta el reloj efectivo y no el pedido), la estrategia suma y resta
        pasos enteros sobre esa base y el ajuste se queda fuera de rejilla para
        todo lo que reste de ejecucion: 493.75, 498.75, 503.75... Ninguno de esos
        valores es uno que el usuario haya configurado ni que se pueda comparar
        con los limites de forma limpia.
        """
        real_v = system_info.get("coreVoltage")
        real_f = system_info.get("frequency")
        if real_v is None or real_f is None:
            return
        real_v = _a_rejilla(real_v, self.config.get("VOLTAGE_STEP"))
        real_f = _a_rejilla(real_f, self.config.get("FREQUENCY_STEP"))
        # Margen de 1 unidad: el miner redondea y no conviene disparar esto por
        # un decimal de diferencia.
        if abs(real_v - self.target_voltage) < 1 and abs(real_f - self.target_frequency) < 1:
            return
        logging.info(
            f"Ajuste cambiado fuera del tuner: el miner esta en {real_v}mV/"
            f"{real_f}MHz y no en {self.target_voltage}mV/{self.target_frequency}MHz. "
            f"Se adopta y se sigue optimizando desde ahi."
        )
        self.target_voltage = real_v
        self.target_frequency = real_f
        self.tuning_strategy.ajuste_cambiado_fuera()

    def _initialize_hardware(self) -> None:
        """
        Initialize miner hardware settings.

        Un fallo aqui no aborta: el miner sigue con el ajuste que ya tenia, que
        es un punto de partida valido, y el bucle empieza a decidir desde ahi en
        cuanto la primera muestra le diga en que esta. Se registra como error
        porque explica por que el CSV no arranca en INITIAL_VOLTAGE.
        """
        logging.info(
            f"Initializing hardware: Voltage={self.target_voltage}mV, Frequency={self.target_frequency}MHz"
        )
        if not self.api_client.set_settings(
            self.target_voltage, self.target_frequency
        ):
            logging.error(
                f"No se pudo fijar el ajuste inicial {self.target_voltage}mV/"
                f"{self.target_frequency}MHz: se sigue con el que tenga el "
                f"miner y se adoptara en la primera muestra"
            )

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
        """
        Start the tuning process, adjusting settings based on system info and exposing metrics if enabled.

        El manejo de errores es por iteracion y no por bucle a proposito. Con un
        unico `except` alrededor del `while`, cualquier excepcion imprevista
        (un campo raro en la respuesta del miner, un disco lleno al escribir el
        CSV) sacaba del bucle, la registraba y RETORNABA: el proceso terminaba
        con codigo 0, asi que `restart: unless-stopped` lo tomaba por una salida
        limpia y no reiniciaba nada. El miner se quedaba con el ultimo ajuste
        aplicado y sin nadie vigilando la temperatura, indefinidamente.

        Un fallo suelto en una muestra no es motivo para dejar el hardware sin
        supervision: se registra y se sigue con la siguiente. Lo que si termina
        el bucle es KeyboardInterrupt, que es una parada pedida por el usuario.
        """
        try:
            if isinstance(self.terminal_ui, RichTerminalUI):
                self.terminal_ui.start()
            logging.info("Starting BitaxePID tuner...")
            while self.running:
                try:
                    self._tune_once()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    # Sin logging.exception se perderia la traza, y con ella la
                    # unica pista de donde fallo una muestra que ya paso.
                    logging.exception(f"Error en la muestra de tuning: {e}")
                    time.sleep(1)
                    continue

                time.sleep(self.sample_interval)
        except KeyboardInterrupt:
            self.stop_tuning()
        finally:
            if isinstance(self.terminal_ui, RichTerminalUI):
                self.terminal_ui.stop()

    # Claves de la configuracion que NO salen por el servidor de metricas. Son
    # las que identifican donde se mina y con que credenciales, o rutas del
    # sistema de ficheros del host: nada de eso sirve para un panel de Grafana y
    # todo ello describe la instalacion a quien pregunte.
    _CLAVES_NO_PUBLICABLES = frozenset(
        {
            "PRIMARY_STRATUM",
            "BACKUP_STRATUM",
            "USER_FILE",
            "POOLS_FILE",
            "LOG_FILE",
            "SNAPSHOT_FILE",
        }
    )

    def _metricas_publicables(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Quitar de una muestra lo que no debe salir por el endpoint HTTP.

        `pid_settings` era `self.config` entera, y el servidor de metricas la
        servia en 0.0.0.0:8093 sin autenticacion: con PRIMARY_STRATUM declarado,
        la URL del pool quedaba publicada en la red. Los limites y las ganancias
        si se conservan, porque son justo lo que hace util el endpoint para
        diagnosticar (y para confirmar de un vistazo que se cargo el perfil que
        se creia).

        No es una medida de seguridad completa: el endpoint sigue siendo abierto
        y las metricas de operacion del miner siguen ahi. Solo deja de regalar
        las credenciales y la topologia.

        Args:
            metrics (Dict[str, Any]): Muestra tal como se escribe en el CSV.

        Returns:
            Dict[str, Any]: Copia apta para publicar. El original no se toca,
                porque el CSV si lleva la configuracion completa.
        """
        publicables = dict(metrics)
        settings = publicables.get("pid_settings")
        if isinstance(settings, dict):
            publicables["pid_settings"] = {
                clave: valor
                for clave, valor in settings.items()
                if clave not in self._CLAVES_NO_PUBLICABLES
            }
        return publicables

    def _tune_once(self) -> None:
        """
        Una muestra: leer el miner, decidir y aplicar.

        Separado de `start_tuning` para que el `except` de la iteracion cubra
        exactamente el trabajo de una muestra, sin envolver la espera ni el
        arranque y parada de la UI.
        """
        system_info = self.api_client.get_system_info()
        if not system_info:
            time.sleep(1)
            return

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
        if isinstance(self.tuning_strategy, EstabilidadTuningStrategy):
            metrics["error_percent"] = system_info.get("errorPercentage")
            metrics["error_target"] = self.tuning_strategy.error_target
            metrics["estado"] = self.tuning_strategy.estado
        self.logger.log_to_csv(**metrics)
        if opcional(self.config, "METRICS_SERVE"):
            # Al servidor HTTP va una version filtrada, no `metrics` tal cual: el
            # endpoint :8093/metrics no tiene autenticacion y escucha en todas las
            # interfaces, mientras que el CSV es un fichero local y si puede
            # llevar la configuracion entera.
            update_metrics(self.mac_address, self._metricas_publicables(metrics))

        # errorPercentage lo consumen las DOS estrategias: ninguna decide ya por
        # hashrate. Si el miner no lo reporta llega None, y cada estrategia
        # omite el criterio de errores en vez de suponer un 0% que autorizaria
        # subidas a ciegas.
        kwargs = {"error_percent": system_info.get("errorPercentage")}
        # La adopcion de cambios externos sigue siendo solo de la estrategia de
        # estabilidad: es la que mantiene ventana de errores y techo aprendido,
        # y por tanto la unica que necesita enterarse de que el punto de partida
        # ya no es el suyo.
        if isinstance(self.tuning_strategy, EstabilidadTuningStrategy):
            self._adoptar_ajuste_externo(system_info)

        # El hashrate NO se pasa: ninguna estrategia decide con el. Se sigue
        # midiendo y registrando en el CSV, que es donde sirve para ver el
        # resultado de un ajuste, pero no entra en la decision.
        new_voltage, new_frequency = self.tuning_strategy.apply_strategy(
            current_voltage=self.target_voltage,
            current_frequency=self.target_frequency,
            temp=system_info.get("temp", 0),
            power=system_info.get("power", 0),
            **kwargs,
        )

        if (
            new_voltage != self.target_voltage
            or new_frequency != self.target_frequency
        ):
            # El ajuste solo se da por vigente si el miner lo acepto. Si la
            # escritura falla, `target_*` se queda como estaba: asi la decision
            # siguiente parte del ajuste que el miner tiene de verdad, y
            # `_adoptar_ajuste_externo` no confunde un fallo de red con un
            # cambio hecho por el usuario en la web de AxeOS.
            if self.api_client.set_settings(new_voltage, new_frequency):
                self.target_voltage = new_voltage
                self.target_frequency = new_frequency
                self.logger.save_snapshot(
                    self.target_voltage, self.target_frequency
                )
            else:
                logging.error(
                    f"No se pudo aplicar {new_voltage}mV/{new_frequency}MHz: "
                    f"se mantiene {self.target_voltage}mV/"
                    f"{self.target_frequency}MHz y se reintentara en la "
                    f"muestra siguiente"
                )
