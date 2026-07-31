# Cómo aplicar los cuatro parches

> **Documento histórico: no lo sigas como si fuera actual.** Describe la entrega
> de cuatro parches sobre `087dc6e`, y hoy hay **siete commits por encima**. Dos
> cosas de aquí ya no son ciertas:
>
> - **La palanca térmica está al revés.** Aquí se dice que el calor baja voltaje
>   primero. El parche `0003` hacía eso, pero `d2ef8dc` lo revirtió **a
>   propósito**, porque bajar voltaje sube los errores justo cuando el chip va más
>   forzado. Hoy el calor baja **frecuencia** primero, y voltaje solo con la
>   frecuencia ya en `MIN_FREQUENCY`. Es lo que pediste.
> - **El `git revert` de más abajo ya no es seguro**, porque revertiría cambios
>   sobre los que se ha construido después. Para volver atrás usa el respaldo
>   `/tmp/bitaxepid-antes` del `LEEME.md`, no ese comando.
>
> Lo que sigue siendo válido y no está recogido en otro sitio es la comparación
> del punto de convergencia contra el óptimo teórico, al final del documento.
> Para desplegar, la referencia es `archivos-para-umbrel/LEEME.md`.

Cuatro commits sobre `087dc6e` ("config: muestrear cada 30 s y descartar solo una muestra"):

1. `0001` — la RAMPA ya no abandona por el calor del ajuste anterior
2. `0002` — se lee el ajuste real del miner y se adoptan los cambios hechos por la web de AxeOS
3. `0003` — el voltaje pasa a ser la palanca térmica y la rampa arranca con el voltaje al máximo
4. `0004` — solo comentarios: deja constancia de que el punto de convergencia se verificó contra el óptimo

Tocan tres archivos: `tuning_estabilidad.py`, `tuning_manager.py` y `tests/test_estabilidad.py`.

Verificado aquí: los cuatro aplican limpios sobre `087dc6e`, reconstruyen el árbol
`3a48aab` byte a byte, y el test pasa en el árbol reconstruido.

## En tu máquina de desarrollo

Comprueba primero que partes del commit correcto:

    git log --oneline -1
    # debe decir: 087dc6e config: muestrear cada 30 s y descartar solo una muestra

Si tienes cambios sin comitear, guárdalos antes (`git stash`). Luego:

    git am parches-estabilidad/*.patch

Si `git am` se queja de la identidad, configúrala una vez:

    git config user.name "tu nombre"
    git config user.email "tu@correo"

Para abortar y quedarte como estabas: `git am --abort`.

Comprueba que quedaron los tres:

    git log --oneline -4

### Si no partes de 087dc6e

Usa `git apply` con tolerancia al contexto, que no crea commits:

    git apply -3 parches-estabilidad/*.patch

O aplica los cambios y revisa uno a uno con `git apply --check` antes.

## Comprobar antes de desplegar

    python3 tests/test_estabilidad.py

Debe terminar en `Todas las comprobaciones pasan.` Este test no necesita el
miner: usa un chip simulado.

El resto de la batería:

    bash scripts/smoke_test.sh

(Estaba en la raíz cuando se escribió esto; hoy vive en `scripts/`. En Windows,
`PYTHON=python bash scripts/smoke_test.sh`.)

## Desplegar en el Umbrel

Copia el repo actualizado al nodo y **reconstruye la imagen**. Un `restart` no
sirve: el `Containerfile` hace `COPY *.yaml *.py banner.txt ./`, así que el
código viejo se queda dentro de la imagen.

    cd ~/BitaxePID-refactor      # o donde lo tengas
    sudo docker compose up -d --build

En el Umbrel los comandos de docker necesitan `sudo`: el usuario `umbrel` no
está en el grupo `docker`.

### Qué mirar en el log

    sudo docker compose logs -f --tail 50

Señales de que los tres arreglos están vivos:

- Al arrancar en caliente, en vez de saltar a `BUSCAR_VOLTAJE` en dos segundos,
  debe aparecer `RAMPA: ... C al arrancar puede ser calor del ajuste anterior;
  se baja pero no se abandona la rampa (N muestras por confirmar)`.
- `RAMPA: voltaje al maximo ... mV antes de subir frecuencia`, y después
  `RAMPA: subiendo frecuencia a ... MHz`, sin tocar el voltaje.
- Si cambias voltaje o frecuencia desde la web de AxeOS:
  `Ajuste cambiado fuera del tuner: el miner esta en ...mV/...MHz ... Se adopta
  y se sigue optimizando desde ahi.`
- Al pasarse de `TARGET_TEMP`: **al revés de como decía este documento.** Lo que
  sale hoy es `Bajando frecuencia a ...MHz por temperatura ...`, y solo con la
  frecuencia ya en `MIN_FREQUENCY`, `Bajando voltaje a ...mV por temperatura
  ...: ya en la frecuencia minima ...MHz`.

  La coletilla que aparecía aquí, «el voltaje ya no puede bajar sin pasarse»,
  **no existe en el código**, ni antes ni ahora: buscarla en el log da vacío
  siempre.

Al buscar cualquiera de estas líneas con `grep`, usa solo el trozo **anterior al
primer valor** (`grep "Bajando frecuencia"`, no la frase entera): el texto lleva
números interpolados en medio. Que un `grep` salga vacío por eso no significa que
el arreglo no esté. Está explicado con más detalle en `LEEME.md`.

### Para volver atrás

**No uses el `git revert` que había aquí.** Revertía `d0ea3c5 c7db4b3 d5805d6
6fd67c1`, y hoy hay siete commits por encima; uno de ellos, `d2ef8dc`, reescribe
precisamente la rama térmica del `c7db4b3`. Revertirlos ahora deja el árbol en un
estado que nadie ha probado, sobre un miner encendido.

Usa el respaldo completo del paso 1 del `LEEME.md`:

    cd ~/BitaxePID
    cp -a /tmp/bitaxepid-antes/. .
    sudo docker compose up -d --build

## Sobre el voltaje mínimo: ya funciona, y está verificado

Te dije antes que esta parte quedaba pendiente. Estaba equivocado: la búsqueda
del voltaje mínimo sí ocurre, en el estado `BUSCAR_VOLTAJE`, que es el dedicado a
eso. Yo la busqué en `_optimizar`, que es solo el afinado del régimen permanente.

Comparado por fuerza bruta contra el óptimo teórico, con tus límites reales
(1180-1210 mV, 475-925 MHz, `TARGET_TEMP` 60) sobre el chip calibrado con dos
medidas de tu miner:

| Objetivo | Punto del lazo | Óptimo teórico |
|---|---|---|
| 1 % | 1210 mV / 530 MHz | 1210 mV / 530 MHz |
| 2 % | 1210 mV / 610 MHz | 1210 mV / 610 MHz |
| 5 % | 1210 mV / 715 MHz | 1210 mV / 715 MHz |
| 10 % | 1210 mV / 795 MHz | 1210 mV / 795 MHz |
| 25 % | 1185 mV / 855 MHz | 1190 mV / 870 MHz |

En los cuatro primeros el lazo acaba exactamente en el óptimo, y en ningún caso
el voltaje final queda por encima del óptimo. Que el voltaje acabe en 1210 no es
un fallo: más voltaje sostiene más frecuencia al mismo nivel de errores, y tu
procedimiento pide primero la frecuencia más alta.

El único caso que se queda corto es el objetivo del 25 %, y la causa no es el
voltaje sino `TEMP_MARGIN: 2`: el lazo deja de subir a 58.4 °C porque exige 58.0
o menos, cuando el óptimo está a 59.6 °C, todavía por debajo de tu límite de 60.
Ese coste solo aparece cuando el límite que manda es la temperatura; con
objetivos del 1 al 10 %, donde manda el error, `TEMP_MARGIN` cuesta 0 MHz. Con la
configuración que usas no te afecta, así que no lo he tocado. Si algún día subes
el objetivo a esa zona, el parámetro a discutir es `TEMP_MARGIN`, no el voltaje.

También implementé y descarté un mecanismo que medía cuánto sube los errores un
paso de voltaje para decidir si bajar era seguro. Daba resultados idénticos en
ocho escenarios (`TARGET_TEMP` 50/55/60/90 × objetivos 10/25/40, con
`VOLTAGE_STEP` 5 y 1), así que era código muerto y no está en los parches.
