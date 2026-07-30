#!/usr/bin/env python3
"""
Cliente HTTP de la API del miner Bitaxe.

Encapsula las cuatro operaciones que el auto-tuner necesita: leer el estado del
miner, aplicar voltaje y frecuencia, configurar los pools stratum y reiniciar.
Usa un pool de conexiones de urllib3 con reintentos y backoff exponencial,
porque un miner ocupado puede tardar en responder o cortar la conexion.

Uso:
    from api_client import BitaxeAPIClient

    client = BitaxeAPIClient("192.168.1.1")
    info = client.get_system_info()
    client.set_settings(voltage=1200, frequency=485)
    client.close()

Dependencias:
    - Terceros: urllib3
    - Estandar: json, logging, time, typing
"""

import json
import logging
import time
from typing import Any, Dict, Optional

import urllib3
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class BitaxeAPIClient:
    """Concrete implementation of the Bitaxe API client using urllib3 for robust communication."""

    def __init__(
        self, ip: str, timeout: int = 10, retries: int = 5, pool_maxsize: int = 10
    ) -> None:
        """
        Initialize the Bitaxe API client with a connection pool.

        Args:
            ip (str): IP address of the Bitaxe miner (e.g., "192.168.1.1").
            timeout (int): Timeout for each request in seconds (default: 10).
            retries (int): Number of retries for failed requests (default: 5).
            pool_maxsize (int): Maximum number of connections in the pool (default: 10).
        """
        self.bitaxepid_url = f"http://{ip}"
        retry_strategy = Retry(
            total=retries,
            backoff_factor=1,  # Exponential backoff: 1s, 2s, 4s, etc.
            status_forcelist=[500, 502, 503, 504],  # Retry on server errors
        )
        self.http_pool = urllib3.HTTPConnectionPool(
            host=ip,
            port=80,
            timeout=urllib3.Timeout(connect=timeout, read=timeout),
            maxsize=pool_maxsize,
            retries=retry_strategy,
            block=False,
        )
        logger.info(
            f"Initialized BitaxeAPIClient for {ip} with timeout={timeout}s, retries={retries}, pool_maxsize={pool_maxsize}"
        )

    def get_system_info(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve current system information from the miner.

        Returns:
            Optional[Dict[str, Any]]: System information as a dictionary (e.g., {"hashRate": 500, "temp": 48}), or None if unavailable.

        Example:
            >>> client = BitaxeAPIClient("192.168.1.1")
            >>> info = client.get_system_info()
            >>> info.get("hashRate")
            500.0
        """
        try:
            response = self.http_pool.request("GET", "/api/system/info")
            if response.status == 200:
                return json.loads(response.data.decode("utf-8"))
            else:
                logger.error(f"Failed to fetch system info: HTTP {response.status}")
                return None
        except urllib3.exceptions.MaxRetryError as e:
            logger.error(f"Max retries exceeded fetching system info: {e}")
            return None
        except urllib3.exceptions.TimeoutError as e:
            logger.error(f"Timeout fetching system info: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching system info: {e}")
            return None

    def set_settings(self, voltage: float, frequency: float) -> bool:
        """
        Set voltage and frequency on the miner and report whether it took effect.

        Devolvia la frecuencia PEDIDA, y la devolvia igual con un 200, con un
        500 y con una excepcion: el valor de retorno no distinguia el exito del
        fallo, asi que quien llamaba no tenia forma de saberlo. El bucle de
        tuning daba entonces por aplicado un ajuste que el miner no tenia, y en
        la muestra siguiente la discrepancia se interpretaba como un cambio
        hecho por el usuario desde la web de AxeOS: un fallo de red acababa
        tirando la ventana de errores medida y lo aprendido sobre techos.

        El mismatch contra el miner tampoco se reportaba, solo se registraba
        como warning; ahora cuenta como fallo, porque un ajuste que el miner no
        adopto no esta aplicado por mucho que el PATCH respondiera 200.

        Args:
            voltage (float): Target core voltage to set (mV).
            frequency (float): Target frequency to set (MHz).

        Returns:
            bool: True si el miner acepto el ajuste y lo confirma al releerlo;
                False si la peticion fallo, si hubo excepcion o si el miner
                quedo en otro valor. Cuando no se puede releer el estado se
                concede el 200 como suficiente: la escritura se acepto, y
                tratarlo como fallo dejaria al tuner sin poder actuar cada vez
                que la relectura no llega.

        Example:
            >>> client = BitaxeAPIClient("192.168.1.1")
            >>> client.set_settings(1200, 485)
            True
        """
        settings = {"coreVoltage": voltage, "frequency": frequency}
        try:
            response = self.http_pool.request(
                "PATCH",
                "/api/system",
                body=json.dumps(settings).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            if response.status == 200:
                logger.info(
                    f"Applied settings: Voltage={voltage}mV, Frequency={frequency}MHz"
                )
                time.sleep(2)  # Allow settings to stabilize
                system_info = self.get_system_info()
                if system_info:
                    actual_voltage = system_info.get("coreVoltage", 0)
                    actual_freq = system_info.get("frequency", 0)
                    if (
                        abs(actual_voltage - voltage) > 5
                        or abs(actual_freq - frequency) > 5
                    ):
                        logger.warning(
                            f"Settings mismatch - Requested: {voltage}mV/{frequency}MHz, "
                            f"Actual: {actual_voltage}mV/{actual_freq}MHz"
                        )
                        return False
                return True
            logger.error(f"Failed to set settings: HTTP {response.status}")
            return False
        except Exception as e:
            logger.error(f"Error setting system settings: {e}")
            return False

    def set_stratum(self, primary: Dict[str, Any], backup: Dict[str, Any]) -> bool:
        """
        Configure primary and backup stratum pools.

        Args:
            primary (Dict[str, Any]): Configuration for the primary stratum pool (e.g., {"hostname": "solo.ckpool.org", "port": 3333, "user": "user1"}).
            backup (Dict[str, Any]): Configuration for the backup stratum pool (e.g., {"hostname": "pool.example.com", "port": 3333, "user": "user2"}).

        Returns:
            bool: True if the stratum settings were successfully applied, False otherwise.

        Example:
            >>> client = BitaxeAPIClient("192.168.1.1")
            >>> primary = {"hostname": "solo.ckpool.org", "port": 3333, "user": "user1"}
            >>> backup = {"hostname": "pool.example.com", "port": 3333, "user": "user2"}
            >>> success = client.set_stratum(primary, backup)
            >>> success
            True
        """
        settings = {
            "stratumURL": primary["hostname"],
            "stratumPort": primary["port"],
            "fallbackStratumURL": backup["hostname"],
            "fallbackStratumPort": backup["port"],
            "stratumUser": primary.get("user", ""),
            "fallbackStratumUser": backup.get("user", ""),
        }
        try:
            response = self.http_pool.request(
                "PATCH",
                "/api/system",
                body=json.dumps(settings).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            if response.status == 200:
                logger.info(
                    f"Set stratum: Primary={primary['hostname']}:{primary['port']} "
                    f"User={primary.get('user', '')}, "
                    f"Backup={backup['hostname']}:{backup['port']} "
                    f"User={backup.get('user', '')}"
                )
                time.sleep(1)
                system_info = self.get_system_info()
                if system_info and not all(
                    [
                        system_info.get("stratumURL") == primary["hostname"],
                        system_info.get("stratumPort") == primary["port"],
                        system_info.get("fallbackStratumURL") == backup["hostname"],
                        system_info.get("fallbackStratumPort") == backup["port"],
                        system_info.get("stratumUser") == primary.get("user", ""),
                        system_info.get("fallbackStratumUser")
                        == backup.get("user", ""),
                    ]
                ):
                    logger.warning("Stratum settings verification failed")
                    return False
                return True
            logger.error(f"Failed to set stratum: HTTP {response.status}")
            return False
        except Exception as e:
            logger.error(f"Error setting stratum endpoints: {e}")
            return False

    def restart(self) -> bool:
        """
        Restart the Bitaxe miner.

        Returns:
            bool: True if the restart was successful and the miner responds, False otherwise.

        Example:
            >>> client = BitaxeAPIClient("192.168.1.1")
            >>> success = client.restart()
            >>> success
            True
        """
        try:
            response = self.http_pool.request("POST", "/api/system/restart")
            if response.status == 200:
                logger.info("Restarted Bitaxe miner")
                time.sleep(5)  # Wait for restart
                for _ in range(3):
                    if self.get_system_info():
                        logger.info("Miner successfully restarted and responding")
                        return True
                    time.sleep(2)
                logger.warning("Miner restart completed but not responding")
                return False
            logger.error(f"Failed to restart miner: HTTP {response.status}")
            return False
        except Exception as e:
            logger.error(f"Error restarting Bitaxe miner: {e}")
            return False

    def close(self) -> None:
        """
        Close the connection pool to free resources.

        Example:
            >>> client = BitaxeAPIClient("192.168.1.1")
            >>> client.close()
        """
        self.http_pool.close()
        logger.info("BitaxeAPIClient connection pool closed")
