#!/usr/bin/env python3
"""
Carga y validacion de la configuracion de BitaxePID.

La configuracion se compone en dos capas: el YAML del modelo de ASIC
(BM1366.yaml, BM1370.yaml...) con los limites de voltaje y frecuencia de ese
chip, y opcionalmente un YAML de usuario que sobreescribe claves concretas. Las
opciones de linea de comandos se aplican encima de todo eso, en cli.py.

Hay tres categorias de clave, y la diferencia importa:

  - Obligatorias siempre (`required_keys`): sin ellas no se puede ni escribir un
    valor al miner. Si falta una, el programa termina.
  - Obligatorias solo con la estrategia antigua (`CLAVES_SOLO_PID`): ningun
    modulo las lee, pero alimentan columnas del CSV. Ver el comentario de la
    lista.
  - Opcionales (`CLAVES_OPCIONALES`): el programa tira con un valor por defecto
    declarado en este modulo. Se avisa por log de las que falten.

Uso:
    from config import YamlConfigLoader, load_config, opcional, validate_config

    config = load_config(YamlConfigLoader(), "BM1366.yaml", "mi_config.yaml")
    validate_config(config)   # falta una clave -> termina; fuera de rango -> recorta
    ventana = opcional(config, "ERROR_WINDOW")   # el valor, o su defecto

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


# Claves que solo tenian sentido cuando la estrategia perseguia un setpoint de
# hashrate con dos controladores PID. Hoy NINGUN modulo las lee para decidir
# nada: se buscaron una por una y las unicas apariciones son las columnas del
# CSV (logger.py), que ya usan `pid_settings.get(clave, "")` y quedan vacias sin
# romper la cabecera.
#
# Por eso no pueden seguir en `required_keys`: exigirlas obliga a declarar seis
# ganancias PID y un objetivo de hashrate en un perfil de la estrategia de
# errores, donde no significan nada. Un perfil limpio para un Bitaxe nuevo
# terminaba con "Missing required config keys: PID_FREQ_KP, ..." y quien lo
# leyera no tenia forma de saber que el programa no las usa.
#
# Se siguen exigiendo cuando ERROR_TUNING esta desactivado, porque ahi el CSV es
# el de esa estrategia y sus columnas se comparan con historiales antiguos.
CLAVES_SOLO_PID = (
    "PID_FREQ_KP",
    "PID_FREQ_KI",
    "PID_FREQ_KD",
    "PID_VOLT_KP",
    "PID_VOLT_KI",
    "PID_VOLT_KD",
    "HASHRATE_SETPOINT",
)


# Claves OPCIONALES y el valor por defecto que aplica el codigo si faltan.
#
# Esta tabla es la unica fuente del valor: quien lee la configuracion llama a
# `opcional()` en vez de repetir el defecto en su `config.get(clave, X)`. Antes
# estaban escritos a mano en bitaxepid.py, con lo que el YAML documentaba un
# numero y el codigo podia aplicar otro sin que nada lo detectara.
#
# Faltar no es un error, pero si algo que hay que poder ver: `validate_config`
# deja en el log los defectos que quedan en vigor. El caso que lo motiva es
# ERROR_TUNING: sin declararlo se corre la OTRA estrategia, y un perfil escrito
# entero para la de estabilidad se ejecutaria con la de limites.
#
# No estan aqui las opcionales que no tienen defecto sino ausencia con
# significado propio: ERROR_TARGET_PERCENT (obligatoria con ERROR_TUNING, la
# comprueba bitaxepid.py; sin ella la estrategia de limites decide solo con
# temperatura y potencia) ni PRIMARY_STRATUM/BACKUP_STRATUM (declararlas AMBAS
# es lo que activa el stratum fijo en vez de medir latencias).
CLAVES_OPCIONALES: Dict[str, Any] = {
    "ERROR_TUNING": False,
    "ERROR_HYSTERESIS": 0.5,
    "ERROR_WINDOW": 7,
    "ERROR_SETTLE": 3,
    "TEMP_MARGIN": 2.0,
    "ERROR_RETRY_CEILING": 50,
    "LOWER_VOLTAGE_AFTER": 4,
    "METRICS_SERVE": False,
    "MANAGE_MINER_POOLS": False,
    "USER_FILE": None,
}


def opcional(config: Dict[str, Any], key: str) -> Any:
    """
    Devolver el valor de una clave opcional, o su defecto de CLAVES_OPCIONALES.

    Args:
        config (Dict[str, Any]): Configuracion ya fusionada.
        key (str): Nombre de la clave, que debe estar en CLAVES_OPCIONALES.

    Returns:
        Any: El valor configurado, o el defecto declarado en este modulo.

    Raises:
        KeyError: Si la clave no esta declarada como opcional. Es deliberado:
            leer con un defecto inventado en el momento es justo lo que hacia
            que los defectos del codigo y los del YAML se separaran.

    Example:
        >>> opcional({"ERROR_WINDOW": 9}, "ERROR_WINDOW")
        9
        >>> opcional({}, "ERROR_WINDOW")
        7
    """
    if key not in CLAVES_OPCIONALES:
        raise KeyError(
            f"{key} no esta declarada en CLAVES_OPCIONALES: anadela ahi con su "
            "valor por defecto en vez de pasar uno suelto en la llamada"
        )
    return config.get(key, CLAVES_OPCIONALES[key])


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
    if user_config_path:
        # Un --config que no existe se ignoraba en silencio, y el programa
        # arrancaba con los limites del YAML del chip. Cuando el fichero de
        # usuario es justo el que baja MAX_VOLTAGE y MAX_FREQUENCY (un perfil
        # conservador, o una configuracion montada en un contenedor), una ruta
        # mal escrita dejaba al miner corriendo con los topes de fabrica sin
        # decir nada. Si se pide explicitamente, tiene que existir.
        if not os.path.exists(user_config_path):
            logger.error(
                f"User config file {user_config_path} not found "
                "(se pidio con --config o USER_CONFIG)"
            )
            sys.exit(1)
        user_config = config_loader.load_config(user_config_path)
        if not user_config:
            logger.error(
                f"User config file {user_config_path} no se pudo leer o esta "
                "vacio: se ignorarian sus limites"
            )
            sys.exit(1)
        config.update(user_config)
    return config


def clamp_initial_values(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recorta INITIAL_VOLTAGE e INITIAL_FREQUENCY al rango configurado.

    El valor inicial se aplica al miner en el arranque (`_initialize_hardware`)
    sin pasar por la estrategia de tuning, asi que el recorte de
    `apply_strategy` no lo cubre: con MAX_VOLTAGE=1150 y `--voltage 1250` el
    miner recibia 1250mV. MIN_VOLTAGE y MAX_VOLTAGE son limites de hardware, y
    la unica lectura coherente es que valgan tambien para el primer valor que
    se escribe.

    Se recorta en lugar de abortar porque el caso normal es benigno y muy
    facil de provocar: bajar MAX_FREQUENCY en un YAML propio deja el
    INITIAL_FREQUENCY heredado del YAML del chip por encima del nuevo tope.
    Abortar obligaria a redeclarar los valores iniciales cada vez que se
    ajusta un limite. El recorte queda en el log como WARNING.

    Modifica `config` in situ y lo devuelve, para poder encadenarlo.

    Args:
        config (Dict[str, Any]): Configuracion ya fusionada, con los overrides
            de linea de comandos aplicados.

    Returns:
        Dict[str, Any]: El mismo diccionario, con los valores iniciales dentro
            de rango.
    """
    for key, low_key, high_key, unit in (
        ("INITIAL_VOLTAGE", "MIN_VOLTAGE", "MAX_VOLTAGE", "mV"),
        ("INITIAL_FREQUENCY", "MIN_FREQUENCY", "MAX_FREQUENCY", "MHz"),
    ):
        value = config.get(key)
        low = config.get(low_key)
        high = config.get(high_key)
        if value is None or low is None or high is None:
            # validate_config ya informa de las claves que faltan.
            continue
        clamped = max(low, min(high, value))
        if clamped != value:
            logger.warning(
                f"{key}={value}{unit} esta fuera del rango "
                f"{low}-{high}{unit} ({low_key}/{high_key}): "
                f"se usara {clamped}{unit}"
            )
            config[key] = clamped
    return config


def validate_ranges(config: Dict[str, Any]) -> None:
    """
    Comprobar que los limites de voltaje y frecuencia no estan invertidos.

    Es la unica validacion del proyecto que no se puede sustituir por un
    recorte, porque el recorte es justo lo que deja de funcionar. Tanto
    `_cerrar` (estrategia de estabilidad) como `apply_strategy` (PID) cierran
    con `max(minimo, min(maximo, valor))`, que es correcto SOLO si
    minimo <= maximo: con los limites al reves gana el `max()` exterior y la
    funcion devuelve MIN_VOLTAGE, es decir, un valor POR ENCIMA del tope que
    esa misma linea existe para imponer. Un solo digito mal en un YAML de
    usuario convierte la red de seguridad en su contrario, y lo que sale de
    ahi va directo al voltaje del core.

    Por eso aqui se aborta y no se recorta ni se reordena: unos limites
    invertidos no son un valor fuera de rango que se pueda acomodar, son una
    configuracion que no expresa ninguna intencion interpretable. Adivinar
    cual de los dos numeros quiso poner el usuario seria peor que pararse.

    Args:
        config (Dict[str, Any]): Configuracion ya fusionada.

    Raises:
        SystemExit: Si algun par de limites esta invertido.
    """
    invertidos = []
    for low_key, high_key, unit in (
        ("MIN_VOLTAGE", "MAX_VOLTAGE", "mV"),
        ("MIN_FREQUENCY", "MAX_FREQUENCY", "MHz"),
    ):
        low = config.get(low_key)
        high = config.get(high_key)
        if low is None or high is None:
            # Las claves que faltan las informa validate_config.
            continue
        if low > high:
            invertidos.append(
                f"{low_key}={low}{unit} > {high_key}={high}{unit}"
            )
    if invertidos:
        logger.error(
            "Limites invertidos en la configuracion: "
            + "; ".join(invertidos)
            + ". El recorte de seguridad no puede funcionar con el minimo por "
            "encima del maximo (devolveria el minimo, saltandose el tope), "
            "asi que no se arranca."
        )
        sys.exit(1)


def avisar_de_opcionales_ausentes(config: Dict[str, Any]) -> None:
    """
    Dejar en el log los valores por defecto que quedan en vigor.

    Las claves de `CLAVES_OPCIONALES` no se exigen, pero su ausencia tampoco
    deberia ser invisible: el programa acaba corriendo con numeros que no estan
    escritos en ningun sitio que el usuario haya leido. El caso que motiva el
    aviso es ERROR_TUNING, cuyo defecto (False) no es un matiz sino OTRA
    estrategia: un perfil escrito entero para la de estabilidad, al que se le
    olvide esa linea, arranca con la de limites y todo lo demas que declara
    (ventana, histeresis, techo) se ignora en silencio.

    Es un WARNING y no un error porque los defectos son deliberados y correctos
    para el caso normal; lo que no puede pasar es que nadie sepa cuales rigen.

    Args:
        config (Dict[str, Any]): Configuracion ya fusionada.
    """
    ausentes = {k: v for k, v in CLAVES_OPCIONALES.items() if k not in config}
    if not ausentes:
        return
    detalle = ", ".join(f"{k}={v}" for k, v in sorted(ausentes.items()))
    logger.warning(
        f"Claves opcionales no declaradas, se usan los valores por defecto del "
        f"programa: {detalle}"
    )
    if "ERROR_TUNING" in ausentes:
        logger.warning(
            "ERROR_TUNING no esta declarado: se usara la estrategia por limites "
            "(temperatura, potencia y errores) y NO la de estabilidad. Si este "
            "perfil se escribio para la de estabilidad, declara ERROR_TUNING: TRUE."
        )


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate that required configuration keys are present.

    Tambien comprueba que los limites no esten invertidos (ver
    `validate_ranges`), recorta los valores iniciales al rango configurado (ver
    `clamp_initial_values`) y deja en el log los defectos de las claves
    opcionales ausentes (ver `avisar_de_opcionales_ausentes`). El orden importa:
    sin `validate_ranges` por delante, `clamp_initial_values` recortaria contra
    un rango imposible.

    Las siete claves de `CLAVES_SOLO_PID` se exigen SOLO cuando ERROR_TUNING
    esta desactivado. Con la estrategia de estabilidad no las lee nadie, y
    pedirlas obligaba a copiar seis ganancias PID a un perfil que no tiene
    ningun PID para que el programa arrancara.

    Args:
        config (Dict[str, Any]): Configuration dictionary to validate.

    Raises:
        SystemExit: If required keys are missing or limits are inverted.
    """
    required_keys = [
        "INITIAL_VOLTAGE",
        "INITIAL_FREQUENCY",
        "SAMPLE_INTERVAL",
        "LOG_FILE",
        "SNAPSHOT_FILE",
        "POOLS_FILE",
        "MIN_VOLTAGE",
        "MAX_VOLTAGE",
        "MIN_FREQUENCY",
        "MAX_FREQUENCY",
        "VOLTAGE_STEP",
        "FREQUENCY_STEP",
        "TARGET_TEMP",
        "POWER_LIMIT",
    ]
    if not opcional(config, "ERROR_TUNING"):
        required_keys.extend(CLAVES_SOLO_PID)
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        logger.error(f"Missing required config keys: {', '.join(missing_keys)}")
        sys.exit(1)
    validate_ranges(config)
    clamp_initial_values(config)
    avisar_de_opcionales_ausentes(config)
