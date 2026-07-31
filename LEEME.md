# Catorce archivos para copiar encima

## Ojo: los YAML cambiaron de sitio y de nombre

Esta tanda mueve la configuración a dos subdirectorios: los límites de fábrica de
cada chip a `chips/` y los perfiles a `perfiles/`, con nombres nuevos.

| Antes, en la raíz | Ahora |
|---|---|
| `safe-BM1370-estabilidad.yaml` | `perfiles/gamma-estabilidad.yaml` |
| `safe-BM1370.yaml` | `perfiles/gamma-conservador.yaml` |
| `BM1370.yaml` | `chips/BM1370.yaml` |

**Hay que editar el `.env` en el mismo despliegue**, porque el tuyo apunta al
nombre viejo y un `--config` que no existe aborta el arranque:

    BITAXEPID_CONFIG=perfiles/gamma-estabilidad.yaml

Por eso el paquete trae `chips/BM1370.yaml` aunque no le haya cambiado ni un
valor: el nuevo `bitaxepid.py` lo busca en `chips/`, no en la raíz, así que sin
él el arranque termina con `ASIC model YAML file chips/BM1370.yaml not found`.
Los ficheros viejos de la raíz se quedan ahí sin que nadie los lea; borrarlos es
opcional.

## Antes de nada: comprueba en qué directorio estás copiando

Tu `git log` dice `b4b6b14`, que es el refactor de julio **sin la estrategia de
estabilidad comiteada**. Pero tu contenedor sí la está corriendo: el CSV con las
tres columnas nuevas y `BITAXEPID_CONFIG=safe-BM1370-estabilidad.yaml` lo prueban.

Hay dos explicaciones y hay que saber cuál es antes de copiar:

**(a) Los archivos están ahí pero sin comitear.** Lo más probable: los pusiste a
mano y `git log` no los ve porque nunca entraron en un commit. En ese caso este
directorio *es* el correcto, y copiar encima sobrescribe tus versiones — que es
justo lo que quieres, pero mira antes qué tienes.

**(b) El código corre desde otro directorio.** Entonces copiar aquí no cambiaría
nada de lo que se ejecuta.

**Para distinguirlo:**

    cd ~/BitaxePID
    ls -la tuning_estabilidad.py safe-BM1370-estabilidad.yaml tests/ 2>&1
    git status --short
    cat .env 2>/dev/null
    sudo docker inspect bitaxepid --format '{{.Config.Image}}{{"\n"}}{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'

Si `tuning_estabilidad.py` existe y `git status` lo marca como `??`, es el caso
(a): sigue adelante aquí. Si no existe, búscalo:

    ls -d ~/*/ && grep -rl "tuning_estabilidad" ~ --include=*.py 2>/dev/null

y copia en el directorio que tenga el `docker-compose.yml` con el que construiste
la imagen que está corriendo.

## Los archivos

| Archivo | Qué es |
|---|---|
| `tuning_estabilidad.py` | la estrategia entera |
| `perfiles/gamma-estabilidad.yaml` | el perfil de configuración (**movido y renombrado**) |
| `chips/BM1370.yaml` | límites de fábrica del chip: mismos valores, **directorio nuevo** |
| `tests/test_estabilidad.py` | la verificación contra chip simulado (nuevo) |
| `tuning_manager.py` | bucle de tuning: adopta cambios de AxeOS, no muere por una excepción suelta |
| `bitaxepid.py` | activa la estrategia con `ERROR_TUNING` |
| `logger.py` | CSV y snapshot propios del perfil de estabilidad |
| `config.py` | **nuevo en esta tanda:** aborta si los límites están invertidos; ya no exige las claves del PID y avisa de lo que toma por defecto |
| `api_client.py` | **nuevo en esta tanda:** `set_settings` informa si el miner aceptó |
| `stratum.py` | **nuevo en esta tanda:** un pool mal escrito ya no aborta la medición |
| `tuning.py` | **nuevo en esta tanda:** la otra estrategia (la de `ERROR_TUNING: FALSE`), reescrita sin PID y sin hashrate |
| `cli.py` | **nuevo en esta tanda:** `--voltage` y `--frequency` ya no aceptan decimales; añade `--dry-run` |
| `Containerfile` | **nuevo en esta tanda:** copia `chips/` y `perfiles/` a la imagen. **Sin esto el contenedor no arranca** |
| `docker-compose.yml` | **nuevo en esta tanda:** el perfil por defecto pasa a `perfiles/gamma-estabilidad.yaml` |

`tuning.py` no es la estrategia que tú corres (tú tienes `ERROR_TUNING: TRUE`),
pero tiene que ir en el paquete igualmente: `bitaxepid.py` lo importa siempre, y
el nuevo `bitaxepid.py` le pasa parámetros que el `tuning.py` viejo no acepta. Si
copias uno sin el otro, el arranque falla con un `TypeError`.

Además de los arreglos de la tanda anterior (la RAMPA ya no abandona por el calor
del ajuste anterior, y se adoptan los cambios hechos por la web de AxeOS), esta
tanda cierra catorce hallazgos de revisión.

Un tercer arreglo de esa tanda **ya no está vigente**: entonces el voltaje pasó a
ser la palanca térmica, y eso se revirtió a propósito. Hoy el calor baja
**frecuencia** primero, y voltaje solo con la frecuencia ya en `MIN_FREQUENCY`,
porque bajar voltaje sube los errores justo cuando el chip va más forzado. Es lo
que verás en el log, y está en «Comprobar que los tres arreglos están vivos».

Los dos primeros hallazgos son los que dejaban el hardware sin supervisión:

1. **Límites invertidos saltaban el tope de voltaje.** El recorte de seguridad es
   `max(mínimo, min(máximo, valor))`, correcto sólo si mínimo ≤ máximo. Con
   `MIN_VOLTAGE` por encima de `MAX_VOLTAGE` devolvía el mínimo, o sea un valor
   *por encima* del tope que existe para imponer. Ahora `config.py` no arranca.
2. **Una excepción suelta mataba el bucle para siempre.** El `try/except` estaba
   fuera del `while`: cualquier fallo imprevisto salía del bucle y el proceso
   terminaba con código 0, así que `restart: unless-stopped` lo tomaba por salida
   limpia. El miner se quedaba con el último ajuste y sin nadie vigilando la
   temperatura. Ahora el manejo es por muestra.
3. **`set_settings` no distinguía éxito de fallo.** Devolvía la frecuencia pedida
   con un 200, con un 500 y con una excepción. El bucle daba por aplicado un
   ajuste que el miner no tenía, y a la muestra siguiente lo interpretaba como un
   cambio del usuario en AxeOS: un fallo de red tiraba la ventana de errores.
4. Un pool sin clave `endpoint` lanzaba `KeyError` y abortaba la medición de todos
   los demás; el mensaje de error podía enmascararlo con un `UnboundLocalError`.
5. Dos ramas inalcanzables en `_optimizar`, restos de cuando la condición era más
   ancha. Describían comportamiento que ya no existe.
6. El docstring del módulo decía que la RAMPA sube voltaje «un paso por muestra»,
   cuando va a `MAX_VOLTAGE` de golpe en la primera.
7. El endpoint `:8093/metrics` publicaba la configuración entera sin autenticación
   (incluidas URLs de pool). Ahora se filtran las claves sensibles.
8. `ERROR_SETTLE: 0` descartaba una muestra al arrancar y ninguna después.

Y seis más, por orden de aparición:

9. **La frecuencia arrastraba decimales toda la ejecución.** Lo viste en el CSV:
   493.75, 498.75, 503.75… El valor con coma entra de fuera (la web de AxeOS
   permite valores libres, y `--frequency` los aceptaba), el tuner lo adoptaba
   tal cual y luego le sumaba pasos enteros encima, así que el desfase no se
   corregía nunca. Ninguno de esos valores es uno que hayas configurado. Ahora
   lo que llega de AxeOS se lleva al múltiplo de `FREQUENCY_STEP` más cercano al
   adoptarlo, las dos estrategias devuelven enteros, y `cli.py` rechaza los
   decimales en el momento en vez de dejarlos entrar.

10. **La otra estrategia no volvía a subir la frecuencia después de bajarla.**
    No te afecta hoy (corres `ERROR_TUNING: TRUE`), pero era un fallo real: la
    única rama que subía frecuencia estaba dentro de un `elif hashrate <
    setpoint`, y con el hashrate cumpliendo el objetivo el tuner caía en un
    `else` que no proponía nada. Los MHz que quitaba el calor no volvían jamás.
    `tuning.py` está reescrito: fuera el PID y fuera el hashrate. Decide solo con
    temperatura, potencia y errores, con cinco reglas por prioridad — el calor
    baja frecuencia, el límite de potencia baja voltaje, los errores por encima
    del objetivo suben voltaje, el margen térmico sube frecuencia, y estar varias
    muestras seguidas sin errores baja voltaje buscando el mínimo.

11. **Bajar el voltaje tardaba dos horas y media en dar el primer paso.** Y no
    hacía falta. La espera de la búsqueda del voltaje mínimo usaba el mismo
    contador que el reintento de frecuencia (`ERROR_RETRY_CEILING`, 50
    decisiones), pero las dos cosas no cuestan lo mismo: reintentar una
    frecuencia que ya falló sube el calor y los errores de golpe, mientras que
    un paso de 10 mV se mide en 4 minutos y, si se pasa, la prioridad 3 lo
    devuelve arriba en la decisión siguiente y `_v_suelo` impide repetirlo.
    Ahora la bajada tiene su propia perilla, `LOWER_VOLTAGE_AFTER`, con 4 por
    defecto.

    Medido con el ruido real (desviación 1.24), 30 semillas, tiempo por encima
    del objetivo del 2 % y cuánto tarda el primer paso a 30 s por muestra:

    | Espera | Incumple | Primer paso |
    |---|---|---|
    | 1 | 4.5 % | 22 min |
    | 2 | 4.3 % | 25 min |
    | **4 (por defecto)** | **3.1 %** | **30 min** |
    | 10 | 1.9 % | 44 min |
    | 50 (lo que había) | 0.0 % | 144 min |

    El 4 es el codo de la curva. **No es gratis**, y conviene que lo sepas: con
    tus límites concretos (1180-1210 mV, o sea tres pasos) el primer paso pasa de
    28 a 6 minutos, y el tiempo por encima del 2 % sube del 0 % al 2-6 %. Sigue
    por debajo del 6-9 % que da el lazo completo, pero es peor que antes en ese
    aspecto. Si prefieres el comportamiento anterior, pon `LOWER_VOLTAGE_AFTER:
    50` en el YAML y queda exactamente como estaba.

12. **La validación de arranque exigía siete claves que nadie lee.** Un perfil
    limpio y correcto para la estrategia de estabilidad no arrancaba: `config.py`
    pedía las seis ganancias `PID_*` y `HASHRATE_SETPOINT`, y salía con
    `Missing required config keys: PID_FREQ_KP, ...`. Ninguna de las dos
    estrategias las mira — no queda ningún PID en el programa y el hashrate no
    interviene en ninguna rama. Lo único que hacen es rellenar siete columnas del
    CSV. Ahora sólo se exigen con `ERROR_TUNING` desactivado, donde ese CSV se
    compara con historiales antiguos. **A ti no te cambia nada**: tu YAML las
    declara, y declararlas sigue siendo válido.

    De paso, trece claves que se leían con un valor por defecto escrito en la
    llamada (`ERROR_WINDOW`, `ERROR_SETTLE`, `TEMP_MARGIN`, `METRICS_SERVE`…) ya
    no llevan su defecto suelto en cada sitio: hay una sola tabla en `config.py` y
    el arranque avisa por log de las que falten y del valor que va a usar. El
    aviso que importa es el de `ERROR_TUNING`: si esa línea se borra del YAML, el
    defecto es `FALSE`, o sea **la otra estrategia**, y antes todo lo demás que
    declara el perfil se ignoraba sin decir nada. Ahora sale un `WARNING` claro.
    Lo fija un test nuevo de 18 comprobaciones que se queda en el repositorio
    (`tests/test_claves_config.py`; no va en el paquete porque comprueba también
    ficheros que no se envían), incluida una que recorre los `.py` del proyecto
    para que nadie vuelva a escribir un defecto por su cuenta.

    Los otros dos ficheros de esa tanda (`.env.example` y `docker-compose.yml`,
    que apuntaban por defecto al perfil equivocado, y `safe-BM1370.yaml`, que
    heredaba de fábrica sus dos suelos) **no viajan en este paquete**: son del
    repositorio y no afectan a tu nodo.

13. **La documentación te mandaba buscar en el log frases que el programa no
    escribe.** Es el hallazgo más incómodo de la tanda, porque el fallo caía del
    lado equivocado: si el `grep` sale vacío, la conclusión no es «la
    documentación está mal», es «el arreglo no está puesto» — y de ahí a deshacer
    un cambio que estaba bien. `UMBREL.md` prometía `Increasing voltage to`,
    `System stable at` y `Reducing frequency to`; el fork tradujo las decisiones
    al castellano hace tiempo y esos tres textos no están en ningún `.py`. La
    única aparición de `System stable` en todo el árbol es un comentario que
    explica por qué se quitó. Ahora cita las de verdad, y hay un test nuevo
    (`tests/test_citas_de_log.py`, 13 comprobaciones) que falla si la
    documentación vuelve a citar algo que el código no emite.

    De paso quedan avisadas las dos formas de que un `grep` correcto salga vacío,
    que son distintas: en el **log**, porque el programa mete valores en medio de
    la frase; en el **fuente**, porque una frase larga está partida en varias
    líneas y `grep` compara línea a línea. El `grep -c "calor del ajuste
    anterior"` de más arriba está elegido para que quepa en una línea, y el test
    lo comprueba.

    También se ha quitado `simple-pid` de `requirements.txt`: no queda ningún PID
    y nadie importaba el módulo, así que el `Containerfile` lo instalaba en tu
    nodo para no ejecutarlo nunca. `scripts/smoke_test.sh` ahora comprueba las
    dependencias **en los dos sentidos** (nada importado sin declarar, nada
    declarado sin importar), que es lo que faltaba para que esa deriva no pasara
    inadvertida.

    De los ficheros de este hallazgo **solo `bitaxepid.py` viaja en el paquete**
    (le sobraba `simple_pid` en el docstring). `requirements.txt`,
    `scripts/smoke_test.sh`, `README.md` y `UMBREL.md` son del repositorio y no
    llegan a tu nodo; el `requirements.txt` que usa tu imagen es el que ya tienes
    ahí, así que si quieres que el nodo deje de instalar `simple-pid` hay que
    copiar ese fichero aparte — **no hace falta**: instalar un paquete de más no
    rompe nada, solo alarga el `build`.

14. **Y el mismo fallo, en un quinto documento que no había revisado nadie.**
    `parches-estabilidad/APLICAR.md` describe la entrega de cuatro parches de
    hace unas tandas, y se había quedado congelado en ese momento mientras el
    código seguía. Dos cosas de las que decía eran ya falsas, y las dos en la
    dirección peligrosa:

    - Contaba que el calor baja **voltaje** primero y frecuencia después. Es al
      revés desde `d2ef8dc`, que revirtió ese comportamiento a propósito — bajar
      voltaje sube los errores justo cuando el chip va más forzado. Un documento
      que invierte el orden no es una errata de redacción: describe otro
      comportamiento de seguridad.
    - Mandaba buscar en el log «el voltaje ya no puede bajar sin pasarse del
      ...% de errores». Esa frase no existe en ningún `.py`, ni existió nunca. Y
      catorce líneas más abajo ofrecía un `git revert` de cuatro commits, que hoy
      tiene siete commits por encima y ya no es seguro. O sea: el `grep` sale
      vacío, parece que el arreglo térmico no está, y justo debajo hay un comando
      destructivo esperando. Ahora el documento está marcado como histórico, la
      frase desmentida, y el `git revert` sustituido por el respaldo de
      `/tmp/bitaxepid-antes`.

    Se me escapó en el hallazgo 13 por una razón que conviene decir: el test que
    escribí entonces miraba `README.md`, `UMBREL.md` y este `LEEME.md`, pero no
    ese fichero, así que la suite pasaba en verde con el error dentro. Ahora
    recorre **todos** los `.md` del árbol, distingue citar una frase para
    desmentirla de mandar buscarla, y comprueba en el propio código que la palanca
    térmica sigue siendo la frecuencia. Son 21 comprobaciones en vez de 13.

    Nada de esto viaja en el paquete: `parches-estabilidad/` es del repositorio.

Verificado aquí: la suite completa pasa (126 tests, OK) con las dependencias
instaladas, y `tests/test_estabilidad.py` termina en `Todas las comprobaciones
pasan.` (13 bloques).

### Cuidado con el YAML: sus valores no son los tuyos

El `perfiles/gamma-estabilidad.yaml` de aquí trae mis valores, no los que tienes
puestos en el nodo. Copiarlo tal cual te cambia cuatro cosas:

| Clave | Tú tienes | Este trae |
|---|---|---|
| `ERROR_TARGET_PERCENT` | 1.5 | 2.0 |
| `SAMPLE_INTERVAL` | 60 | 30 |
| `ERROR_SETTLE` | 3 | 1 |
| `INITIAL_FREQUENCY` | 500 | 475 |

(El 1.5 medido en `:8093/metrics` del nodo, campo `error_target`, con el tuner
llevando dos días corriendo. Antes decia aqui 1.0, que era incorrecto.)

Los tres arreglos están en el código, **no en el YAML**. Si quieres conservar tu
configuración, guarda la tuya antes y vuelve a ponerla después:

    cp safe-BM1370-estabilidad.yaml /tmp/mi-yaml-anterior.yaml

(Ése es el nombre que tiene **en tu nodo**, en la raíz. El que llega se llama
`perfiles/gamma-estabilidad.yaml`, así que no se pisan: el paso 4 explica cómo
llevar tus valores al fichero nuevo.)

`ERROR_TARGET_PERCENT` es tu decisión: tras dos días el nodo estaba a 900 MHz /
1202 mV con **0 % de errores**, o sea que cumple el 1.5 con margen de sobra.
Subirlo a 2.0 le da recorrido para bajar voltaje y ahorrar vatios; dejarlo en 1.5
es más conservador y ya se sabe que se alcanza. `SAMPLE_INTERVAL: 30` y
`ERROR_SETTLE: 1` son los que recomiendo, porque a 60 s y 3 descartes cada paso
hacia abajo cuesta 4 minutos y la convergencia se va a horas — pero son
recomendación, no requisito.

### Sembrar el punto ya convergido, para no repetir la rampa

El arranque no carga el snapshot: empieza en `INITIAL_FREQUENCY` y sube de
`FREQUENCY_STEP` en `FREQUENCY_STEP` una vez por muestra. Con 475 y pasos de 5 a
30 s, volver a los 900 MHz que el nodo ya había encontrado son ~43 minutos de
estado RAMPA. Si quieres saltártelos, siembra el punto conocido (medido en
`:8093/metrics` antes de reiniciar):

    sed -i 's/^INITIAL_FREQUENCY: 475/INITIAL_FREQUENCY: 900/; \
            s/^INITIAL_VOLTAGE: 1185/INITIAL_VOLTAGE: 1200/' perfiles/gamma-estabilidad.yaml

Los dos siguen dentro de los límites duros (900 < 925 y 1200 < 1210), asi que
`clamp_initial_values` no los recorta. Es lo que el propio YAML recomienda en el
comentario de `INITIAL_FREQUENCY`: subir el arranque cerca del punto de trabajo
real en vez de agrandar el paso.

Los límites duros (1180-1210 mV, 475-925 MHz, `TARGET_TEMP: 60`) y
`MANAGE_MINER_POOLS: FALSE` son idénticos en las dos versiones. Nada de esto
escribe la configuración de pools del miner.

## Cómo copiarlos

En el directorio correcto del Umbrel (el que localizaste arriba). Los pasos en
este orden:

**1. Copia de seguridad de lo que hay ahora**, por SSH en el Umbrel y **antes de
mandar nada**. Vale para los dos casos y no depende de git:

    ssh umbrel@<ip-del-umbrel>
    cd ~/BitaxePID                      # o el que sea
    cp -a . /tmp/bitaxepid-antes        # respaldo completo, por si acaso

Deja esta sesión SSH abierta: la necesitas en los pasos 3 y siguientes.

**2. Mándalos desde Windows con `scp`**, directamente desde mi carpeta de
trabajo. Abre **PowerShell** (en tu Windows, no en el Umbrel):

    $ORIGEN = "C:\Users\garda\AppData\Local\Claude-3p\local-agent-mode-sessions\93187a49\00000000\local_daff86a4-b64c-492d-a31c-e415194b3388\outputs\archivos-para-umbrel"
    $UMBREL = "umbrel@<ip-del-umbrel>"

    cd $ORIGEN
    scp *.py Containerfile docker-compose.yml SHA256SUMS.txt "${UMBREL}:~/BitaxePID/"
    scp chips\BM1370.yaml "${UMBREL}:~/BitaxePID/chips/"
    scp perfiles\gamma-estabilidad.yaml "${UMBREL}:~/BitaxePID/perfiles/"
    scp tests\test_estabilidad.py "${UMBREL}:~/BitaxePID/tests/"

Sustituye `<ip-del-umbrel>` por la IP de tu nodo, y `~/BitaxePID` por el
directorio que localizaste arriba si no es ése. Te pedirá la contraseña de
`umbrel` una vez por comando.

**`chips/` y `perfiles/` no existen todavía en tu nodo**, y `scp` no los crea. Los
tres últimos comandos fallarán con `No such file or directory` si no los creas
primero, desde la sesión SSH del paso 1:

    cd ~/BitaxePID && mkdir -p chips perfiles tests

Alternativa, mandar la carpeta entera de una vez y repartir ya en el Umbrel. Es
más cómoda y no depende de crear nada por adelantado:

    scp -r $ORIGEN "${UMBREL}:~/"

y luego, por SSH:

    cd ~/BitaxePID
    mkdir -p chips perfiles tests
    cp ~/archivos-para-umbrel/*.py ~/archivos-para-umbrel/Containerfile \
       ~/archivos-para-umbrel/docker-compose.yml \
       ~/archivos-para-umbrel/SHA256SUMS.txt .
    cp ~/archivos-para-umbrel/chips/BM1370.yaml chips/
    cp ~/archivos-para-umbrel/perfiles/gamma-estabilidad.yaml perfiles/
    cp ~/archivos-para-umbrel/tests/test_estabilidad.py tests/

**3. Comprueba que llegaron enteros** (por SSH en el Umbrel, dentro del repo, y
ahora, antes de retocar el YAML):

    cd ~/BitaxePID
    sha256sum -c SHA256SUMS.txt

Los catorce deben decir `OK`, incluidos `chips/BM1370.yaml` y
`perfiles/gamma-estabilidad.yaml` con su directorio delante. Si alguno dice
`FAILED`, la transferencia se corrompió: vuelve a mandar ese archivo. Si dice
`No such file or directory`, no llegó — casi siempre porque el directorio no
existía (ver el paso 2). `LEEME.md` no está en la lista.

Cuando termines puedes borrar el `SHA256SUMS.txt` del repo, no hace falta ahí:

    rm SHA256SUMS.txt

**4. Apunta el `.env` al nombre nuevo. Este paso no es opcional:** tu `.env` dice
`safe-BM1370-estabilidad.yaml`, ese fichero ya no es el que el programa espera, y
un `--config` que no existe **aborta el arranque** en lugar de seguir con los
límites de fábrica.

    cd ~/BitaxePID
    nano .env
    # BITAXEPID_CONFIG=perfiles/gamma-estabilidad.yaml

Con el directorio delante: es la ruta que ve el programa dentro del contenedor.

**5. Recupera tu configuración si la quieres** (ver el aviso del YAML más
arriba). Ahora el destino es el fichero nuevo, no el viejo:

    cp /tmp/bitaxepid-antes/safe-BM1370-estabilidad.yaml perfiles/gamma-estabilidad.yaml

Ojo con hacerlo así: te devuelve tu perfil entero, incluidos `SAMPLE_INTERVAL: 60`
y `ERROR_SETTLE: 3`. Si solo quieres conservar `ERROR_TARGET_PERCENT: 1.0`, edita
esa línea en el fichero nuevo en vez de sobrescribirlo.

Antes de reconstruir, compruébalo en seco. No conecta con ningún miner y dice de
qué fichero sale cada valor:

    python3 bitaxepid.py --dry-run --asic BM1370 --config perfiles/gamma-estabilidad.yaml

Termina con código 0 si la configuración es válida y 1 si no. Todas las líneas
deben decir `<- perfiles/gamma-estabilidad.yaml`: si alguna dice
`<- chips/BM1370.yaml`, esa clave la estás heredando de los límites de fábrica.

A partir de aquí `sha256sum -c` fallará en el YAML, y es lo esperado.

**6. Guárdalo en git**, que es lo que te deja comparar y volver atrás:

    git add -A && git commit -m "estrategia de estabilidad con los tres arreglos de campo"

Si al hacer `git diff` te aparecen archivos "cambiados" con `old mode 100644 / new
mode 100755` y cero líneas de diferencia, es solo el bit de ejecución. `scp`
normalmente no lo arrastra, pero por si acaso:

    chmod 644 *.py chips/*.yaml perfiles/*.yaml tests/*.py

## Compilar y probar

Todo esto por SSH, en el directorio del repo (el que tiene `docker-compose.yml`).

### 1. Construir la imagen

    cd ~/BitaxePID
    sudo docker compose build

Tarda unos minutos la primera vez (baja `python:3.12-slim` e instala las
dependencias); las siguientes reutiliza la caché. Debe acabar sin errores. Esto
**no arranca nada** todavía: la imagen se construye y el contenedor que corre
ahora sigue con el código viejo.

Si falla en el `pip3 install`, suele ser red del nodo; repite el comando.

### 2. Pasar el test, sin tocar el miner

    sudo docker compose run --rm \
      -v "$PWD/tests:/app/tests" \
      --entrypoint python3 bitaxepid tests/test_estabilidad.py

Debe terminar en `Todas las comprobaciones pasan.` Usa un chip simulado: no habla
con el miner ni cambia su ajuste.

Dos detalles que explican por qué el comando es así:

- **El `-v` hace falta.** El `Containerfile` copia la raíz, `chips/` y
  `perfiles/`, pero no `tests/`, así que el test no está dentro de la imagen. Sin
  montarlo, el comando falla con `can't open file '/app/tests/test_estabilidad.py'`.
  (Los comodines de `COPY` no bajan a subdirectorios: de ahí las dos líneas
  explícitas para los YAML.)
- **Tiene que ser dentro del contenedor.** Si lo lanzas en el sistema con
  `python3 tests/test_estabilidad.py` sale `ModuleNotFoundError: pyfiglet`, que
  no es un fallo del test: las dependencias viven en la imagen, no en el host.
  (Si lo prefieres en el host: `pip3 install pyfiglet rich pyyaml urllib3`. No
  hace falta para desplegar. `simple-pid` ya no está en la lista: no queda ningún
  PID en el programa y nadie lo importaba, así que se ha quitado de
  `requirements.txt`.)

### 3. Ver el arranque antes de dejarlo suelto

Si quieres comprobarlo contra tu miner de verdad sin dejarlo corriendo, arráncalo
en primer plano:

    sudo docker compose up

Muestra el log en la terminal. `Ctrl+C` lo para y lo deja parado. Mira que el
perfil cargado sea el tuyo:

    Initializing hardware: Voltage=1185mV, Frequency=500MHz

Si ves `Voltage=1150mV, Frequency=550MHz` es que **no** se cargó
`perfiles/gamma-estabilidad.yaml`: son los valores de fábrica del BM1370. Revisa
`BITAXEPID_CONFIG` en `.env`, que es lo que hay que editar en esta tanda (paso 4).

Con este código el log lo dice antes, en una línea propia:

    INFO - 32 claves, todas declaradas en perfiles/gamma-estabilidad.yaml: no se hereda nada de chips/BM1370.yaml

Y debe aparecer también:

    Gestion de pools desactivada: se respeta la configuracion stratum del miner.

Eso confirma que no va a tocar tu configuración de pools.

**No te extrañe si en la primera muestra sale esto:**

    Ajuste cambiado fuera del tuner: el miner esta en 1195mV/495MHz y no en
    1185mV/500MHz. Se adopta y se sigue optimizando desde ahi.

Es el arreglo funcionando, no un error. El tuner arranca escribiendo los
`INITIAL_*` del YAML, luego lee el miner de verdad y, si no coinciden —porque el
contenedor anterior lo dejó en otro punto, o porque tocaste AxeOS— se queda con lo
del miner en vez de reimponer lo suyo. Es lo que pediste.

### 4. Dejarlo corriendo

    sudo docker compose up -d --build
    sudo docker compose logs -f

**`--build` es obligatorio.** Por el mismo `COPY` de antes, sin reconstruir la
imagen se sigue ejecutando el código viejo aunque los archivos del disco estén
actualizados. Un `restart` no sirve para nada aquí.

Para pararlo: `sudo docker compose down`. `Ctrl+C` en el `logs -f` solo sale del
log, no para el contenedor.

En el Umbrel los comandos de docker necesitan `sudo`: el usuario `umbrel` no está
en el grupo `docker`.

### Comprobar que corre el código nuevo

    sudo docker compose exec bitaxepid grep -c "calor del ajuste anterior" tuning_estabilidad.py

Si responde `1`, la imagen lleva los arreglos. Si responde `0` o da error, el
`--build` no llegó a aplicarse.

## Comprobar que los tres arreglos están vivos

    sudo docker compose logs -f --tail 50

Los `...` de abajo son valores que el programa mete en medio de la frase. Si vas a
buscar con `grep`, **usa solo el trozo anterior al primer `...`** —
`grep "Bajando frecuencia"`, no la frase entera— porque el texto real lleva los
números intercalados y una frase copiada completa no encontrará nada. Que un
`grep` salga vacío por eso no significa que el arreglo no esté.

Lo mismo pasa al revés cuando buscas dentro de un `.py` en vez de en el log (como
el `grep -c` de más arriba): ahí las frases largas están partidas en varias líneas
del código, y `grep` compara línea a línea, así que una frase que en el log sale
seguida puede no aparecer en ninguna línea del fuente. Para comprobar la imagen
usa el comando tal cual está escrito arriba, que sí cabe en una línea.

- Al arrancar en caliente, en vez de saltar a `BUSCAR_VOLTAJE` en dos segundos:
  `RAMPA: ...C al arrancar puede ser calor del ajuste anterior; se baja pero no
  se abandona la rampa (N muestras por confirmar)`
- `RAMPA: voltaje al maximo ...mV antes de subir frecuencia`, y luego
  `RAMPA: subiendo frecuencia a ...MHz` sin tocar el voltaje
- Si cambias el ajuste desde AxeOS: `Ajuste cambiado fuera del tuner: el miner
  esta en ...mV/...MHz ... Se adopta y se sigue optimizando desde ahi.`
- Al pasarse de `TARGET_TEMP`: `Bajando frecuencia a ...MHz por temperatura
  ...`, y solo cuando ya se está en `MIN_FREQUENCY`, `Bajando voltaje a ...mV
  por temperatura ...: ya en la frecuencia minima ...MHz`. La palanca térmica es la **frecuencia**: es
  lo que pediste, y además bajar voltaje sube los errores, o sea que usarlo
  contra el calor empeoraba la estabilidad justo cuando el chip va más forzado.
- Tras un rato estable: `OPTIMIZAR: estable N decisiones a ...C con errores
  ...%, bajando voltaje a ...mV para buscar el minimo`. Con
  `LOWER_VOLTAGE_AFTER: 4` esto aparece a los pocos minutos, no a las dos horas.

## Para volver atrás

Usa el respaldo del paso 1, que funciona en los dos casos:

    cd ~/BitaxePID
    cp -a /tmp/bitaxepid-antes/. .
    sudo docker compose up -d --build

**No uses `git reset --hard`.** Si estabas en el caso (a) —los archivos ahí pero
sin comitear— un reset te borraría precisamente el código que hoy te funciona,
porque git nunca lo tuvo registrado. Solo es seguro si comprobaste que
`git status` estaba limpio antes de empezar.
