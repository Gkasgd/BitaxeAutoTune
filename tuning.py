#!/usr/bin/env python3
"""
Estrategia de tuning por limites para el voltaje y la frecuencia del miner.

Decide con TEMPERATURA, POTENCIA y ERRORES DE HARDWARE. El hashrate NO
interviene: no se mide, no se compara y no se guarda. Es un resultado de la
frecuencia y el voltaje, no un objetivo que perseguir.

Antes si lo era, con dos controladores PID persiguiendo HASHRATE_SETPOINT, y de
ahi salian dos fallos:

  - La unica rama capaz de SUBIR la frecuencia estaba encerrada en
    `elif hashrate < setpoint`. En cuanto el miner cumplia el setpoint, el tuner
    caia en un `else` que no proponia nada, asi que los MHz que quitaba un pico
    de calor no volvian NUNCA. Y era el caso normal, porque se recomendaba poner
    el setpoint POR DEBAJO de la media medida para que el ruido no sacara al
    tuner de "System stable": bajarlo para evitar oscilacion era justo lo que
    cerraba el camino de vuelta.
  - Esa rama hacia `new_frequency = proposed_frequency`, o sea adoptaba el valor
    ABSOLUTO del PID, que no es una frecuencia fisica sino `Kp*error + integral`.
    Con KP=0.2 harian falta 4000 GH/s de error para pedir 800 MHz por via
    proporcional, asi que mandaba el integral, anclado en MIN_FREQUENCY al
    arrancar: la primera reaccion podia ser un salto de 825 MHz a 485.

Las reglas ahora, en orden de prioridad:

  1. Temperatura por encima de TARGET_TEMP  -> bajar frecuencia.
  2. Potencia por encima del limite         -> bajar voltaje.
  3. Errores por encima del objetivo        -> subir voltaje.
  4. Margen de temperatura y de errores     -> subir frecuencia.
  5. Estable y sin errores                  -> bajar voltaje (buscar el minimo).

Invariantes que el codigo mantiene y los tests fijan: nunca se mueve mas de UN
paso, ni mas de UNA palanca, por muestra; y toda decision es RELATIVA al ajuste
actual, nunca un salto a un valor absoluto calculado.

La clase conserva el nombre `PIDTuningStrategy` y sigue aceptando las ganancias
PID_* y `setpoint` para no romper la firma publica ni obligar a reescribir los
YAML de todo el mundo, pero ya no construye ningun PID: no queda ningun
controlador que ajustar. Los parametros se ignoran y se avisa por log.

Uso:
    from tuning import PIDTuningStrategy

    strategy = PIDTuningStrategy(min_voltage=..., max_voltage=..., ...)
    new_voltage, new_frequency = strategy.apply_strategy(
        current_voltage, current_frequency, temp, power, error_percent
    )

Dependencias:
    - Terceros: rich (a traves de ui_rich, para los mensajes)
    - Estandar: logging, typing
"""

import logging
from typing import Optional, Tuple

from ui_rich import (
    PRIMARY_ACCENT,
    SECONDARY_ACCENT,
    WARNING_COLOR,
    console,
)


class PIDTuningStrategy:
    """Estrategia por limites: temperatura, potencia y errores de hardware.

    El nombre lleva "PID" por compatibilidad historica. No hay ningun
    controlador PID dentro.
    """

    def __init__(
        self,
        min_voltage: float,
        max_voltage: float,
        min_frequency: float,
        max_frequency: float,
        voltage_step: float,
        frequency_step: float,
        target_temp: float,
        power_limit: float,
        temp_margin: float = 2.0,
        error_target: Optional[float] = None,
        error_hysteresis: float = 0.5,
        estable_para_bajar: int = 3,
        # --- Ignorados, aceptados por compatibilidad --------------------------
        # Estaban en la firma cuando la estrategia perseguia un setpoint de
        # hashrate con dos PID. Se siguen aceptando para que los YAML existentes
        # y quien construya la clase con argumentos posicionales no se rompan.
        kp_freq: Optional[float] = None,
        ki_freq: Optional[float] = None,
        kd_freq: Optional[float] = None,
        kp_volt: Optional[float] = None,
        ki_volt: Optional[float] = None,
        kd_volt: Optional[float] = None,
        setpoint: Optional[float] = None,
        sample_interval: Optional[float] = None,
    ) -> None:
        """
        Inicializar la estrategia con los limites de operacion.

        Args:
            min_voltage: Voltaje minimo permitido (mV).
            max_voltage: Voltaje maximo permitido (mV). Limite de seguridad.
            min_frequency: Frecuencia minima permitida (MHz).
            max_frequency: Frecuencia maxima permitida (MHz). Limite de seguridad.
            voltage_step: Cuanto se mueve el voltaje por decision (mV).
            frequency_step: Cuanto se mueve la frecuencia por decision (MHz).
            target_temp: Temperatura objetivo (C). Al pasarse, se baja.
            power_limit: Limite de potencia (W). Se compara con un margen del
                7.5%, asi que la rama actua por encima de power_limit * 1.075.
            temp_margin: Grados bajo target_temp exigidos para autorizar
                cualquier SUBIDA. Sin este margen, bajar al pasarse y subir en
                cuanto se cumple produce un ciclo de un paso arriba y otro abajo
                indefinidamente.
            error_target: Porcentaje de errores de hardware que no se quiere
                superar. None = no hay criterio de errores; entonces no se toca
                el voltaje por errores y las subidas dependen solo de la
                temperatura.
            error_hysteresis: Banda muerta bajo error_target, en puntos, que se
                exige para considerar que "sobra margen".
            estable_para_bajar: Muestras estables consecutivas exigidas antes de
                bajar el voltaje en busca del minimo. Bajar en la primera
                muestra tranquila hace que el tuner persiga el ruido de
                errorPercentage, que en un BM1370 recorre casi 3 puntos entre
                lecturas con el hardware quieto.
            kp_freq, ki_freq, kd_freq, kp_volt, ki_volt, kd_volt, setpoint,
            sample_interval: IGNORADOS. Restos de la epoca del PID sobre
                hashrate.
        """
        ignorados = {
            "kp_freq": kp_freq, "ki_freq": ki_freq, "kd_freq": kd_freq,
            "kp_volt": kp_volt, "ki_volt": ki_volt, "kd_volt": kd_volt,
            "setpoint": setpoint, "sample_interval": sample_interval,
        }
        recibidos = sorted(k for k, v in ignorados.items() if v is not None)
        if recibidos:
            # Un aviso y no un fallo: los YAML del proyecto declaran las
            # ganancias PID_* y validate_config las exige, asi que llegar aqui
            # es lo normal, no un error del usuario. Pero conviene que quede
            # dicho, para que nadie ajuste ganancias esperando algun efecto.
            logging.info(
                f"Parametros ignorados (ya no hay PID ni objetivo de hashrate): "
                f"{', '.join(recibidos)}"
            )

        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.min_frequency = min_frequency
        self.max_frequency = max_frequency
        self.voltage_step = voltage_step
        self.frequency_step = frequency_step
        self.target_temp = target_temp
        self.power_limit = power_limit
        self.temp_margin = temp_margin
        self.error_target = error_target
        self.error_hysteresis = error_hysteresis
        self.estable_para_bajar = max(1, int(estable_para_bajar))
        self._muestras_estables = 0

    def apply_strategy(
        self,
        current_voltage: float,
        current_frequency: float,
        temp: float,
        power: float = 0.0,
        error_percent: Optional[float] = None,
        hashrate: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Devolver el siguiente par (voltaje, frecuencia) a aplicar.

        `hashrate` se acepta y se DESCARTA. Esta en la firma solo para que una
        llamada antigua que lo pase por nombre no falle.
        """
        new_voltage = current_voltage
        new_frequency = current_frequency

        limite_potencia = self.power_limit * 1.075
        margen_termico = temp <= self.target_temp - self.temp_margin

        # Los errores solo pesan si hay objetivo configurado Y lectura del
        # miner. Sin una de las dos cosas el criterio se omite, en vez de
        # suponer un 0% que autorizaria bajar voltaje a ciegas.
        errores_conocidos = self.error_target is not None and error_percent is not None
        errores_altos = errores_conocidos and error_percent > self.error_target
        # "Sin errores" es por debajo de la banda de histeresis, no exactamente
        # cero: errorPercentage nunca se queda quieto.
        sin_errores = errores_conocidos and (
            error_percent < self.error_target - self.error_hysteresis
        )

        # --- Prioridad 1: temperatura ---------------------------------------
        # La frecuencia es la palanca termica: baja el calor sin comprometer la
        # estabilidad, que es lo que sostiene el voltaje.
        if temp > self.target_temp:
            self._muestras_estables = 0
            if current_frequency > self.min_frequency:
                new_frequency = current_frequency - self.frequency_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando frecuencia a {new_frequency}MHz "
                    f"por temperatura {temp}C > {self.target_temp}C[/]"
                )
            elif current_voltage > self.min_voltage:
                new_voltage = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando voltaje a {new_voltage}mV por "
                    f"temperatura {temp}C > {self.target_temp}C "
                    f"(la frecuencia ya esta en el minimo)[/]"
                )
            else:
                console.print(
                    f"[{WARNING_COLOR}]Temperatura {temp}C > {self.target_temp}C "
                    f"pero ya se esta en el minimo "
                    f"{self.min_voltage}mV/{self.min_frequency}MHz: "
                    f"no queda margen para bajar[/]"
                )
        # --- Prioridad 2: potencia ------------------------------------------
        elif power > limite_potencia:
            self._muestras_estables = 0
            if current_voltage > self.min_voltage:
                new_voltage = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando voltaje a {new_voltage}mV "
                    f"por potencia {power}W > {limite_potencia:.1f}W[/]"
                )
            elif current_frequency > self.min_frequency:
                new_frequency = current_frequency - self.frequency_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando frecuencia a {new_frequency}MHz "
                    f"por potencia {power}W > {limite_potencia:.1f}W "
                    f"(el voltaje ya esta en el minimo)[/]"
                )
        # --- Prioridad 3: errores por encima del objetivo -------------------
        # Se sube VOLTAJE, que es lo que estabiliza. Solo cuando el voltaje ya
        # no tiene sitio se baja frecuencia: bajar voltaje aqui empeoraria los
        # errores justo cuando hace falta estabilidad.
        elif errores_altos:
            self._muestras_estables = 0
            if current_voltage < self.max_voltage:
                new_voltage = min(
                    current_voltage + self.voltage_step, self.max_voltage
                )
                console.print(
                    f"[{SECONDARY_ACCENT}]Subiendo voltaje a {new_voltage}mV "
                    f"por errores {error_percent}% > {self.error_target}%[/]"
                )
            elif current_frequency > self.min_frequency:
                new_frequency = current_frequency - self.frequency_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando frecuencia a {new_frequency}MHz "
                    f"por errores {error_percent}% > {self.error_target}% "
                    f"(el voltaje ya esta en el maximo {self.max_voltage}mV)[/]"
                )
            else:
                console.print(
                    f"[{WARNING_COLOR}]Errores {error_percent}% > "
                    f"{self.error_target}% con el voltaje al maximo y la "
                    f"frecuencia al minimo: el objetivo no es alcanzable "
                    f"dentro de los limites configurados[/]"
                )
        # --- Prioridad 4: recuperar frecuencia ------------------------------
        # El camino de vuelta. Si la temperatura bajo, la frecuencia sube.
        elif (
            margen_termico
            and current_frequency < self.max_frequency
            and (sin_errores or not errores_conocidos)
        ):
            self._muestras_estables = 0
            new_frequency = min(
                current_frequency + self.frequency_step, self.max_frequency
            )
            motivo = (
                f"errores {error_percent}% por debajo de "
                f"{self.error_target - self.error_hysteresis}%"
                if errores_conocidos
                else "sin lectura de errores"
            )
            console.print(
                f"[{SECONDARY_ACCENT}]Subiendo frecuencia a {new_frequency}MHz: "
                f"temp {temp}C <= {self.target_temp - self.temp_margin}C "
                f"y {motivo}[/]"
            )
        # --- Prioridad 5: buscar el voltaje minimo --------------------------
        # Estable, sin errores y con la frecuencia ya en el techo: lo unico que
        # queda por mejorar es el consumo. Se baja voltaje hasta que los errores
        # aparezcan; cuando aparezcan, la prioridad 3 lo devuelve a su sitio, y
        # entre las dos el ajuste queda oscilando alrededor del voltaje minimo
        # estable, que es justo el punto que se busca.
        elif sin_errores and current_voltage > self.min_voltage:
            self._muestras_estables += 1
            if self._muestras_estables >= self.estable_para_bajar:
                self._muestras_estables = 0
                new_voltage = max(
                    current_voltage - self.voltage_step, self.min_voltage
                )
                console.print(
                    f"[{SECONDARY_ACCENT}]Bajando voltaje a {new_voltage}mV: "
                    f"{self.estable_para_bajar} muestras estables con errores "
                    f"{error_percent}% por debajo de "
                    f"{self.error_target - self.error_hysteresis}% "
                    f"(buscando el minimo)[/]"
                )
            else:
                console.print(
                    f"[{PRIMARY_ACCENT}]Estable en {current_voltage}mV/"
                    f"{current_frequency}MHz "
                    f"({self._muestras_estables}/{self.estable_para_bajar} "
                    f"muestras para bajar voltaje)[/]"
                )
        else:
            self._muestras_estables = 0
            console.print(
                f"[{PRIMARY_ACCENT}]Estable en {current_voltage}mV/"
                f"{current_frequency}MHz (temp {temp}C, {power}W)[/]"
            )

        # Red final: por muy razonada que sea cada rama, lo que sale de aqui va
        # directo al hardware. Se recorta al rango configurado una ultima vez,
        # asi que MAX_VOLTAGE y MAX_FREQUENCY son un tope real y no una
        # intencion. Tambien cubre el caso de recibir un valor actual ya fuera
        # de rango: la estrategia no depende de que quien la llama le pase
        # valores sanos. El arranque se valida aparte, en config.py.
        clamped_voltage = max(self.min_voltage, min(self.max_voltage, new_voltage))
        clamped_frequency = max(
            self.min_frequency, min(self.max_frequency, new_frequency)
        )
        # Y se devuelven enteros: son mV y MHz que van a la API del miner, que no
        # aplica fracciones. Un decimal que entre (de la web de AxeOS o de un
        # --frequency con coma) se arrastraria sumando pasos enteros encima hasta
        # el final de la ejecucion.
        recortado = (
            clamped_voltage != new_voltage or clamped_frequency != new_frequency
        )
        clamped_voltage = int(round(clamped_voltage))
        clamped_frequency = int(round(clamped_frequency))
        if recortado:
            console.print(
                f"[{WARNING_COLOR}]Recortando a los limites seguros: "
                f"{new_voltage}mV/{new_frequency}MHz -> "
                f"{clamped_voltage}mV/{clamped_frequency}MHz "
                f"(limites {self.min_voltage}-{self.max_voltage}mV, "
                f"{self.min_frequency}-{self.max_frequency}MHz)[/]"
            )

        return clamped_voltage, clamped_frequency
