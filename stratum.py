#!/usr/bin/env python3
"""
Endpoints stratum: parseo, medicion de latencia y seleccion de pools.

Lee la lista de pools de pools.yaml, mide la latencia de cada endpoint abriendo
un socket TCP (varios intentos, se queda con la mediana) y devuelve los dos mas
rapidos para usarlos como primario y de respaldo. Las mediciones se guardan en
pools.yaml y se reutilizan durante 15 minutos, para no castigar a los pools con
sondeos en cada arranque.

Aqui vive tambien parse_stratum_url, la unica implementacion del parseo de
endpoints del proyecto.

Uso:
    from stratum import get_fastest_pools, parse_stratum_url

    pools = get_fastest_pools(yaml_file="pools.yaml", stratum_user="...", fallback_stratum_user="...")

Como diagnostico manual, el modulo se puede ejecutar directamente para medir
todos los pools e imprimir el YAML resultante por stdout:

    python3 stratum.py

Dependencias:
    - Terceros: pyyaml
    - Estandar: logging, os, socket, statistics, sys, time, typing, urllib.parse
"""

import logging
import sys
import time
import socket
import yaml
import statistics
from typing import List, Dict, Union, Optional, Any
from urllib.parse import urlparse
import os


# --- Pool Management Functions ---
logger = logging.getLogger(__name__)

STRATUM_SCHEME = "stratum+tcp"


def parse_stratum_url(url: str) -> Dict[str, Any]:
    """
    Parse a stratum endpoint into its hostname and port.

    Unica implementacion del parseo de endpoints stratum del proyecto: la usan
    tanto la medicion de latencias como la configuracion que se envia al miner.

    Acepta el endpoint con o sin esquema; si falta, se asume "stratum+tcp://".
    El puerto es obligatorio. El hostname se normaliza a minusculas y se
    descarta la informacion de usuario ("user@host") y la ruta, igual que hace
    urlparse.

    Args:
        url (str): Endpoint stratum (p.ej. "stratum+tcp://solo.ckpool.org:3333"
            o "solo.ckpool.org:3333").

    Returns:
        Dict[str, Any]: Diccionario con las claves 'hostname' y 'port'.

    Raises:
        ValueError: Si el esquema no es stratum+tcp, si falta el hostname o el
            puerto, o si el puerto no es un entero entre 0 y 65535.

    Example:
        >>> parse_stratum_url("stratum+tcp://solo.ckpool.org:3333")
        {'hostname': 'solo.ckpool.org', 'port': 3333}
        >>> parse_stratum_url("solo.ckpool.org:3333")
        {'hostname': 'solo.ckpool.org', 'port': 3333}
    """
    candidate = url.strip()
    if "://" not in candidate:
        # Tolerancia heredada de la medicion de latencias, donde los endpoints
        # de pools.yaml podian venir sin esquema.
        candidate = f"{STRATUM_SCHEME}://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme != STRATUM_SCHEME:
        raise ValueError(
            f"Invalid scheme: {parsed.scheme}. Expected '{STRATUM_SCHEME}'"
        )
    # urlparse valida el rango del puerto y lanza ValueError si no es entero.
    port = parsed.port
    if not parsed.hostname or port is None:
        raise ValueError("Stratum URL must include both hostname and port")
    return {"hostname": parsed.hostname, "port": port}


def load_pools(yaml_file: str = "pools.yaml") -> List[Dict[str, Any]]:
    """
    Load mining pool configurations from a YAML file.
    Args:
        yaml_file: Path to the YAML file containing pool data.
    Returns:
        List of dictionaries containing pool details (endpoint, fee, latency, last_tested).
    """
    try:
        with open(yaml_file, "r") as file:
            data = yaml.safe_load(file)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Error loading pools from {yaml_file}: {e}")
        return []


def load_user_yaml(user_yaml: str = "user.yaml") -> Dict[str, str]:
    """
    Load user configuration from a YAML file.
    Args:
        user_yaml: Path to the user YAML file.
    Returns:
        Dictionary containing user configurations (stratumUser, fallbackStratumUser).
    """
    try:
        with open(user_yaml, "r") as file:
            return yaml.safe_load(file) or {}
    except FileNotFoundError:
        logger.warning(
            f"User YAML file {user_yaml} not found. Using empty user configurations."
        )
        return {}


def measure_latency(
    endpoint: str,
    port: int,
    timeout: float = 5.0,
    attempts: int = 5,
    delay: float = 0.5,
) -> float:
    """
    Measures the median latency to a given network endpoint with thorough testing.
    Args:
        endpoint: Hostname of the pool (e.g., 'solo.ckpool.org').
        port: Port number of the pool (e.g., 3333).
        timeout: Timeout for each connection attempt in seconds.
        attempts: Number of attempts to measure latency.
        delay: Delay between attempts in seconds.
    Returns:
        Median latency in milliseconds, or infinity if unreachable.
    """
    latencies = []
    logger.info(f"Testing latency for {endpoint}:{port}")

    for i in range(attempts):
        start_time = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((endpoint, port))
            # Send a dummy request to ensure connection is fully established
            sock.send(b"\n")
            sock.close()
            latency = (time.time() - start_time) * 1000  # Convert to milliseconds
            latencies.append(latency)
            logger.debug(f"Attempt {i+1}/{attempts}: {latency:.0f}ms")
        except (socket.timeout, socket.error) as e:
            logger.debug(f"Attempt {i+1}/{attempts}: Failed ({str(e)})")
            latencies.append(float("inf"))
        time.sleep(delay)

    median_latency = statistics.median(latencies) if latencies else float("inf")
    logger.info(f"Median latency: {median_latency:.0f}ms")
    return median_latency


def measure_pools(yaml_file: str = "pools.yaml") -> List[Dict[str, Any]]:
    """
    Loads pools from a YAML file, measures latency for each, and saves results back to file
    while preserving existing pool information.
    Args:
        yaml_file: Path to the YAML file containing pool data.
    Returns:
        List of pool dictionaries with updated latency measurements and timestamps.
    """
    # First verify we can read the file
    try:
        with open(yaml_file, "r") as f:
            pools = yaml.safe_load(f)
            if not isinstance(pools, list):
                logger.error(f"Invalid pools data format in {yaml_file}")
                return []
    except Exception as e:
        logger.error(f"Error reading {yaml_file}: {e}")
        return []

    logger.info(f"Measuring latency for {len(pools)} pools...")
    updated_pools = []

    for pool in pools:
        try:
            endpoint_str = pool["endpoint"]
            parsed = parse_stratum_url(endpoint_str)
            hostname, port = parsed["hostname"], parsed["port"]
            latency = measure_latency(hostname, port)

            # Create new dict with all existing data plus latency info
            updated_pool = pool.copy()
            updated_pool.update(
                {
                    "latency": latency,
                    "port": port,
                    "last_tested": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            updated_pools.append(updated_pool)

            logger.debug(
                f"Updated pool data for {endpoint_str}: latency={latency:.0f}ms"
            )

        except ValueError as e:
            logger.error(f"Error parsing endpoint {endpoint_str}: {e}")
            updated_pool = pool.copy()
            updated_pool.update(
                {
                    "latency": float("inf"),
                    "port": 0,
                    "last_tested": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            updated_pools.append(updated_pool)

    # Try to save the updated data
    try:
        # First write to a temporary file
        temp_file = f"{yaml_file}.tmp"
        with open(temp_file, "w") as f:
            yaml.safe_dump(updated_pools, f, default_flow_style=False, sort_keys=False)

        # If successful, rename to the actual file
        os.replace(temp_file, yaml_file)
        logger.info(f"Successfully updated {yaml_file} with new latency data")

        # Verify the file was written correctly
        with open(yaml_file, "r") as f:
            verify_pools = yaml.safe_load(f)
            if not verify_pools or len(verify_pools) != len(pools):
                logger.warning(f"File verification failed for {yaml_file}")
            else:
                logger.debug(
                    f"File verification successful: {len(verify_pools)} pools saved"
                )

    except Exception as e:
        logger.error(f"Error saving pool data to {yaml_file}: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        return updated_pools

    return updated_pools


def get_fastest_pools(
    yaml_file: str = "pools.yaml",
    stratum_user: Optional[str] = None,
    fallback_stratum_user: Optional[str] = None,
    user_yaml: str = "user.yaml",
    force_measure: bool = False,
    latency_expiry_minutes: int = 15,
) -> List[Dict[str, Union[str, int]]]:
    """
    Retrieves the two fastest pools, measuring latency if expired or forced.
    Args:
        yaml_file: Path to the YAML file containing pool data.
        stratum_user: Optional stratum user for primary pool.
        fallback_stratum_user: Optional stratum user for backup pool.
        user_yaml: Path to the user YAML file for default users.
        force_measure: If True, force new latency measurements.
        latency_expiry_minutes: Minutes before latency measurements expire (default 15).
    Returns:
        List of up to two fastest pools with latency, port, and user keys.
    """
    # Load existing pools first
    pools = load_pools(yaml_file)

    # Check if we need to measure latencies
    current_time = time.time()
    need_measure = force_measure

    if not need_measure:
        for pool in pools:
            if "latency" not in pool or "last_tested" not in pool:
                need_measure = True
                break
            try:
                # Convert last_tested string to timestamp
                last_tested = time.strptime(pool["last_tested"], "%Y-%m-%d %H:%M:%S")
                last_tested_timestamp = time.mktime(last_tested)

                # Check if latency measurement has expired
                minutes_since_test = (current_time - last_tested_timestamp) / 60
                if minutes_since_test > latency_expiry_minutes:
                    logger.info(
                        f"Latency data expired for {pool['endpoint']} "
                        f"(last tested: {pool['last_tested']}, "
                        f"{minutes_since_test:.1f} minutes ago)"
                    )
                    need_measure = True
                    break
            except (ValueError, KeyError) as e:
                logger.warning(f"Error checking latency expiry: {e}")
                need_measure = True
                break

    if need_measure:
        logger.info("Measuring pool latencies...")
        pools = measure_pools(yaml_file)
    else:
        logger.info("Using cached pool latencies")

    valid_pools = [
        pool for pool in pools if pool.get("latency", float("inf")) != float("inf")
    ]
    sorted_pools = sorted(valid_pools, key=lambda x: x.get("latency", float("inf")))[:2]

    if not sorted_pools:
        logger.error("No valid pools found.")
        return []

    if len(sorted_pools) < 2:
        logger.warning("Only one valid pool found. Duplicating for backup.")
        sorted_pools.append(sorted_pools[0].copy())

    # Load default users from user.yaml if not provided
    if stratum_user is None or fallback_stratum_user is None:
        user_config = load_user_yaml(user_yaml)
        default_stratum_user = user_config.get("stratumUser", "")
        default_fallback_user = user_config.get(
            "fallbackStratumUser", default_stratum_user
        )
    else:
        default_stratum_user = stratum_user
        default_fallback_user = fallback_stratum_user

    # Assign users: use provided values if available, otherwise fall back to user.yaml defaults
    sorted_pools[0]["user"] = (
        stratum_user if stratum_user is not None else default_stratum_user
    )
    sorted_pools[1]["user"] = (
        fallback_stratum_user
        if fallback_stratum_user is not None
        else default_fallback_user
    )

    # Log selected pools
    logger.info("Selected pools:")
    for i, pool in enumerate(sorted_pools):
        logger.info(
            f"{'Primary' if i == 0 else 'Backup'} pool: "
            f"{pool['endpoint']} (latency: {pool['latency']:.0f}ms, "
            f"last tested: {pool['last_tested']})"
        )

    return sorted_pools


def main() -> None:
    """
    Diagnostico manual: mide las latencias de los pools y las imprime.

    Se ejecuta con `python pools.py` para comprobar la conectividad sin
    arrancar el auto-tuner completo. Igual que measure_pools(), reescribe
    pools.yaml con las latencias medidas.
    """
    # Solo al ejecutarse como programa se configura el logging: como libreria,
    # el modulo se limita a emitir por su logger y deja la configuracion al
    # llamante (bitaxepid.py), que es lo que se espera de un modulo importable.
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    pools_with_latency = measure_pools()
    # El resultado va a stdout, no al log: es la salida util del comando, para
    # poder redirigirla o pasarla por una tuberia.
    print("\nCurrent pool latencies:")
    print(yaml.safe_dump(pools_with_latency, default_flow_style=False))


if __name__ == "__main__":
    main()
