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


def estrategia(voltage_step=10, frequency_step=25, target_temp=55.0,
               power_limit=15.0, error_target=None, temp_margin=2.0,
               estable_para_bajar=3):
    return PIDTuningStrategy(
        min_voltage=MIN_V, max_voltage=MAX_V,
        min_frequency=MIN_F, max_frequency=MAX_F,
        voltage_step=voltage_step, frequency_step=frequency_step,
        target_temp=target_temp, power_limit=power_limit,
        temp_margin=temp_margin, error_target=error_target,
        estable_para_bajar=estable_para_bajar,
    )


class TestNuncaSuperaElMaximo(unittest.TestCase):
    """El caso que importa: ninguna combinacion debe proponer mas del maximo."""

    def test_voltaje_no_alineado_con_el_paso(self):
        """1145 mV con paso 10 y maximo 1150: sumar un paso daria 1155.

        Es el caso concreto que fallaba. current_voltage < max_voltage es
        cierto (1145 < 1150), asi que la rama se activaba y sumaba entero.
        """
        s = estrategia(voltage_step=10, error_target=2.0)
        # Frecuencia ya en el maximo y errores altos: activa la rama que sube
        # voltaje, que es la que sumaba el paso entero sin recortar.
        v, f = s.apply_strategy(current_voltage=1145, current_frequency=MAX_F,
                                temp=40, power=5, error_percent=9.0)
        self.assertLessEqual(v, MAX_V, f"propuso {v}mV con maximo {MAX_V}mV")
        self.assertLessEqual(f, MAX_F, f"propuso {f}MHz con maximo {MAX_F}MHz")

    def test_paso_grande_desde_justo_debajo(self):
        """Con un paso de 20 el desbordamiento es mayor: 1145 -> 1165."""
        s = estrategia(voltage_step=20, error_target=2.0)
        v, _ = s.apply_strategy(current_voltage=1145, current_frequency=MAX_F,
                                temp=40, power=5, error_percent=9.0)
        self.assertLessEqual(v, MAX_V, f"propuso {v}mV con maximo {MAX_V}mV")

    def test_barrido_de_voltajes_y_pasos(self):
        """Ninguna combinacion de voltaje inicial y paso debe superar el maximo.

        Se barre tambien por encima del maximo: la estrategia no debe empeorar
        un valor que ya llega fuera de rango. El arranque se valida en
        config.py, pero la estrategia no confia en eso.
        """
        for step in (5, 10, 20, 25):
            for volt in range(MIN_V, MAX_V + 60, 5):
                # error_percent alto activa la rama que sube voltaje, que es la
                # que podia desbordar; el resto de ramas se cubren aparte.
                with self.subTest(step=step, volt=volt):
                    s = estrategia(voltage_step=step, error_target=2.0)
                    v, f = s.apply_strategy(
                        current_voltage=volt, current_frequency=MAX_F,
                        temp=40, power=5, error_percent=9.0,
                    )
                    self.assertLessEqual(v, MAX_V)
                    self.assertLessEqual(f, MAX_F)

    def test_subida_de_voltaje_por_errores(self):
        """La rama que sube voltaje: errores por encima del objetivo."""
        s = estrategia(voltage_step=10, error_target=2.0)
        v, _ = s.apply_strategy(current_voltage=1145, current_frequency=450,
                                temp=40, power=5,
                                error_percent=9.0)
        self.assertLessEqual(v, MAX_V, f"propuso {v}mV con maximo {MAX_V}mV")
        self.assertGreater(v, 1145, "no subio el voltaje con errores altos")


class TestNuncaBajaDelMinimo(unittest.TestCase):
    """El lado simetrico: bajar por temperatura o potencia tampoco se pasa."""

    def test_bajada_por_temperatura(self):
        for step in (5, 10, 20, 25):
            for volt in range(MIN_V - 20, MIN_V + 30, 5):
                with self.subTest(step=step, volt=volt):
                    s = estrategia(voltage_step=step)
                    v, f = s.apply_strategy(
                        current_voltage=volt, current_frequency=MIN_F,
                        temp=80, power=5,
                    )
                    self.assertGreaterEqual(v, min(MIN_V, volt))
                    self.assertGreaterEqual(f, MIN_F)

    def test_bajada_por_potencia(self):
        s = estrategia(voltage_step=10)
        v, _ = s.apply_strategy(current_voltage=MIN_V, current_frequency=450,
                                temp=40, power=100)
        self.assertGreaterEqual(v, MIN_V, f"propuso {v}mV con minimo {MIN_V}mV")


class TestElTuningSigueFuncionando(unittest.TestCase):
    """Recortar no debe convertir la estrategia en un no-op."""

    def test_sube_frecuencia_cuando_hay_margen(self):
        """Con margen de sobra, la subida ocurre y es de un paso."""
        s = estrategia(voltage_step=10)
        _, f = s.apply_strategy(current_voltage=1100, current_frequency=450,
                                temp=40, power=5)
        self.assertEqual(f, 475, "no subio la frecuencia habiendo margen")

    def test_baja_frecuencia_por_temperatura(self):
        s = estrategia(voltage_step=10)
        _, f = s.apply_strategy(current_voltage=1100, current_frequency=475,
                                temp=80, power=5)
        self.assertEqual(f, 450, "la temperatura debe bajar la frecuencia un paso")


class TestElHashrateNoDecide(unittest.TestCase):
    """El hashrate es un resultado, no un objetivo: no debe influir en nada."""

    def test_misma_decision_con_hashrate_absurdo(self):
        """Dos hashrates opuestos y ninguno: misma decision.

        `hashrate` se sigue aceptando por compatibilidad de firma, pero se
        descarta. Pasarlo no debe cambiar nada, y omitirlo tampoco.
        """
        for temp, power, freq in ((80, 5, 475), (40, 100, 475), (40, 5, 450)):
            with self.subTest(temp=temp, power=power, freq=freq):
                comun = dict(current_voltage=1100, current_frequency=freq,
                             temp=temp, power=power)
                bajo = estrategia().apply_strategy(**comun, hashrate=0)
                alto = estrategia().apply_strategy(**comun, hashrate=999999)
                sin = estrategia().apply_strategy(**comun)
                self.assertEqual(bajo, alto,
                                 f"el hashrate cambio la decision: {bajo} vs {alto}")
                self.assertEqual(bajo, sin,
                                 f"omitir el hashrate cambio la decision: {sin}")

    def test_hashrate_por_encima_del_setpoint_no_impide_recuperar(self):
        """El bug reportado: bajar por calor y no volver a subir NUNCA.

        La unica rama que subia frecuencia estaba dentro de
        `elif hashrate < setpoint`. Con el hashrate cumpliendo el setpoint el
        tuner caia en un `else` que no proponia nada, asi que los MHz que quito
        la temperatura no volvian jamas. Y era el caso normal: se recomienda
        poner HASHRATE_SETPOINT por debajo de la media medida.
        """
        s = estrategia(voltage_step=10)
        # 1) hace calor: baja un paso
        _, f = s.apply_strategy(current_voltage=1100, current_frequency=475,
                                temp=80, power=5)
        self.assertEqual(f, 450, "deberia haber bajado por temperatura")
        # 2) el calor pasa, el hashrate SIGUE por encima del setpoint
        _, f = s.apply_strategy(current_voltage=1100, current_frequency=f,
                                temp=40, power=5)
        self.assertEqual(f, 475, "no recupero la frecuencia que quito el calor")


class TestNuncaMasDeUnPaso(unittest.TestCase):
    """Ninguna decision debe mover mas de un paso ni dos palancas a la vez."""

    def test_un_solo_paso_y_una_sola_palanca(self):
        casos = [
            dict(temp=80, power=5, error_percent=None),    # temperatura
            dict(temp=40, power=100, error_percent=None),  # potencia
            dict(temp=40, power=5, error_percent=9.0),     # errores altos
            dict(temp=40, power=5, error_percent=0.1),     # margen -> sube
            dict(temp=40, power=5, error_percent=1.8),     # dentro de histeresis
        ]
        for caso in casos:
            for freq in (MIN_F, 450, MAX_F):
                with self.subTest(freq=freq, **caso):
                    s = estrategia(voltage_step=10, error_target=2.0)
                    v0, f0 = 1100, freq
                    v, f = s.apply_strategy(current_voltage=v0,
                                            current_frequency=f0,
                                            **caso)
                    self.assertLessEqual(abs(v - v0), 10, f"salto de voltaje {v0}->{v}")
                    self.assertLessEqual(abs(f - f0), 25, f"salto de frecuencia {f0}->{f}")
                    self.assertFalse(v != v0 and f != f0,
                                     f"movio las dos palancas: {v0}->{v}, {f0}->{f}")

    def test_no_salta_al_valor_absoluto_del_pid(self):
        """El segundo defecto: `new_frequency = proposed_frequency` adoptaba
        `Kp*error + integral`, que no es una frecuencia fisica. Desde 500 MHz
        con el integral anclado abajo, la propuesta podia ser 400."""
        s = estrategia(voltage_step=10, frequency_step=25)
        _, f = s.apply_strategy(current_voltage=1100, current_frequency=MAX_F,
                                temp=40, power=5)
        self.assertGreaterEqual(f, MAX_F - 25,
                                f"salto brusco hacia abajo: {MAX_F} -> {f}")


class TestSinLecturaDeErrores(unittest.TestCase):
    """Sin objetivo o sin lectura, el criterio de errores se omite."""

    def test_sin_objetivo_configurado_sigue_recuperando(self):
        s = estrategia(error_target=None)
        _, f = s.apply_strategy(current_voltage=1100, current_frequency=450,
                                temp=40, power=5)
        self.assertEqual(f, 475, "sin objetivo de errores deberia recuperar igual")

    def test_error_percent_none_no_cuenta_como_cero(self):
        """None no debe leerse como 0%: eso autorizaria subidas a ciegas...
        pero tampoco debe bloquear la recuperacion por temperatura."""
        s = estrategia(error_target=2.0)
        _, f = s.apply_strategy(current_voltage=1100, current_frequency=450,
                                temp=40, power=5,
                                error_percent=None)
        self.assertEqual(f, 475, "sin lectura deberia decidir por temperatura")

    def test_errores_altos_manda_sobre_el_margen_termico(self):
        """Con errores altos NO se sube frecuencia aunque sobre temperatura."""
        s = estrategia(error_target=2.0)
        _, f = s.apply_strategy(current_voltage=MAX_V, current_frequency=450,
                                temp=30, power=5,
                                error_percent=9.0)
        self.assertLess(f, 475, "subio frecuencia con los errores por encima")

    def test_sin_lectura_no_baja_voltaje(self):
        """Sin objetivo o sin lectura NO se busca el minimo de voltaje.

        Bajar voltaje sin saber los errores es hacerlo a ciegas: None no debe
        leerse como "0%, todo bien".
        """
        for objetivo, lectura in ((None, None), (None, 0.1), (2.0, None)):
            with self.subTest(error_target=objetivo, error_percent=lectura):
                s = estrategia(error_target=objetivo, estable_para_bajar=1)
                v, _ = s.apply_strategy(current_voltage=1100,
                                        current_frequency=MAX_F,
                                        temp=40, power=5,
                                        error_percent=lectura)
                self.assertEqual(v, 1100, "bajo voltaje sin conocer los errores")


class TestBuscaElVoltajeMinimo(unittest.TestCase):
    """Estable y sin errores: se baja voltaje para buscar el minimo."""

    def test_baja_voltaje_tras_las_muestras_estables(self):
        """No en la primera muestra tranquila: errorPercentage es ruidoso y en
        un BM1370 recorre casi 3 puntos con el hardware quieto. Se exigen N
        muestras seguidas antes de tocar nada."""
        s = estrategia(voltage_step=10, error_target=2.0, estable_para_bajar=3)
        v = 1100
        vistos = []
        for _ in range(3):
            v, _ = s.apply_strategy(current_voltage=v, current_frequency=MAX_F,
                                    temp=40, power=5, error_percent=0.1)
            vistos.append(v)
        self.assertEqual(vistos, [1100, 1100, 1090],
                         f"esperaba dos esperas y una bajada, salio {vistos}")

    def test_el_contador_se_reinicia_si_dejo_de_estar_estable(self):
        """Dos muestras tranquilas, una con errores, y vuelta a empezar."""
        s = estrategia(voltage_step=10, error_target=2.0, estable_para_bajar=3)
        v = 1100
        for _ in range(2):
            v, _ = s.apply_strategy(current_voltage=v, current_frequency=MAX_F,
                                    temp=40, power=5, error_percent=0.1)
        self.assertEqual(v, 1100)
        # una muestra con errores altos: sube voltaje y reinicia el contador
        v, _ = s.apply_strategy(current_voltage=v, current_frequency=MAX_F,
                                temp=40, power=5, error_percent=9.0)
        self.assertEqual(v, 1110, "deberia haber subido por errores")
        # la siguiente muestra tranquila NO debe bajar: el contador iba a cero
        v, _ = s.apply_strategy(current_voltage=v, current_frequency=MAX_F,
                                temp=40, power=5, error_percent=0.1)
        self.assertEqual(v, 1110, "bajo voltaje sin acumular muestras estables")

    def test_no_baja_por_debajo_del_minimo(self):
        s = estrategia(voltage_step=10, error_target=2.0, estable_para_bajar=1)
        v = MIN_V
        for _ in range(5):
            v, _ = s.apply_strategy(current_voltage=v, current_frequency=MAX_F,
                                    temp=40, power=5, error_percent=0.1)
            self.assertGreaterEqual(v, MIN_V, f"bajo de {MIN_V}mV a {v}mV")

    def test_la_frecuencia_va_antes_que_el_ahorro(self):
        """Con frecuencia por recuperar, se sube frecuencia y no se baja
        voltaje: el ahorro es lo ultimo, cuando ya no queda nada que ganar."""
        s = estrategia(voltage_step=10, error_target=2.0, estable_para_bajar=1)
        v, f = s.apply_strategy(current_voltage=1100, current_frequency=450,
                                temp=40, power=5, error_percent=0.1)
        self.assertEqual((v, f), (1100, 475),
                         "deberia priorizar recuperar frecuencia")

    def test_converge_alrededor_del_minimo_estable(self):
        """El ciclo completo: baja hasta que aparecen errores, la prioridad 3 lo
        devuelve, y el ajuste queda oscilando alrededor del minimo estable."""
        s = estrategia(voltage_step=10, error_target=2.0, estable_para_bajar=1)
        umbral = 1070   # por debajo de esto el chip simulado da errores
        v = 1120
        historia = []
        for _ in range(12):
            errores = 0.1 if v >= umbral else 9.0
            v, _ = s.apply_strategy(current_voltage=v, current_frequency=MAX_F,
                                    temp=40, power=5, error_percent=errores)
            historia.append(v)
        self.assertGreaterEqual(min(historia), umbral - 10,
                                f"se fue muy por debajo del umbral: {historia}")
        self.assertLessEqual(max(historia[4:]), umbral + 10,
                             f"no converge, sigue alto: {historia}")


class TestNoArrastraDecimales(unittest.TestCase):
    """Lo que sale va a la API del miner: mV y MHz enteros, siempre.

    El fallo: un valor con decimales entraba (de la web de AxeOS, que permite
    valores libres, o de un `--frequency` con coma) y salia igual. La estrategia
    le suma y resta pasos enteros encima, asi que el desfase no se corregia nunca
    y el ajuste recorria 493.75, 498.75, 503.75... para el resto de la ejecucion.
    Ninguno de esos valores es uno que el usuario haya configurado.
    """

    def test_la_salida_siempre_es_entera(self):
        casos = [
            dict(temp=80, power=5, error_percent=None),    # baja frecuencia
            dict(temp=40, power=100, error_percent=None),  # baja voltaje
            dict(temp=40, power=5, error_percent=9.0),     # sube voltaje
            dict(temp=40, power=5, error_percent=0.1),     # sube frecuencia
            dict(temp=40, power=5, error_percent=1.8),     # no mueve nada
        ]
        for caso in casos:
            for v0, f0 in ((1100.5, 493.75), (1099.9, 450.25), (1100, 475)):
                with self.subTest(v0=v0, f0=f0, **caso):
                    s = estrategia(voltage_step=10, error_target=2.0)
                    v, f = s.apply_strategy(current_voltage=v0,
                                            current_frequency=f0, **caso)
                    self.assertIsInstance(v, int, f"voltaje no entero: {v!r}")
                    self.assertIsInstance(f, int, f"frecuencia no entera: {f!r}")

    def test_el_decimal_no_sobrevive_al_lazo(self):
        """Entrando con 493.75 MHz, ninguna muestra posterior debe tener coma."""
        s = estrategia(voltage_step=10, frequency_step=25, error_target=2.0)
        v, f = 1100.5, 493.75
        for _ in range(10):
            v, f = s.apply_strategy(current_voltage=v, current_frequency=f,
                                    temp=40, power=5, error_percent=0.1)
            self.assertEqual(f, int(f), f"quedo un decimal en la frecuencia: {f}")
            self.assertEqual(v, int(v), f"quedo un decimal en el voltaje: {v}")


class TestCuantizarAjusteExterno(unittest.TestCase):
    """Lo que llega de AxeOS se lleva a la rejilla antes de adoptarlo."""

    def test_a_rejilla(self):
        from tuning_manager import _a_rejilla

        # frecuencia fuera de rejilla -> al multiplo de paso mas cercano
        self.assertEqual(_a_rejilla(493.75, 25), 500)
        self.assertEqual(_a_rejilla(486.0, 25), 475)
        self.assertEqual(_a_rejilla(1195.4, 10), 1200)
        # ya en rejilla: no se toca
        self.assertEqual(_a_rejilla(475, 25), 475)
        # sin paso util: al menos entero, nunca peor que antes
        for paso in (0, None, "x"):
            with self.subTest(paso=paso):
                self.assertEqual(_a_rejilla(493.75, paso), 494)
        # un valor que no es numero se devuelve tal cual, sin romper el bucle
        self.assertIsNone(_a_rejilla(None, 25))


if __name__ == "__main__":
    unittest.main(verbosity=2)
