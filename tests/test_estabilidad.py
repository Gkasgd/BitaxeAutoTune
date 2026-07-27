#!/usr/bin/env python3
"""
Verificacion de EstabilidadTuningStrategy contra un chip simulado.

El chip simulado no pretende modelar el BM1370 de verdad. Solo reproduce las
tres relaciones que el controlador da por ciertas, y que son las que g ha
comprobado a mano en su miner:

  - subir frecuencia sube los errores
  - subir voltaje los baja
  - ambos suben la temperatura y la potencia

Si el controlador converge sobre este modelo, se demuestra que su logica de
estados es coherente. Si NO converge, hay un fallo en el controlador. Lo que
este test no puede demostrar es que los valores por defecto de la ventana o de
la histeresis sean los buenos para el hardware real: eso solo lo dira el miner.

Se le anade ruido de +-1.4 puntos, que es la desviacion medida en el miner de g,
para comprobar que la mediana movil hace su trabajo y el lazo no oscila.
"""

import random
import sys

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tuning_estabilidad import (  # noqa: E402
    BUSCAR_VOLTAJE,
    OPTIMIZAR,
    RAMPA,
    EstabilidadTuningStrategy,
)


class ChipSimulado:
    """Modelo monotono y simple: errores(f, v), temp(f, v), potencia(f, v)."""

    def __init__(self, ruido: float = 0.0, semilla: int = 1) -> None:
        self.ruido = ruido
        self.rng = random.Random(semilla)

    def errores(self, f: float, v: float) -> float:
        """
        Porcentaje de errores. Calibrado para que el punto de trabajo real de g
        (800 MHz, 1195 mV) de ~12.6 %, que es la media que midio.
        """
        e = 12.6 + (f - 800) * 0.09 - (v - 1195) * 0.16
        e = max(0.0, e)
        if self.ruido:
            e += self.rng.gauss(0, self.ruido)
        return max(0.0, e)

    def temp(self, f: float, v: float) -> float:
        return 60.0 + (f - 800) * 0.035 + (v - 1195) * 0.030

    def potencia(self, f: float, v: float) -> float:
        return 27.3 + (f - 800) * 0.018 + (v - 1195) * 0.022


def simular(
    chip: ChipSimulado,
    strategy: EstabilidadTuningStrategy,
    v0: float,
    f0: float,
    muestras: int = 400,
):
    """Cerrar el lazo y devolver la traza completa."""
    v, f = v0, f0
    traza = []
    for _ in range(muestras):
        e = chip.errores(f, v)
        t = chip.temp(f, v)
        p = chip.potencia(f, v)
        estado = strategy.estado
        nv, nf = strategy.apply_strategy(
            current_voltage=v,
            current_frequency=f,
            temp=t,
            hashrate=0.0,  # deliberadamente cero: no debe influir en nada
            power=p,
            error_percent=e,
        )
        traza.append((estado, v, f, e, t, p, nv, nf))
        v, f = nv, nf
    return traza, v, f


def nueva(**kw):
    """Estrategia con los limites de safe-BM1370 y objetivo del 2 %."""
    base = dict(
        min_voltage=1150,
        max_voltage=1250,
        min_frequency=750,
        max_frequency=900,
        voltage_step=10,
        frequency_step=25,
        target_temp=65.0,
        power_limit=28.0,
        error_target=2.0,
        error_hysteresis=0.5,
        error_window=7,
        error_settle=3,
        temp_margin=2.0,
    )
    base.update(kw)
    return EstabilidadTuningStrategy(**base)


fallos = []


def check(cond: bool, msg: str) -> None:
    print(("  OK   " if cond else "  FALLA") + f" {msg}")
    if not cond:
        fallos.append(msg)


# ---------------------------------------------------------------------------
print("=== 1. el hashrate no influye en ninguna decision ===")
# Misma situacion, hashrate absurdamente distinto: debe decidir lo mismo.
s1, s2 = nueva(), nueva()
r1 = s1.apply_strategy(1200, 800, 60.0, 0.0, 27.0, error_percent=12.0)
r2 = s2.apply_strategy(1200, 800, 60.0, 999999.0, 27.0, error_percent=12.0)
check(r1 == r2, f"hashrate 0 y 999999 dan la misma decision {r1}")

# ---------------------------------------------------------------------------
print("\n=== 2. la temperatura tiene prioridad sobre todo ===")
# La palanca termica es el VOLTAJE, no la frecuencia. Se baja voltaje mientras
# los errores lo permitan; la frecuencia solo cuando el voltaje ya no puede
# bajar sin pasarse del objetivo de errores.
s = nueva()
v, f = s.apply_strategy(1200, 800, 70.0, 1500, 27.0, error_percent=40.0)
check(
    v == 1190 and f == 800,
    f"temp 70>65 baja VOLTAJE a 1190, no toca frecuencia: {v}mV/{f}MHz",
)

# Con la ventana llena por encima del objetivo, el voltaje ya no tiene sitio:
# bajarlo empeoraria los errores, asi que la que cede es la frecuencia.
#
# La ventana se rellena a mano porque por el lazo no hay forma: con errores del
# 40 % cada muestra provoca un cambio de ajuste, y todo cambio la invalida. Lo
# que se comprueba aqui es la decision CON ventana llena, no como se llena.
s2 = nueva()
s2.estado = OPTIMIZAR
s2._descartar = 0
s2._ventana.extend([40.0] * 7)
check(
    s2._mediana() is not None,
    f"la ventana queda llena para la comprobacion (mediana {s2._mediana()})",
)
v, f = s2.apply_strategy(1200, 800, 70.0, 1500, 27.0, error_percent=40.0)
check(
    f == 775 and v == 1200,
    f"con errores ya sobre el objetivo, la temperatura baja FRECUENCIA: {v}mV/{f}MHz",
)

s = nueva()
# En la frecuencia minima ya, con temperatura pasada: toca bajar voltaje.
v, f = s.apply_strategy(1200, 750, 70.0, 1500, 27.0, error_percent=40.0)
check(v == 1190 and f == 750, f"en MIN_FREQUENCY baja voltaje: {v}mV/{f}MHz")

s = nueva()
# En el minimo absoluto: no puede bajar mas, no debe romperse.
v, f = s.apply_strategy(1150, 750, 70.0, 1500, 27.0, error_percent=40.0)
check(v == 1150 and f == 750, f"en el minimo absoluto no se mueve: {v}mV/{f}MHz")

# ---------------------------------------------------------------------------
print("\n=== 3. la potencia baja FRECUENCIA, no voltaje ===")
s = nueva()
v, f = s.apply_strategy(1200, 800, 60.0, 1500, 35.0, error_percent=1.0)
check(
    f == 775 and v == 1200,
    f"potencia 35W > 30.1W baja frecuencia y respeta el voltaje: {v}mV/{f}MHz",
)

# ---------------------------------------------------------------------------
print("\n=== 4. no decide por errores hasta tener la ventana llena ===")
s = nueva()
v, f = 1200, 800
# Tras el primer cambio (rampa) se invalida la ventana y hay 3 descartes + 7
# muestras. Comprobamos que en BUSCAR_VOLTAJE no mueve nada mientras mide.
s.estado = BUSCAR_VOLTAJE
s._invalidar_ventana()
movimientos = 0
for i in range(9):  # 3 descartes + 6 de ventana: aun no llega a 7
    nv, nf = s.apply_strategy(v, f, 60.0, 0, 27.0, error_percent=1.0)
    if (nv, nf) != (v, f):
        movimientos += 1
    v, f = nv, nf
check(movimientos == 0, f"con la ventana a medias no mueve nada ({movimientos} movimientos en 9 muestras)")

# ---------------------------------------------------------------------------
print("\n=== 5. el procedimiento completo, sin ruido ===")
chip = ChipSimulado(ruido=0.0)
s = nueva()
traza, vf, ff = simular(chip, s, v0=1150, f0=750)
estados = []
for e, *_ in traza:
    if not estados or estados[-1] != e:
        estados.append(e)
print(f"  secuencia de estados: {' -> '.join(estados)}")
check(estados[0] == RAMPA, "arranca en RAMPA")
check(BUSCAR_VOLTAJE in estados, "pasa por BUSCAR_VOLTAJE")
check(estados[-1] == OPTIMIZAR, "termina en OPTIMIZAR")
check(
    estados == [RAMPA, BUSCAR_VOLTAJE, OPTIMIZAR],
    f"el orden es exactamente el pedido: {estados}",
)

e_final = chip.errores(ff, vf)
t_final = chip.temp(ff, vf)
p_final = chip.potencia(ff, vf)
print(f"  punto final: {vf}mV / {ff}MHz  errores {e_final:.2f}%  temp {t_final:.1f}C  pot {p_final:.1f}W")
check(e_final <= 2.0 + 0.01, f"los errores finales cumplen el objetivo del 2%: {e_final:.2f}%")
check(t_final <= 65.0, f"la temperatura final respeta TARGET_TEMP: {t_final:.1f}C")
check(1150 <= vf <= 1250, f"voltaje final dentro de limites: {vf}")
check(750 <= ff <= 900, f"frecuencia final dentro de limites: {ff}")

# El punto final debe ser eficiente: bajar un paso mas de voltaje deberia
# incumplir el objetivo. Si no, el controlador dejo voltaje de sobra.
if vf > 1150:
    e_menos = chip.errores(ff, vf - 10)
    check(
        e_menos > 2.0,
        f"el voltaje es el minimo que cumple: a {vf-10}mV los errores serian {e_menos:.2f}%",
    )

# Y debe ser el mas alto sostenible: subir un paso de frecuencia deberia
# incumplir el objetivo al voltaje actual.
if ff < 900:
    e_mas_f = chip.errores(ff + 25, vf)
    check(
        e_mas_f > 2.0 or chip.temp(ff + 25, vf) > 65.0,
        f"la frecuencia es la maxima sostenible: a {ff+25}MHz seria {e_mas_f:.2f}% / {chip.temp(ff+25, vf):.1f}C",
    )

# ---------------------------------------------------------------------------
print("\n=== 6. estabilidad final: no oscila (sin ruido) ===")
ultimos = traza[-60:]
puntos = {(v, f) for _, v, f, *_ in ultimos}
print(f"  puntos visitados en las ultimas 60 muestras: {sorted(puntos)}")
check(len(puntos) == 1, f"se queda quieto en un solo punto ({len(puntos)} puntos)")

# ---------------------------------------------------------------------------
print("\n=== 7. con el ruido real medido (desv 1.24) cumple el objetivo ===")
# El criterio correcto no es "no se mueve" sino "cuanto tiempo esta por encima
# del 2 %", que es lo que se pide. Se juzga con el error REAL del chip (sin
# ruido), que es la verdad que el controlador no puede ver: si eligiera un punto
# malo, el ruido no lo salvaria.
#
# Y hay que exigir las dos cosas a la vez, porque son un compromiso: un lazo que
# se queda pegado en MIN_FREQUENCY cumple el 0 % del tiempo pero desperdicia
# frecuencia. Se pide cumplir la mayor parte del tiempo Y aprovechar el margen.
for semilla in (1, 7, 42, 99):
    chip_r = ChipSimulado(ruido=1.24, semilla=semilla)
    s_r = nueva()
    traza_r, vr, fr = simular(chip_r, s_r, v0=1150, f0=750, muestras=1200)
    permanente = traza_r[len(traza_r) // 2 :]
    # Error real del punto visitado en cada muestra, no la lectura ruidosa.
    reales = [ChipSimulado(ruido=0.0).errores(f, v) for _, v, f, *_ in permanente]
    viola = sum(1 for e in reales if e > 2.0) / len(reales)
    e_medio = sum(reales) / len(reales)
    print(
        f"  semilla {semilla}: final {vr}mV/{fr}MHz  "
        f"tiempo por encima del 2%: {viola:.0%}  error real medio {e_medio:.2f}%"
    )
    check(
        viola <= 0.15,
        f"semilla {semilla}: cumple el objetivo al menos el 85% del tiempo "
        f"(incumple el {viola:.0%})",
    )
    check(
        e_medio >= 0.4,
        f"semilla {semilla}: aprovecha el margen y no se queda pegado abajo "
        f"(error real medio {e_medio:.2f}%)",
    )
    check(
        1150 <= vr <= 1250 and 750 <= fr <= 900,
        f"semilla {semilla}: acaba dentro de limites ({vr}mV/{fr}MHz)",
    )

# ---------------------------------------------------------------------------
print("\n=== 8. objetivo inalcanzable: se queda en el extremo, no se rompe ===")
chip_duro = ChipSimulado(ruido=0.0)
s_d = nueva(error_target=0.01)  # imposible con este chip
traza_d, vd, fd = simular(chip_duro, s_d, v0=1150, f0=750, muestras=300)
print(f"  punto final: {vd}mV/{fd}MHz (errores {chip_duro.errores(fd, vd):.2f}%)")
check(vd == 1250 or fd == 750, f"acaba en un extremo del rango: {vd}mV/{fd}MHz")
check(1150 <= vd <= 1250 and 750 <= fd <= 900, "nunca sale de los limites")

# ---------------------------------------------------------------------------
print("\n=== 9. sin el dato de errores solo actuan temp y potencia ===")
s_n = nueva()
v, f = 1200, 800
for _ in range(30):
    v, f = s_n.apply_strategy(v, f, 60.0, 1500, 27.0, error_percent=None)
check((v, f) != (1200, 800), f"la RAMPA funciona sin el dato: {v}mV/{f}MHz")
antes = (v, f)
for _ in range(30):
    v, f = s_n.apply_strategy(v, f, 60.0, 1500, 27.0, error_percent=None)
check(
    s_n.estado in (BUSCAR_VOLTAJE, OPTIMIZAR),
    f"sale de RAMPA por temperatura aunque no haya dato (estado {s_n.estado})",
)
check(1150 <= v <= 1250 and 750 <= f <= 900, f"sigue dentro de limites: {v}mV/{f}MHz")

# ---------------------------------------------------------------------------
print("\n=== 10. arrancando desde arriba tambien converge ===")
chip2 = ChipSimulado(ruido=0.0)
s2 = nueva()
traza2, v2, f2 = simular(chip2, s2, v0=1250, f0=900)
e2 = chip2.errores(f2, v2)
print(f"  desde 1250mV/900MHz -> {v2}mV/{f2}MHz, errores {e2:.2f}%, temp {chip2.temp(f2, v2):.1f}C")
check(e2 <= 2.01, f"cumple el objetivo viniendo desde arriba: {e2:.2f}%")
check(chip2.temp(f2, v2) <= 65.0, "y respeta la temperatura")

# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
if fallos:
    print(f"FALLAN {len(fallos)} comprobaciones:")
    for m in fallos:
        print(f"  - {m}")
    sys.exit(1)
print("Todas las comprobaciones pasan.")
