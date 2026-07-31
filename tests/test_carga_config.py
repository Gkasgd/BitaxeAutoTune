#!/usr/bin/env python3
"""Tests de que un fichero de configuracion que falta no pasa desapercibido.

`load_config` fusiona el YAML del chip con un YAML de usuario opcional. En el
codigo original, si la ruta pasada con --config no existia, se ignoraba en
silencio y el programa seguia con los limites del YAML del chip.

Eso importa porque el fichero de usuario es justo donde se bajan MAX_VOLTAGE y
MAX_FREQUENCY. Medido: con `--config /no/existe/perfil.yaml` y BM1370.yaml
debajo, la configuracion resultante tenia MAX_VOLTAGE=1250 y MAX_FREQUENCY=625
(los de fabrica) sin una sola linea de log. Una ruta mal escrita, o un montaje
de contenedor equivocado, dejaba al miner sin los topes que se creian puestos.

Ejecutar:  python3 -m unittest tests.test_carga_config -v
No necesita miner ni red.
"""

import os
import tempfile
import unittest

from config import YamlConfigLoader, load_config

CHIP = """
INITIAL_VOLTAGE: 1150
MIN_VOLTAGE: 1000
MAX_VOLTAGE: 1250
INITIAL_FREQUENCY: 550
MIN_FREQUENCY: 400
MAX_FREQUENCY: 625
"""

PERFIL_SEGURO = """
MAX_VOLTAGE: 1150
MAX_FREQUENCY: 500
"""


class BaseConFicheros(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.chip = self.escribir("BM1370.yaml", CHIP)  # el nombre da igual: se pasa la ruta
        self.loader = YamlConfigLoader()

    def escribir(self, nombre, contenido):
        ruta = os.path.join(self.dir.name, nombre)
        with open(ruta, "w") as fh:
            fh.write(contenido)
        return ruta


class TestFicheroDeUsuarioQueFalta(BaseConFicheros):
    """El caso del bug: pedir un fichero que no esta."""

    def test_termina_en_lugar_de_ignorarlo(self):
        with self.assertRaises(SystemExit) as ctx:
            load_config(self.loader, self.chip, os.path.join(self.dir.name, "no.yaml"))
        self.assertEqual(ctx.exception.code, 1)

    def test_no_arranca_con_los_limites_de_fabrica(self):
        """Lo que de verdad se quiere evitar: seguir con 1250mV creyendo 1150."""
        try:
            config = load_config(
                self.loader, self.chip, os.path.join(self.dir.name, "no.yaml")
            )
        except SystemExit:
            return  # correcto: no se llega a usar ninguna configuracion
        self.fail(
            f"siguio adelante con MAX_VOLTAGE={config.get('MAX_VOLTAGE')}, "
            "los limites de fabrica"
        )

    def test_avisa_en_el_log(self):
        with self.assertLogs("config", level="ERROR") as captura:
            with self.assertRaises(SystemExit):
                load_config(
                    self.loader, self.chip, os.path.join(self.dir.name, "no.yaml")
                )
        self.assertIn("no.yaml", "\n".join(captura.output))


class TestFicheroDeUsuarioVacio(BaseConFicheros):
    """Un fichero que existe pero no aporta nada es el mismo problema."""

    def test_vacio_termina(self):
        vacio = self.escribir("vacio.yaml", "")
        with self.assertRaises(SystemExit):
            load_config(self.loader, self.chip, vacio)

    def test_ilegible_termina(self):
        roto = self.escribir("roto.yaml", "esto: [no cierra\n")
        with self.assertRaises(SystemExit):
            load_config(self.loader, self.chip, roto)


class TestElCaminoNormalSigueFuncionando(BaseConFicheros):
    """Endurecer el error no debe romper el uso correcto."""

    def test_fusiona_y_los_limites_del_usuario_ganan(self):
        seguro = self.escribir("safe.yaml", PERFIL_SEGURO)
        config = load_config(self.loader, self.chip, seguro)
        self.assertEqual(config["MAX_VOLTAGE"], 1150)
        self.assertEqual(config["MAX_FREQUENCY"], 500)
        self.assertEqual(config["MIN_VOLTAGE"], 1000, "lo no declarado se hereda")

    def test_sin_fichero_de_usuario_no_es_un_error(self):
        """--config es opcional: no pasarlo debe seguir siendo valido."""
        config = load_config(self.loader, self.chip, None)
        self.assertEqual(config["MAX_VOLTAGE"], 1250)

    def test_chip_que_falta_sigue_terminando(self):
        with self.assertRaises(SystemExit):
            load_config(self.loader, os.path.join(self.dir.name, "BM9999.yaml"), None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
