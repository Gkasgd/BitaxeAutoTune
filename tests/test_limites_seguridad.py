#!/usr/bin/env python3
"""Tests de que la estrategia nunca propone valores fuera de los limites.

MAX_VOLTAGE y MAX_FREQUENCY son limites de seguridad de hardware: el usuario los
pone para no cocer el chip. Una propuesta por encima del maximo no es un detalle
estetico, es exactamente lo que esos parametros existen para impedir.

El fallo que estos tests fijan estaba en el codigo original: las ramas que suben
voltaje comprobaban `current_voltage < self.max_voltage` y luego sumaban un paso
completo, sin recortar. Con max_voltage=1150, voltage_step=10 y un voltaje actual
de 1145 la propuesta era 1155 mV. Un voltaje que no es multiplo del paso es
normal: sale de INITIAL_VOLTAGE, del override --voltage, o de lo que ya tuviera
puesto el miner.

Ejecutar:  python3 -m unittest tests.test_limites_seguridad -v
No necesita miner ni red.
"""

import unittest

from tuning import PIDTuningStrategy

# Limites de seguridad usados en los tests. No coinciden con ningun BM*.yaml a
# proposito: lo que se comprueba es que la estrategia respeta los limites que le
# dan, no los de un modelo concreto.
MAX_V = 1150
MIN_V = 1000
MAX_F = 500
MIN_F = 400


def estrategia(voltage_step=10, frequency_step=25, setpoint=525, target_temp=55.0,
               power_limit=15.0):
    return PIDTuningStrategy(
        kp_freq=0.2, ki_freq=0.01, kd_freq=0.02,
        kp_volt=0.1, ki_volt=0.01, kd_volt=0.02,
        min_voltage=MIN_V, max_voltage=MAX_V,
        min_frequency=MIN_F, max_frequency=MAX_F,
        voltage_step=voltage_step, frequency_step=frequency_step,
        setpoint=setpoint, sample_interval=1,
        target_temp=target_temp, power_limit=power_limit,
    )


class TestNuncaSuperaElMaximo(unittest.TestCase):
    """El caso que importa: ninguna combinacion debe proponer mas del maximo."""

    def test_voltaje_no_alineado_con_el_paso(self):
        """1145 mV con paso 10 y maximo 1150: sumar un paso daria 1155.

        Es el caso concreto que fallaba. current_voltage < max_voltage es
        cierto (1145 < 1150), asi que la rama se activaba y sumaba entero.
        """
        s = estrategia(voltage_step=10)
        # hashrate muy por debajo del setpoint y frecuencia ya en el maximo:
        # activa las dos ramas que suben voltaje.
        v, f = s.apply_strategy(current_voltage=1145, current_frequency=MAX_F,
                                temp=40, hashrate=100, power=5)
        self.assertLessEqual(v, MAX_V, f"propuso {v}mV con maximo {MAX_V}mV")
        self.assertLessEqual(f, MAX_F, f"propuso {f}MHz con maximo {MAX_F}MHz")

    def test_paso_grande_desde_justo_debajo(self):
        """Con un paso de 20 el desbordamiento es mayor: 1145 -> 1165."""
        s = estrategia(voltage_step=20)
        v, _ = s.apply_strategy(current_voltage=1145, current_frequency=MAX_F,
                                temp=40, hashrate=100, power=5)
        self.assertLessEqual(v, MAX_V, f"propuso {v}mV con maximo {MAX_V}mV")

    def test_barrido_de_voltajes_y_pasos(self):
        """Ninguna combinacion de voltaje inicial y paso debe superar el maximo.

        Se barre tambien por encima del maximo: la estrategia no debe empeorar
        un valor que ya llega fuera de rango. El arranque se valida en
        config.py, pero la estrategia no confia en eso.
        """
        for step in (5, 10, 20, 25):
            for volt in range(MIN_V, MAX_V + 60, 5):
                with self.subTest(step=step, volt=volt):
                    s = estrategia(voltage_step=step)
                    v, f = s.apply_strategy(
                        current_voltage=volt, current_frequency=MAX_F,
                        temp=40, hashrate=100, power=5,
                    )
                    self.assertLessEqual(v, MAX_V)
                    self.assertLessEqual(f, MAX_F)

    def test_hashrate_apenas_por_debajo(self):
        """La otra rama que sube voltaje: hashrate < 85% del setpoint."""
        s = estrategia(voltage_step=10)
        v, _ = s.apply_strategy(current_voltage=1145, current_frequency=450,
                                temp=40, hashrate=100, power=5)
        self.assertLessEqual(v, MAX_V, f"propuso {v}mV con maximo {MAX_V}mV")


class TestNuncaBajaDelMinimo(unittest.TestCase):
    """El lado simetrico: bajar por temperatura o potencia tampoco se pasa."""

    def test_bajada_por_temperatura(self):
        for step in (5, 10, 20, 25):
            for volt in range(MIN_V - 20, MIN_V + 30, 5):
                with self.subTest(step=step, volt=volt):
                    s = estrategia(voltage_step=step)
                    v, f = s.apply_strategy(
                        current_voltage=volt, current_frequency=MIN_F,
                        temp=80, hashrate=100, power=5,
                    )
                    self.assertGreaterEqual(v, min(MIN_V, volt))
                    self.assertGreaterEqual(f, MIN_F)

    def test_bajada_por_potencia(self):
        s = estrategia(voltage_step=10)
        v, _ = s.apply_strategy(current_voltage=MIN_V, current_frequency=450,
                                temp=40, hashrate=100, power=100)
        self.assertGreaterEqual(v, MIN_V, f"propuso {v}mV con minimo {MIN_V}mV")


class TestElTuningSigueFuncionando(unittest.TestCase):
    """Recortar no debe convertir la estrategia en un no-op."""

    def test_sube_voltaje_cuando_hay_margen(self):
        """Con margen de sobra, la subida ocurre y es de un paso."""
        s = estrategia(voltage_step=10)
        v, _ = s.apply_strategy(current_voltage=1100, current_frequency=MAX_F,
                                temp=40, hashrate=100, power=5)
        self.assertGreater(v, 1100, "no subio el voltaje habiendo margen")
        self.assertLessEqual(v, MAX_V)

    def test_baja_frecuencia_por_temperatura(self):
        s = estrategia(voltage_step=10)
        _, f = s.apply_strategy(current_voltage=1100, current_frequency=475,
                                temp=80, hashrate=500, power=5)
        self.assertEqual(f, 450, "la temperatura debe bajar la frecuencia un paso")


if __name__ == "__main__":
    unittest.main(verbosity=2)
