#!/usr/bin/env python3
"""Tests del interruptor MANAGE_MINER_POOLS.

Por defecto BitaxePID NO debe tocar la configuracion de pools del miner: es
hardware que el usuario puede tener apuntando a donde quiere, y reconfigurarlo
sin permiso explicito es intrusivo. Con manage_pools=False el tuner ajusta
voltaje y frecuencia, y nada mas.

Consecuencia aceptada a proposito: con manage_pools=False el miner tampoco se
reinicia al arrancar, porque el restart() vive dentro de la secuencia de
aplicacion de stratum.

Ejecutar:  python3 -m unittest tests.test_manage_pools -v
No necesita miner ni red: la API es un Mock y get_fastest_pools esta parcheado.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import yaml

from tuning_manager import TuningManager

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM_INFO = {
    "macAddr": "AA:BB:CC:DD:EE:FF",
    "stratumUser": "usuario.existente",
    "fallbackStratumUser": "usuario.respaldo",
    "stratumURL": "pool.existente.org",
    "stratumPort": 3333,
    "fallbackStratumURL": "pool.respaldo.org",
    "fallbackStratumPort": 3333,
    "hashRate": 500.0,
    "temp": 48.0,
    "power": 15.0,
    "coreVoltage": 1150,
    "frequency": 490,
}


def cargar_config():
    with open(os.path.join(REPO_ROOT, "BM1370.yaml")) as fh:
        return yaml.safe_load(fh)


def construir(manage_pools, api=None, **extra):
    config = cargar_config()
    api = api or MagicMock()
    api.get_system_info.return_value = dict(SYSTEM_INFO)
    api.set_stratum.return_value = True
    api.set_settings.return_value = config["INITIAL_FREQUENCY"]
    kwargs = dict(
        tuning_strategy=MagicMock(),
        api_client=api,
        logger=MagicMock(),
        config_loader=MagicMock(),
        terminal_ui=MagicMock(),
        sample_interval=config["SAMPLE_INTERVAL"],
        initial_voltage=config["INITIAL_VOLTAGE"],
        initial_frequency=config["INITIAL_FREQUENCY"],
        pools_file=os.path.join(REPO_ROOT, "pools.yaml"),
        config=config,
        manage_pools=manage_pools,
    )
    kwargs.update(extra)
    return TuningManager(**kwargs), api, config


class TestPorDefectoNoGestionaPools(unittest.TestCase):
    """manage_pools=False es el valor por defecto y el caso importante."""

    def test_es_el_valor_por_defecto(self):
        config = cargar_config()
        api = MagicMock()
        api.get_system_info.return_value = dict(SYSTEM_INFO)
        manager = TuningManager(
            tuning_strategy=MagicMock(),
            api_client=api,
            logger=MagicMock(),
            config_loader=MagicMock(),
            terminal_ui=MagicMock(),
            sample_interval=config["SAMPLE_INTERVAL"],
            initial_voltage=config["INITIAL_VOLTAGE"],
            initial_frequency=config["INITIAL_FREQUENCY"],
            pools_file=os.path.join(REPO_ROOT, "pools.yaml"),
            config=config,
        )
        self.assertFalse(manager.manage_pools)

    @patch("tuning_manager.get_fastest_pools")
    def test_no_configura_stratum(self, fake_pools):
        manager, api, _ = construir(False)
        manager.connect_and_configure()
        api.set_stratum.assert_not_called()

    @patch("tuning_manager.get_fastest_pools")
    def test_no_reinicia_el_miner(self, fake_pools):
        """Consecuencia aceptada del diseño: sin gestion de pools no hay
        reinicio, porque el restart forma parte de aplicar el stratum."""
        manager, api, _ = construir(False)
        manager.connect_and_configure()
        api.restart.assert_not_called()

    @patch("tuning_manager.get_fastest_pools")
    def test_no_mide_latencias(self, fake_pools):
        """Lo importante no es solo no escribir: get_fastest_pools no debe ni
        invocarse, porque abre conexiones a pools de internet."""
        manager, api, _ = construir(False)
        manager.connect_and_configure()
        fake_pools.assert_not_called()

    @patch("tuning_manager.get_fastest_pools")
    def test_si_ajusta_voltaje_y_frecuencia(self, fake_pools):
        """El tuning es la razon de ser del programa: se hace en ambos modos."""
        manager, api, config = construir(False)
        manager.connect_and_configure()
        api.set_settings.assert_called_once_with(
            config["INITIAL_VOLTAGE"], config["INITIAL_FREQUENCY"]
        )

    @patch("tuning_manager.get_fastest_pools")
    def test_lee_el_estado_del_miner(self, fake_pools):
        """Aunque no gestione pools, necesita la MAC para las metricas."""
        manager, api, _ = construir(False)
        manager.connect_and_configure()
        api.get_system_info.assert_called()
        self.assertEqual(manager.mac_address, SYSTEM_INFO["macAddr"])

    @patch("tuning_manager.get_fastest_pools")
    def test_ignora_el_stratum_de_la_linea_de_comandos(self, fake_pools):
        """Si el usuario no ha activado la gestion de pools, ni siquiera un
        --primary-stratum explicito debe reconfigurar el miner."""
        primary = {"hostname": "solo.ckpool.org", "port": 3333, "user": "u1"}
        backup = {"hostname": "pool.example.com", "port": 3333, "user": "u2"}
        manager, api, _ = construir(
            False, primary_stratum=primary, backup_stratum=backup
        )
        manager.connect_and_configure()
        api.set_stratum.assert_not_called()
        fake_pools.assert_not_called()


class TestActivadoGestionaPools(unittest.TestCase):
    """Con manage_pools=True el comportamiento es el de siempre."""

    def setUp(self):
        """Aplicar el stratum incluye un time.sleep(1) para dar tiempo al miner.
        En un test no aporta nada y multiplica la duracion, asi que se anula."""
        parche = patch("tuning_manager.time.sleep")
        parche.start()
        self.addCleanup(parche.stop)

    @patch("tuning_manager.get_fastest_pools")
    def test_configura_stratum_desde_cli(self, fake_pools):
        primary = {"hostname": "solo.ckpool.org", "port": 3333, "user": "u1"}
        backup = {"hostname": "pool.example.com", "port": 3333, "user": "u2"}
        manager, api, _ = construir(
            True, primary_stratum=primary, backup_stratum=backup
        )
        manager.connect_and_configure()
        api.set_stratum.assert_called_once()
        # Con stratum explicito no hace falta medir latencias.
        fake_pools.assert_not_called()

    @patch("tuning_manager.get_fastest_pools")
    def test_reinicia_el_miner(self, fake_pools):
        primary = {"hostname": "solo.ckpool.org", "port": 3333, "user": "u1"}
        backup = {"hostname": "pool.example.com", "port": 3333, "user": "u2"}
        manager, api, _ = construir(
            True, primary_stratum=primary, backup_stratum=backup
        )
        manager.connect_and_configure()
        api.restart.assert_called_once()

    @patch("tuning_manager.get_fastest_pools")
    def test_ajusta_voltaje_y_frecuencia(self, fake_pools):
        primary = {"hostname": "solo.ckpool.org", "port": 3333, "user": "u1"}
        backup = {"hostname": "pool.example.com", "port": 3333, "user": "u2"}
        manager, api, config = construir(
            True, primary_stratum=primary, backup_stratum=backup
        )
        manager.connect_and_configure()
        api.set_settings.assert_called_once_with(
            config["INITIAL_VOLTAGE"], config["INITIAL_FREQUENCY"]
        )

    @patch("tuning_manager.get_fastest_pools")
    def test_mide_latencias_si_no_hay_stratum_explicito(self, fake_pools):
        """Sin stratum por CLI ni en la configuracion, mide y elige los mas
        rapidos: el camino que --manage-pools existe para autorizar."""
        fake_pools.return_value = [
            {"hostname": "rapido.example.com", "port": 3333, "user": "u1"},
            {"hostname": "segundo.example.com", "port": 3333, "user": "u2"},
        ]
        manager, api, config = construir(True)
        config.pop("PRIMARY_STRATUM", None)
        config.pop("BACKUP_STRATUM", None)
        manager.connect_and_configure()
        fake_pools.assert_called_once()
        api.set_stratum.assert_called_once()


class TestConfiguracion(unittest.TestCase):
    def test_los_yaml_de_chip_traen_la_clave_desactivada(self):
        """Todos los BM*.yaml deben declarar MANAGE_MINER_POOLS y en falso: si
        faltara, un usuario que actualice tendria el comportamiento antiguo sin
        saberlo."""
        import glob

        ficheros = sorted(glob.glob(os.path.join(REPO_ROOT, "BM*.yaml")))
        self.assertTrue(ficheros, "no se encontro ningun BM*.yaml")
        for path in ficheros:
            with self.subTest(fichero=os.path.basename(path)):
                with open(path) as fh:
                    data = yaml.safe_load(fh)
                self.assertIn("MANAGE_MINER_POOLS", data)
                self.assertFalse(data["MANAGE_MINER_POOLS"])

    def test_el_cli_expone_el_flag(self):
        import sys
        from unittest.mock import patch as p

        from cli import parse_arguments

        with p.object(sys, "argv", ["bitaxepid.py", "--ip", "192.168.1.1"]):
            self.assertFalse(parse_arguments().manage_pools)
        with p.object(
            sys, "argv", ["bitaxepid.py", "--ip", "192.168.1.1", "--manage-pools"]
        ):
            self.assertTrue(parse_arguments().manage_pools)


if __name__ == "__main__":
    unittest.main(verbosity=2)
