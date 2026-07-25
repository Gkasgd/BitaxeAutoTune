#!/usr/bin/env python3
"""Tests de que el valor inicial que se aplica al miner respeta los limites.

El primer set_settings del programa no viene de la estrategia de tuning: viene
de INITIAL_VOLTAGE / INITIAL_FREQUENCY, con los overrides --voltage/--frequency
aplicados encima. Se manda al miner en `_initialize_hardware`, antes de entrar
al bucle, asi que el recorte de `apply_strategy` no lo cubre.

El fallo estaba en el codigo original: `validate_config` comprobaba que las
claves existieran, nunca sus valores. Medido contra el miner simulado con
MAX_VOLTAGE=1150 y MAX_FREQUENCY=500: `--voltage 1250 --frequency 625` llegaba
al hardware tal cual.

Ejecutar:  python3 -m unittest tests.test_limites_arranque -v
No necesita miner ni red.
"""

import logging
import unittest

from config import clamp_initial_values

# Rango de referencia de los tests. Coincide a proposito con los topes seguros
# de safe-BM1370.yaml, que es el caso que motivo estos tests.
LIMITES = {
    "MIN_VOLTAGE": 1000,
    "MAX_VOLTAGE": 1150,
    "MIN_FREQUENCY": 400,
    "MAX_FREQUENCY": 500,
}


def config(voltage, frequency, **extra):
    c = dict(LIMITES)
    c["INITIAL_VOLTAGE"] = voltage
    c["INITIAL_FREQUENCY"] = frequency
    c.update(extra)
    return c


class TestRecortaPorArriba(unittest.TestCase):
    """El caso que importa: nada por encima del maximo llega al hardware."""

    def test_override_muy_por_encima(self):
        """--voltage 1250 --frequency 625 con topes 1150/500."""
        c = clamp_initial_values(config(1250, 625))
        self.assertEqual(c["INITIAL_VOLTAGE"], 1150)
        self.assertEqual(c["INITIAL_FREQUENCY"], 500)

    def test_apenas_por_encima(self):
        c = clamp_initial_values(config(1151, 501))
        self.assertEqual(c["INITIAL_VOLTAGE"], 1150)
        self.assertEqual(c["INITIAL_FREQUENCY"], 500)

    def test_heredado_del_yaml_del_chip(self):
        """El caso real y silencioso: bajar solo los MAX_ en un YAML propio.

        BM1370.yaml trae INITIAL_FREQUENCY 550 y INITIAL_VOLTAGE 1150. Un
        fichero de usuario que solo baja MAX_FREQUENCY a 500 hereda el 550.
        """
        c = clamp_initial_values(config(1150, 550))
        self.assertEqual(c["INITIAL_FREQUENCY"], 500)
        self.assertEqual(c["INITIAL_VOLTAGE"], 1150, "1150 esta en rango, no se toca")

    def test_barrido(self):
        for volt in range(1000, 1300, 10):
            for freq in range(400, 700, 25):
                with self.subTest(volt=volt, freq=freq):
                    c = clamp_initial_values(config(volt, freq))
                    self.assertLessEqual(c["INITIAL_VOLTAGE"], LIMITES["MAX_VOLTAGE"])
                    self.assertLessEqual(
                        c["INITIAL_FREQUENCY"], LIMITES["MAX_FREQUENCY"]
                    )


class TestRecortaPorAbajo(unittest.TestCase):
    """Simetrico: por debajo del minimo tampoco se aplica."""

    def test_por_debajo_del_minimo(self):
        c = clamp_initial_values(config(900, 300))
        self.assertEqual(c["INITIAL_VOLTAGE"], 1000)
        self.assertEqual(c["INITIAL_FREQUENCY"], 400)


class TestNoToqueteaLoQueEstaBien(unittest.TestCase):
    """Recortar no debe convertirse en cambiar valores validos."""

    def test_valores_en_rango_intactos(self):
        c = clamp_initial_values(config(1100, 450))
        self.assertEqual(c["INITIAL_VOLTAGE"], 1100)
        self.assertEqual(c["INITIAL_FREQUENCY"], 450)

    def test_los_extremos_son_validos(self):
        """El limite es alcanzable: max y min no se recortan a otra cosa."""
        c = clamp_initial_values(config(1150, 500))
        self.assertEqual(c["INITIAL_VOLTAGE"], 1150)
        self.assertEqual(c["INITIAL_FREQUENCY"], 500)
        c = clamp_initial_values(config(1000, 400))
        self.assertEqual(c["INITIAL_VOLTAGE"], 1000)
        self.assertEqual(c["INITIAL_FREQUENCY"], 400)

    def test_no_inventa_claves(self):
        c = clamp_initial_values(config(1100, 450))
        self.assertEqual(set(c), set(config(1100, 450)))


class TestClavesQueFaltan(unittest.TestCase):
    """Sin los limites no se puede recortar, y no es aqui donde se reporta."""

    def test_sin_limites_no_revienta(self):
        """validate_config ya informa de las claves que faltan; esto no debe
        adelantarsele con un KeyError."""
        c = {"INITIAL_VOLTAGE": 1250, "INITIAL_FREQUENCY": 625}
        self.assertEqual(clamp_initial_values(c), c)

    def test_sin_valores_iniciales_no_revienta(self):
        c = dict(LIMITES)
        self.assertEqual(clamp_initial_values(c), c)


class TestAvisa(unittest.TestCase):
    """Un recorte silencioso seria peor que el bug: hay que poder verlo."""

    def test_registra_warning_al_recortar(self):
        with self.assertLogs("config", level="WARNING") as captura:
            clamp_initial_values(config(1250, 625))
        texto = "\n".join(captura.output)
        self.assertIn("INITIAL_VOLTAGE", texto)
        self.assertIn("1150", texto)

    def test_no_avisa_cuando_no_recorta(self):
        logger = logging.getLogger("config")
        with self.assertLogs(logger, level="WARNING") as captura:
            logger.warning("centinela: assertLogs exige al menos un registro")
            clamp_initial_values(config(1100, 450))
        self.assertEqual(len(captura.output), 1, f"aviso de mas: {captura.output}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
