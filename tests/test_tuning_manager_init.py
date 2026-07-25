#!/usr/bin/env python3
"""Tests de que construir un TuningManager no toca el miner.

Antes del refactor, TuningManager.__init__ leia el estado del miner, medía la
latencia de pools reales en internet, aplicaba la configuracion stratum y
reiniciaba el hardware. Instanciar el objeto era imposible sin un miner
encendido, y cualquier fallo de red aparecia como un constructor llamando a
sys.exit(1).

Estos tests fijan la separacion: el constructor solo guarda parametros, y todo
lo que habla con el miner vive en connect_and_configure().

Ejecutar:  python3 -m unittest tests.test_tuning_manager_init -v
No necesita miner ni red: el doble de la API falla si alguien lo llama.
"""

import os
import unittest

import yaml

from tuning_manager import TuningManager

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ApiClientQueFalla:
    """Doble de IBitaxeAPIClient: cualquier uso es un error del test."""

    def __init__(self):
        self.llamadas = []

    def _prohibido(self, nombre):
        self.llamadas.append(nombre)
        raise AssertionError(f"no se esperaba una llamada a la API: {nombre}")

    def get_system_info(self):
        self._prohibido("get_system_info")

    def set_settings(self, voltage, frequency):
        self._prohibido("set_settings")

    def set_stratum(self, primary, backup):
        self._prohibido("set_stratum")

    def restart(self):
        self._prohibido("restart")

    def close(self):
        self._prohibido("close")


def cargar_config():
    path = os.path.join(REPO_ROOT, "BM1370.yaml")
    with open(path) as fh:
        return yaml.safe_load(fh)


def construir(api_client, **extra):
    config = cargar_config()
    kwargs = dict(
        tuning_strategy=None,
        api_client=api_client,
        logger=None,
        config_loader=None,
        terminal_ui=None,
        sample_interval=config["SAMPLE_INTERVAL"],
        initial_voltage=config["INITIAL_VOLTAGE"],
        initial_frequency=config["INITIAL_FREQUENCY"],
        pools_file=os.path.join(REPO_ROOT, "pools.yaml"),
        config=config,
    )
    kwargs.update(extra)
    return TuningManager(**kwargs), config


class TestConstructorSinEfectos(unittest.TestCase):
    def test_no_llama_a_la_api(self):
        """El caso que importa: construir no debe abrir ni una conexion."""
        api = ApiClientQueFalla()
        construir(api)
        self.assertEqual(api.llamadas, [])

    def test_no_mide_latencias(self):
        """Tampoco debe medir pools: eso son conexiones a internet y tarda."""
        api = ApiClientQueFalla()
        manager, _ = construir(api)
        # Si hubiera medido, stratum_users se habria rellenado desde el fichero
        # de usuario o desde la API.
        self.assertEqual(manager.stratum_users, {})

    def test_guarda_los_parametros(self):
        api = ApiClientQueFalla()
        manager, config = construir(api)
        self.assertEqual(manager.target_voltage, config["INITIAL_VOLTAGE"])
        self.assertEqual(manager.target_frequency, config["INITIAL_FREQUENCY"])
        self.assertEqual(manager.sample_interval, config["SAMPLE_INTERVAL"])
        self.assertTrue(manager.running)

    def test_atributos_no_quedan_a_medias(self):
        """Los atributos que rellena connect_and_configure deben existir ya,
        con un valor por defecto, para que nadie se encuentre un AttributeError."""
        api = ApiClientQueFalla()
        manager, _ = construir(api)
        self.assertEqual(manager.mac_address, "unknown")
        self.assertEqual(manager.stratum_users, {})

    def test_stratum_de_cli_se_guarda_sin_aplicarse(self):
        """Pasar stratum por CLI no debe configurarlo en el miner todavia."""
        api = ApiClientQueFalla()
        primary = {"hostname": "solo.ckpool.org", "port": 3333, "user": "u1"}
        backup = {"hostname": "pool.example.com", "port": 3333, "user": "u2"}
        manager, _ = construir(api, primary_stratum=primary, backup_stratum=backup)
        self.assertEqual(manager.primary_stratum, primary)
        self.assertEqual(manager.backup_stratum, backup)
        self.assertEqual(api.llamadas, [])


class TestContrato(unittest.TestCase):
    def test_connect_and_configure_existe(self):
        api = ApiClientQueFalla()
        manager, _ = construir(api)
        self.assertTrue(callable(manager.connect_and_configure))

    def test_stop_tuning_sin_conectar(self):
        """Parar antes de conectar no debe fallar: el signal handler puede
        llegar en cualquier momento."""
        api = ApiClientQueFalla()
        manager, _ = construir(api)
        manager.stop_tuning()
        self.assertFalse(manager.running)


if __name__ == "__main__":
    unittest.main(verbosity=2)
