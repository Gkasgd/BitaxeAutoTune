#!/usr/bin/env python3
"""
Estrategia de estabilidad: la temperatura manda y los errores de hardware
deciden el voltaje.

A diferencia de PIDTuningStrategy, aqui no hay ningun controlador PID y el
hashrate no interviene en ninguna decision. El objetivo no es alcanzar un
hashrate, es encontrar la frecuencia mas alta que el chip sostiene sin pasar de
un porcentaje de errores de hardware dado, y hacerlo con el voltaje mas bajo
posible. El hashrate util sale de eso como consecuencia, no como objetivo.

Orden de prioridad, de mayor a menor:

  1. TEMPERATURA. Si se pasa de TARGET_TEMP se baja, primero frecuencia y solo
     al llegar a MIN_FREQUENCY el voltaje. Manda sobre todo lo demas.
  2. POTENCIA. Si se pasa de POWER_LIMIT con su margen se baja la FRECUENCIA
     (no el voltaje, como hacia la estrategia PID): la potencia baja igual y la
     estabilidad no se toca.
  3. ERRORES DE HARDWARE. Deciden el voltaje.

Y tres estados, que recorren el procedimiento en ese orden:

  RAMPA           Subir frecuencia y voltaje a la vez, un paso por muestra,
                  hasta el tope de ambos o hasta acercarse a TARGET_TEMP. Se
                  llega asi al punto mas alto que la temperatura permite, que
                  es tambien el mas estable.
  BUSCAR_VOLTAJE  Bajar el voltaje paso a paso hasta que los errores tocan el
                  objetivo. Al pasarse, se vuelve un paso atras. El resultado
                  es el voltaje MINIMO que cumple el objetivo a esa frecuencia.
  OPTIMIZAR       Regimen permanente. Si los errores se pasan, subir voltaje.
                  Si sobra margen, subir frecuencia. Si sobra margen y la
                  frecuencia ya esta al tope, bajar voltaje. Es el "y asi
                  sucesivamente": el lazo converge a la frecuencia mas alta
                  sostenible y al voltaje mas bajo que la sostiene.

Por que una mediana y no la lectura de cada muestra: `errorPercentage` es
ruidoso. Cinco lecturas consecutivas del BM1370 con voltaje y frecuencia
constantes dieron 11.08, 13.85, 13.31, 11.44 y 13.25 por ciento; un recorrido
de 2.8 puntos sin que el hardware cambiara nada. Comparar una sola lectura
contra el objetivo hace que el ruido cruce el umbral en los dos sentidos y el
tuner se pase la vida moviendo el voltaje. Se decide con la mediana de una
ventana (mediana y no media: un pico aislado no la mueve), y tras cada cambio
se descartan las primeras muestras, porque el propio `errorPercentage` es un
promedio interno de AxeOS y arrastra historia del ajuste anterior.

Uso:
    from tuning_estabilidad import EstabilidadTuningStrategy

    strategy = EstabilidadTuningStrategy(...)
    new_voltage, new_frequency = strategy.apply_strategy(
        current_voltage, current_frequency, temp, hashrate, power,
        error_percent=system_info["errorPercentage"],
    )

Dependencias:
    - Terceros: rich (a traves de ui_rich, para los mensajes)
    - Estandar: collections, logging, statistics, typing
"""

import logging
from collections import deque
from statistics import median
from typing import Deque, Optional, Tuple

from ui_rich import (
    PRIMARY_ACCENT,
    SECONDARY_ACCENT,
    WARNING_COLOR,
    console,
)

# Estados del procedimiento. Son cadenas y no un Enum para que salgan legibles
# tal cual en el CSV y en el log sin conversiones.
RAMPA = "RAMPA"
BUSCAR_VOLTAJE = "BUSCAR_VOLTAJE"
OPTIMIZAR = "OPTIMIZAR"


class EstabilidadTuningStrategy:
    """Ajusta voltaje y frecuencia buscando estabilidad, no hashrate."""

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
        error_target: float,
        error_hysteresis: float = 0.5,
        error_window: int = 7,
        error_settle: int = 3,
        temp_margin: float = 2.0,
        retry_ceiling: int = 50,
    ) -> None:
        """
        Args:
            min_voltage: Voltaje minimo permitido (mV). Suelo duro.
            max_voltage: Voltaje maximo permitido (mV). Tope duro.
            min_frequency: Frecuencia minima permitida (MHz).
            max_frequency: Frecuencia maxima permitida (MHz).
            voltage_step: Cuanto se mueve el voltaje por decision (mV).
            frequency_step: Cuanto se mueve la frecuencia por decision (MHz).
            target_temp: Temperatura objetivo (C). Es un limite: pasarse de
                aqui dispara la rama de mayor prioridad.
            power_limit: Limite de potencia (W). Se compara con un margen del
                7.5 %, igual que en la estrategia PID.
            error_target: Porcentaje de errores de hardware que no se quiere
                superar. Es el objetivo del control.
            error_hysteresis: Banda muerta por debajo del objetivo, en puntos
                de porcentaje. Solo se considera que "sobra margen" cuando la
                mediana baja de (error_target - error_hysteresis). Sin esta
                banda el punto de convergencia oscila entre dos escalones.
            error_window: Numero de muestras de la mediana. Cuanto mas grande,
                mas fiable la decision y mas lenta: cada decision basada en
                errores tarda (error_settle + error_window) muestras.
            error_settle: Muestras que se descartan despues de cada cambio,
                para no decidir con lecturas que aun arrastran el ajuste
                anterior.
            temp_margin: Margen bajo target_temp (C) que se exige para
                autorizar cualquier SUBIDA. Crea la banda muerta que evita el
                ciclo entre "subo porque puedo" y "bajo porque me paso".
            retry_ceiling: Cada cuantas decisiones estables se reintenta una
                frecuencia que fallo antes. Evita quedarse pegado abajo cuando
                las condiciones mejoran (por ejemplo, de noche).

                Es el compromiso central del controlador y esta medido sobre un
                chip simulado con el ruido real (desviacion 1.24). Porcentaje de
                tiempo POR ENCIMA del objetivo del 2 %, en cuatro semillas:

                    retry_ceiling 5   -> 20-28 %
                    retry_ceiling 10  -> 12-25 %
                    retry_ceiling 20  -> 12-15 %
                    retry_ceiling 50  ->  6-10 %     <- por defecto
                    retry_ceiling 100 ->  3-7 %
                    sin reintento     ->  0 %, pero se queda pegado abajo

                Reintentar mas a menudo gana frecuencia (y hashrate util) a
                cambio de pasar mas tiempo incumpliendo el objetivo. El valor
                por defecto se elige del lado del cumplimiento, porque el
                requisito es no superar el objetivo. Subelo si prefieres
                estabilidad aun mas estricta; bajalo si prefieres perseguir la
                frecuencia mas de cerca.
        """
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.min_frequency = min_frequency
        self.max_frequency = max_frequency
        self.voltage_step = voltage_step
        self.frequency_step = frequency_step
        self.target_temp = target_temp
        self.power_limit = power_limit
        self.error_target = error_target
        self.error_hysteresis = error_hysteresis
        self.temp_margin = temp_margin
        self.error_settle = error_settle

        self.estado = RAMPA
        self._ventana: Deque[float] = deque(maxlen=max(1, int(error_window)))
        # Se arranca descartando, igual que despues de cada cambio de ajuste. El
        # tuner se lanza sobre un miner que ya estaba minando, asi que la primera
        # temperatura y el primer errorPercentage describen el ajuste ANTERIOR, no
        # el que se acaba de escribir. Medido en el miner real: a los 2 s de
        # arrancar, RAMPA leyo 60.25 C (calor arrastrado de ~900 MHz), se creyo en
        # el limite termico y se quedo clavado en 495 MHz, donde una hora despues
        # seguia a 38.5 C con 22 grados de margen sin usar.
        self._descartar = max(1, int(error_settle))
        # Muestras a ignorar para decidir por TEMPERATURA al arrancar. Es un
        # contador aparte de _descartar porque la temperatura no pasa por la
        # ventana: se compara cruda contra target_temp en cada muestra.
        self._calentando = self._descartar
        # Frecuencia que ya se demostro insostenible al voltaje actual. Sin esta
        # memoria el lazo reintenta subir a ella cada vez que el ruido mete la
        # mediana un instante dentro de la banda, y la frecuencia vaga entre dos
        # escalones para siempre. Se olvida en cuanto sube el voltaje, porque
        # entonces la frecuencia rechazada puede haber pasado a ser viable.
        self._f_techo: Optional[float] = None
        # El techo caduca: el silicio cambia con la temperatura ambiente y una
        # frecuencia rechazada en una tarde calurosa puede ser viable de noche.
        # Sin caducidad el lazo se queda pegado abajo para siempre, dejando
        # frecuencia sin usar. Con ella se reintenta cada tantas decisiones
        # estables, que es el "y asi sucesivamente" del procedimiento.
        self._estables = 0
        self.reintentar_techo = max(1, int(retry_ceiling))
        # Para avisar una sola vez si el miner no reporta el campo.
        self._sin_dato = 0
        self._aviso_sin_dato = False
        # Para avisar una sola vez cuando el objetivo es inalcanzable.
        self._aviso_inalcanzable = False

    # ------------------------------------------------------------------
    # Ventana de errores
    # ------------------------------------------------------------------

    def _registrar_error(self, error_percent: Optional[float]) -> None:
        """Meter la lectura en la ventana, salvo que estemos asentando."""
        if error_percent is None:
            self._sin_dato += 1
            if self._sin_dato == 3 and not self._aviso_sin_dato:
                self._aviso_sin_dato = True
                console.print(
                    f"[{WARNING_COLOR}]El miner no reporta errorPercentage: el "
                    f"control por errores de hardware no puede funcionar. Solo "
                    f"actuaran temperatura y potencia.[/]"
                )
                logging.error(
                    "errorPercentage ausente en la respuesta del miner; "
                    "EstabilidadTuningStrategy se queda sin su senal principal"
                )
            return
        self._sin_dato = 0
        if self._descartar > 0:
            self._descartar -= 1
            return
        self._ventana.append(float(error_percent))

    def _mediana(self) -> Optional[float]:
        """Mediana de la ventana, o None si aun no esta llena."""
        if len(self._ventana) < self._ventana.maxlen:
            return None
        return median(self._ventana)

    def _invalidar_ventana(self) -> None:
        """Tras cambiar el ajuste, lo medido antes ya no describe el presente."""
        self._ventana.clear()
        self._descartar = self.error_settle

    def ajuste_cambiado_fuera(self) -> None:
        """
        Avisar de que alguien cambio voltaje o frecuencia sin pasar por aqui.

        Lo llama TuningManager cuando detecta que el miner tiene otro ajuste (el
        usuario lo toco por la web de AxeOS). Se tira lo medido, porque describe un
        ajuste que ya no esta puesto, y se olvida lo aprendido sobre techos y
        suelos, porque se aprendio en otro punto de trabajo.

        NO se vuelve a RAMPA: se sigue optimizando desde donde el usuario lo dejo.
        La temperatura sigue mandando por la via normal, que es la rama de mayor
        prioridad y no consulta la ventana.
        """
        self._invalidar_ventana()
        self._f_techo = None
        self._estables = 0

    def _cambiar_estado(self, nuevo: str, motivo: str) -> None:
        if nuevo == self.estado:
            return
        console.print(
            f"[{PRIMARY_ACCENT}]Estado {self.estado} -> {nuevo}: {motivo}[/]"
        )
        logging.info(f"Estado {self.estado} -> {nuevo}: {motivo}")
        self.estado = nuevo

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------

    def apply_strategy(
        self,
        current_voltage: float,
        current_frequency: float,
        temp: float,
        hashrate: float,
        power: float,
        error_percent: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Devolver el siguiente par (voltaje, frecuencia) a aplicar.

        `hashrate` se acepta para mantener la misma firma que la estrategia PID,
        pero NO se usa en ninguna decision: en este controlador el hashrate es
        un resultado, no un objetivo.
        """
        self._registrar_error(error_percent)
        if self._calentando > 0:
            self._calentando -= 1

        nueva_v = current_voltage
        nueva_f = current_frequency

        # Cualquier subida exige margen de temperatura. Sin este margen, bajar
        # al pasarse de TARGET_TEMP y subir en cuanto se cumple produce un
        # ciclo de un paso arriba y otro abajo indefinidamente.
        puede_subir = temp <= self.target_temp - self.temp_margin

        # --- Prioridad 1: temperatura -------------------------------------
        # El VOLTAJE es la palanca termica, no la frecuencia. Se baja voltaje
        # mientras los errores lo permitan; cuando el voltaje ya no puede bajar
        # sin pasarse del objetivo de errores, entonces baja la frecuencia; y si
        # tampoco queda frecuencia, se baja voltaje por debajo del umbral de
        # errores, porque la temperatura es absoluta y manda sobre todo.
        if temp > self.target_temp:
            med = self._mediana()
            # Se baja voltaje mientras lo medido no se pase del objetivo. Cuando
            # no hay mediana SI se concede el beneficio de la duda, y es
            # deliberado: cada cambio invalida la ventana, asi que "sin mediana"
            # es el caso habitual justo despues de actuar, y exigir una medida
            # dejaria la palanca termica en la frecuencia casi siempre, que es
            # justo lo contrario de lo pedido. El riesgo de bajar voltaje de mas
            # esta acotado porque en cuanto la ventana se llena por encima del
            # objetivo esta rama deja de elegir voltaje y pasa a la frecuencia.
            voltaje_con_sitio = current_voltage > self.min_voltage and (
                med is None or med <= self.error_target
            )
            if voltaje_con_sitio:
                nueva_v = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando voltaje a {nueva_v}mV por "
                    f"temperatura {temp}C > {self.target_temp}C "
                    f"(errores {'sin medir' if med is None else f'{med:.2f}%'} "
                    f"contra objetivo {self.error_target}%)[/]"
                )
            elif current_frequency > self.min_frequency:
                # El voltaje ya esta en su suelo util: bajarlo mas se saldria del
                # objetivo de errores. Toca frecuencia.
                nueva_f = current_frequency - self.frequency_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando frecuencia a {nueva_f}MHz por "
                    f"temperatura {temp}C > {self.target_temp}C (el voltaje ya "
                    f"no puede bajar sin pasarse del "
                    f"{self.error_target}% de errores)[/]"
                )
            elif current_voltage > self.min_voltage:
                # Ultimo recurso: ya no queda frecuencia, asi que se sacrifica el
                # objetivo de errores. La temperatura es la unica restriccion que
                # no se negocia.
                nueva_v = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando voltaje a {nueva_v}mV por "
                    f"temperatura {temp}C > {self.target_temp}C: ya en la "
                    f"frecuencia minima, se acepta pasarse del "
                    f"{self.error_target}% de errores[/]"
                )
            else:
                console.print(
                    f"[{WARNING_COLOR}]Temperatura {temp}C > {self.target_temp}C "
                    f"y ya en el minimo {self.min_voltage}mV/"
                    f"{self.min_frequency}MHz: no queda margen para bajar[/]"
                )
            if self.estado == RAMPA:
                # Al arrancar NO se abandona la rampa por temperatura: la lectura
                # puede ser calor arrastrado del ajuste anterior. Se baja igual
                # (la proteccion termica no se toca nunca), pero se sigue en RAMPA
                # para volver a subir cuando la lectura sea del ajuste actual.
                if self._calentando > 0:
                    console.print(
                        f"[{WARNING_COLOR}]RAMPA: {temp}C al arrancar puede ser "
                        f"calor del ajuste anterior; se baja pero no se abandona "
                        f"la rampa ({self._calentando} muestras por confirmar)[/]"
                    )
                else:
                    self._cambiar_estado(
                        BUSCAR_VOLTAJE, f"temperatura alcanzada ({temp}C)"
                    )
            return self._cerrar(nueva_v, nueva_f, current_voltage, current_frequency)

        # --- Prioridad 2: potencia ----------------------------------------
        limite = self.power_limit * 1.075
        if power > limite:
            # Se baja frecuencia y no voltaje: la potencia cae igual y la
            # estabilidad no se toca. Es la diferencia deliberada con la
            # estrategia PID, que aqui bajaba el voltaje y con ello disparaba
            # los errores justo cuando mas hacia falta estabilidad.
            if current_frequency > self.min_frequency:
                nueva_f = current_frequency - self.frequency_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando frecuencia a {nueva_f}MHz por "
                    f"potencia {power}W > {limite:.1f}W[/]"
                )
            elif current_voltage > self.min_voltage:
                nueva_v = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Bajando voltaje a {nueva_v}mV por "
                    f"potencia {power}W > {limite:.1f}W (ya en la frecuencia "
                    f"minima)[/]"
                )
            if self.estado == RAMPA:
                self._cambiar_estado(
                    BUSCAR_VOLTAJE, f"limite de potencia alcanzado ({power}W)"
                )
            return self._cerrar(nueva_v, nueva_f, current_voltage, current_frequency)

        # --- Prioridad 3: errores de hardware ------------------------------
        if self.estado == RAMPA:
            nueva_v, nueva_f = self._rampa(
                current_voltage, current_frequency, temp, puede_subir
            )
        elif self.estado == BUSCAR_VOLTAJE:
            nueva_v, nueva_f = self._buscar_voltaje(
                current_voltage, current_frequency
            )
        else:
            nueva_v, nueva_f = self._optimizar(
                current_voltage, current_frequency, puede_subir, temp
            )

        return self._cerrar(nueva_v, nueva_f, current_voltage, current_frequency)

    # ------------------------------------------------------------------
    # Los tres estados
    # ------------------------------------------------------------------

    def _rampa(
        self,
        v: float,
        f: float,
        temp: float,
        puede_subir: bool,
    ) -> Tuple[float, float]:
        """
        Subir frecuencia y voltaje a la vez hasta el techo que permita la
        temperatura.

        Es el unico estado que mueve las dos palancas en la misma muestra. Se
        permite porque aqui no se esta midiendo nada: la unica condicion de
        parada es la temperatura, que es inmediata. Subir de una en una tardaria
        el doble sin aportar informacion, y el destino es el mismo: el punto mas
        alto alcanzable, que es tambien el mas estable y desde el que tiene
        sentido empezar a bajar voltaje.
        """
        # Primero el voltaje al maximo, de golpe. Es el punto de partida del
        # procedimiento: con el voltaje mas alto el chip aguanta la frecuencia mas
        # alta, asi que subir frecuencia con voltaje a medias solo obligaria a
        # rehacer el camino. No se sube "de paso en paso" porque no se esta
        # midiendo nada: la unica condicion de parada aqui es la temperatura.
        if v < self.max_voltage:
            console.print(
                f"[{SECONDARY_ACCENT}]RAMPA: voltaje al maximo "
                f"{self.max_voltage}mV antes de subir frecuencia (temp {temp}C)[/]"
            )
            return self.max_voltage, f

        if f >= self.max_frequency:
            self._cambiar_estado(
                BUSCAR_VOLTAJE,
                f"techo de frecuencia alcanzado ({v}mV/{f}MHz), ahora a buscar "
                f"el voltaje minimo",
            )
            return v, f

        if not puede_subir:
            self._cambiar_estado(
                BUSCAR_VOLTAJE,
                f"a {temp}C ya no hay margen bajo {self.target_temp}C "
                f"(margen {self.temp_margin}C)",
            )
            return v, f

        # Y ahora solo frecuencia. El voltaje ya esta arriba y no se toca en este
        # estado: bajarlo es trabajo de las fases siguientes.
        nueva_f = min(f + self.frequency_step, self.max_frequency)
        console.print(
            f"[{SECONDARY_ACCENT}]RAMPA: subiendo frecuencia a {nueva_f}MHz "
            f"(temp {temp}C, {v}mV, techo {self.max_frequency}MHz)[/]"
        )
        return v, nueva_f

    def _buscar_voltaje(self, v: float, f: float) -> Tuple[float, float]:
        """
        Bajar el voltaje hasta que los errores toquen el objetivo, y al pasarse
        volver un paso atras.

        El resultado es el voltaje minimo que cumple el objetivo a la frecuencia
        actual, que es exactamente lo que se pide: no el que da mas hashrate,
        sino el mas bajo que aun es estable.
        """
        med = self._mediana()
        if med is None:
            console.print(
                f"[{PRIMARY_ACCENT}]BUSCAR_VOLTAJE: midiendo "
                f"({len(self._ventana)}/{self._ventana.maxlen} muestras"
                f"{f', {self._descartar} por descartar' if self._descartar else ''})[/]"
            )
            return v, f

        if med <= self.error_target:
            if v > self.min_voltage:
                nueva_v = v - self.voltage_step
                console.print(
                    f"[{SECONDARY_ACCENT}]BUSCAR_VOLTAJE: errores {med:.2f}% "
                    f"<= {self.error_target}%, bajando voltaje a {nueva_v}mV[/]"
                )
                return nueva_v, f
            self._cambiar_estado(
                OPTIMIZAR,
                f"errores {med:.2f}% dentro del objetivo ya en el voltaje "
                f"minimo {self.min_voltage}mV",
            )
            return v, f

        # Se paso: el ultimo voltaje bueno era el anterior.
        if v < self.max_voltage:
            nueva_v = v + self.voltage_step
            self._cambiar_estado(
                OPTIMIZAR,
                f"errores {med:.2f}% > {self.error_target}%, volviendo a "
                f"{nueva_v}mV (ultimo voltaje que cumplia)",
            )
            return nueva_v, f
        self._cambiar_estado(
            OPTIMIZAR,
            f"errores {med:.2f}% > {self.error_target}% ya en el voltaje "
            f"maximo {self.max_voltage}mV",
        )
        return v, f

    def _optimizar(
        self,
        v: float,
        f: float,
        puede_subir: bool,
        temp: float,
    ) -> Tuple[float, float]:
        """
        Regimen permanente: el lazo que el usuario describe como "y asi
        sucesivamente".

        Tres reglas, en orden. Si los errores se pasan, subir voltaje (y si no
        se puede, bajar frecuencia). Si sobra margen, subir frecuencia. Si sobra
        margen y la frecuencia ya esta al tope, bajar voltaje, que es lo que
        hace que el punto final sea eficiente y no solo estable.
        """
        med = self._mediana()
        if med is None:
            console.print(
                f"[{PRIMARY_ACCENT}]OPTIMIZAR: midiendo "
                f"({len(self._ventana)}/{self._ventana.maxlen} muestras"
                f"{f', {self._descartar} por descartar' if self._descartar else ''})"
                f" en {v}mV/{f}MHz[/]"
            )
            return v, f

        if med > self.error_target:
            if v < self.max_voltage:
                if not puede_subir:
                    console.print(
                        f"[{WARNING_COLOR}]OPTIMIZAR: errores {med:.2f}% > "
                        f"{self.error_target}% pero a {temp}C no hay margen "
                        f"para subir voltaje; bajando frecuencia[/]"
                    )
                    if f > self.min_frequency:
                        self._f_techo = f
                        self._estables = 0
                        return v, f - self.frequency_step
                    return v, f
                nueva_v = v + self.voltage_step
                console.print(
                    f"[{SECONDARY_ACCENT}]OPTIMIZAR: errores {med:.2f}% > "
                    f"{self.error_target}%, subiendo voltaje a {nueva_v}mV[/]"
                )
                # Con mas voltaje, la frecuencia que antes fallaba puede ser
                # viable: el techo aprendido deja de ser valido.
                self._f_techo = None
                return nueva_v, f
            if f > self.min_frequency:
                nueva_f = f - self.frequency_step
                console.print(
                    f"[{WARNING_COLOR}]OPTIMIZAR: errores {med:.2f}% > "
                    f"{self.error_target}% con el voltaje ya en el maximo "
                    f"{self.max_voltage}mV, bajando frecuencia a {nueva_f}MHz[/]"
                )
                self._f_techo = f
                self._estables = 0
                return v, nueva_f
            if not self._aviso_inalcanzable:
                self._aviso_inalcanzable = True
                console.print(
                    f"[{WARNING_COLOR}]OPTIMIZAR: errores {med:.2f}% > "
                    f"{self.error_target}% en {self.max_voltage}mV/"
                    f"{self.min_frequency}MHz. El objetivo no es alcanzable "
                    f"dentro de los limites configurados: sube MAX_VOLTAGE, "
                    f"baja MIN_FREQUENCY o acepta un objetivo mas alto.[/]"
                )
                logging.warning(
                    f"Objetivo de errores {self.error_target}% inalcanzable: "
                    f"{med:.2f}% en el extremo {self.max_voltage}mV/"
                    f"{self.min_frequency}MHz"
                )
            return v, f

        if med < self.error_target - self.error_hysteresis:
            objetivo_f = f + self.frequency_step
            techo_conocido = self._f_techo is not None and objetivo_f >= self._f_techo
            if f < self.max_frequency and puede_subir and not techo_conocido:
                console.print(
                    f"[{SECONDARY_ACCENT}]OPTIMIZAR: errores {med:.2f}% con "
                    f"margen, subiendo frecuencia a {objetivo_f}MHz[/]"
                )
                return v, objetivo_f
            # Sobra margen de errores y la frecuencia esta en su tope duro: se baja
            # voltaje. Ojo: la busqueda del voltaje minimo NO se hace aqui, se hace
            # en BUSCAR_VOLTAJE, que es el estado dedicado a eso. Esto es solo el
            # afinado del regimen permanente.
            #
            # Verificado por fuerza bruta contra el optimo teorico, con los limites
            # reales (1180-1210mV / 475-925MHz, TARGET_TEMP 60) sobre un chip
            # calibrado con dos medidas del miner: con objetivos 1, 2, 5 y 10 % el
            # lazo acaba EXACTAMENTE en el optimo, y el voltaje final nunca queda
            # por encima del optimo. Que el voltaje acabe alto no es un fallo: mas
            # voltaje sostiene mas frecuencia al mismo nivel de errores, y el
            # procedimiento pide primero la frecuencia mas alta.
            #
            # La condicion es a proposito estrecha (solo en max_frequency) y no se
            # debe ensanchar sin resolver antes el ciclo entre las dos palancas:
            # baja voltaje -> suben los errores -> sube voltaje -> vuelve a sobrar
            # margen -> baja voltaje, cruzando el objetivo en cada vuelta. Medido:
            # ensanchandola el incumplimiento pasa del 6-9 % al 36-43 %, y con un
            # suelo de voltaje aprendido por frecuencia solo baja al 26-32 %.
            #
            # La causa de fondo es de escalones, no de logica: un paso de voltaje
            # mueve los errores mucho mas que la histeresis que autoriza el cambio
            # (10 mV = 1.6 puntos contra 0.5 de banda), asi que desde un punto que
            # cumple, bajar voltaje se pasa siempre.
            #
            # Tambien se probo y descarto estimar ese coste midiendolo (comparando
            # la mediana antes y despues de cada cambio de voltaje) para exigir un
            # margen mayor que el coste: daba resultados identicos en ocho
            # escenarios, porque en la practica esta rama casi no se ejerce. Era
            # codigo muerto.
            if f >= self.max_frequency and v > self.min_voltage:
                nueva_v = v - self.voltage_step
                if f >= self.max_frequency:
                    motivo = f"la frecuencia ya en el maximo {self.max_frequency}MHz"
                elif not puede_subir:
                    motivo = f"a {temp}C no hay margen para subir frecuencia"
                else:
                    motivo = f"{f + self.frequency_step}MHz ya fallo antes"
                console.print(
                    f"[{SECONDARY_ACCENT}]OPTIMIZAR: errores {med:.2f}% con "
                    f"margen y {motivo}, bajando voltaje a {nueva_v}mV[/]"
                )
                return nueva_v, f

        # Punto estable. Se cuenta, y cada reintentar_techo decisiones se olvida
        # el techo aprendido para volver a probar si ya se puede subir.
        self._estables += 1
        if self._f_techo is not None and self._estables >= self.reintentar_techo:
            console.print(
                f"[{PRIMARY_ACCENT}]Estable {self._estables} decisiones: "
                f"reintentando la frecuencia {self._f_techo}MHz, que fallo antes[/]"
            )
            self._f_techo = None
            self._estables = 0
        console.print(
            f"[{PRIMARY_ACCENT}]Estable en {v}mV/{f}MHz: errores {med:.2f}% "
            f"contra objetivo {self.error_target}% "
            f"(banda {self.error_target - self.error_hysteresis:.2f}-"
            f"{self.error_target}%), {temp}C[/]"
        )
        return v, f

    # ------------------------------------------------------------------
    # Salida
    # ------------------------------------------------------------------

    def _cerrar(
        self,
        nueva_v: float,
        nueva_f: float,
        v_previo: float,
        f_previo: float,
    ) -> Tuple[float, float]:
        """
        Red final: recortar al rango configurado e invalidar la ventana si el
        ajuste cambia.

        Igual que en la estrategia PID, lo que sale de aqui va directo al
        hardware, asi que se recorta una ultima vez: MAX_VOLTAGE y
        MAX_FREQUENCY son un tope real y no una intencion. Cubre tambien el caso
        de recibir un valor actual ya fuera de rango.
        """
        v = max(self.min_voltage, min(self.max_voltage, nueva_v))
        f = max(self.min_frequency, min(self.max_frequency, nueva_f))
        if v != nueva_v or f != nueva_f:
            console.print(
                f"[{WARNING_COLOR}]Recortando a los limites seguros: "
                f"{nueva_v}mV/{nueva_f}MHz -> {v}mV/{f}MHz "
                f"(limites {self.min_voltage}-{self.max_voltage}mV, "
                f"{self.min_frequency}-{self.max_frequency}MHz)[/]"
            )
        if v != v_previo or f != f_previo:
            self._invalidar_ventana()
        return v, f
