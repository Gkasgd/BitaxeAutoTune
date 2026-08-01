# BitaxePID en Umbrel, con límites seguros

Objetivo: dejar el tuner corriendo en el Umbrel apuntando a tu Bitaxe Gamma
(BM1370) con el perfil por defecto, `perfiles/gamma-estabilidad.yaml`: **60 °C de
objetivo, 1180-1210 mV y 475-925 MHz**, buscando el voltaje mínimo que mantenga
los errores de hardware por debajo del **2 %**.

## Antes de empezar

Dale al miner una **IP fija** (reserva DHCP en el router). El contenedor no
puede descubrirlo por mDNS, así que si la IP cambia, el tuner se queda hablando
solo.

Apunta también la IP del Umbrel y comprueba que tienes SSH. Por defecto el
usuario es `umbrel`.

## Puesta en marcha

Por SSH al Umbrel:

```bash
ssh umbrel@<ip-del-umbrel>

git clone https://github.com/Gkasgd/BitaxeAutoTune.git
cd BitaxeAutoTune

cp .env.example .env
nano .env          # pon la IP de tu miner en BITAXEPID_MINER_IP

docker compose up -d --build
docker compose logs -f
```

`BITAXEPID_CONFIG` ya viene con `perfiles/gamma-estabilidad.yaml`, así que no hay
que tocarlo. Incluye el directorio: los perfiles viven en `perfiles/` y los
límites de fábrica en `chips/`, y la ruta es la que ve el programa dentro del
contenedor. Dejarlo **vacío** sí es mala idea: entonces manda el YAML de fábrica
del chip que reporte el miner, con `ERROR_TUNING` sin declarar y por tanto la
*otra* estrategia.

Si vienes de una instalación anterior, tu `.env` apunta al nombre viejo
(`safe-BM1370-estabilidad.yaml`) y hay que editarlo: un `--config` que no existe
aborta el arranque en lugar de seguir con los límites de fábrica.

En el log tienen que aparecer, en este orden:

```
INFO - Initialized BitaxeAPIClient for <ip> with timeout=10s, retries=5, pool_maxsize=10
INFO - 32 claves, todas declaradas en perfiles/gamma-estabilidad.yaml: no se hereda nada de chips/BM1370.yaml
INFO - Estrategia de estabilidad: objetivo 2.0% de errores de hardware, temperatura objetivo 60.0C. El hashrate no interviene en las decisiones.
INFO - Gestion de pools desactivada: se respeta la configuracion stratum del miner. Usa --manage-pools o MANAGE_MINER_POOLS para permitir que BitaxePID la cambie.
INFO - Initializing hardware: Voltage=1185mV, Frequency=475MHz
INFO - Applied settings: Voltage=1185mV, Frequency=475MHz
INFO - Metrics server started on http://0.0.0.0:8093/metrics
INFO - Starting BitaxePID tuner...
INFO - Starting BitaxePID tuner...
```

La línea de `Estrategia de estabilidad` es la que confirma que se cargó el perfil
correcto: si dice `Estrategia por limites`, el `--config` no llegó y estás con la
otra estrategia.

La de las 32 claves dice de dónde sale cada valor. Con este perfil no se hereda
nada, así que basta leer un fichero. Con otro que declare menos verás en su lugar
algo como `14 claves declaradas en X; 10 heredadas de chips/BM1370.yaml: ...`, y
esas 10 salen de los límites de fábrica, no de tu perfil.

## Validar un perfil sin encender el miner

Antes de subir un cambio al nodo puedes comprobarlo en seco, sin conexión de
ninguna clase:

```bash
python bitaxepid.py --dry-run --asic BM1370 --config perfiles/gamma-estabilidad.yaml
```

Carga los dos YAML, los fusiona, los valida y saca una tabla con el valor
efectivo de cada clave y **el fichero del que viene**, más las opcionales que
no declara nadie y quedan en el defecto del programa. Termina con código 0 si
la configuración es válida y 1 si no. Hay que pasarle `--asic` porque el modelo
de chip lo reporta el propio miner, y aquí no se le pregunta a ninguno.

Detecta lo que de verdad falla en la práctica: límites invertidos, un `--config`
que no existe, y sobre todo un perfil que baja `MAX_VOLTAGE` pero se deja
`MIN_VOLTAGE` heredado, es decir, un rango efectivo que no es el que el nombre
del fichero promete. No comprueba nada del miner ni del contenedor.

Arranca en **1185 mV / 475 MHz**, el suelo del perfil, y sube desde ahí. Si ves
`Voltage=1150mV, Frequency=550MHz` es que se están usando los valores de fábrica
del BM1370.

("Starting BitaxePID tuner" sale dos veces: está en `main()` y otra vez dentro
de `start_tuning()`. Es cosmético, viene del código original y no lo he tocado.)

`Ctrl+C` sale del log sin parar el contenedor. Para pararlo de verdad:
`docker compose down`.

## Qué va a hacer el tuner

Esta estrategia es una máquina de tres estados, y cada transición se anuncia. Lo
que sigue es una corrida real contra el miner simulado, recortada.

**1. RAMPA** — pone el voltaje en el máximo de una vez y luego sube frecuencia de
5 en 5 MHz por muestra:

```
RAMPA: voltaje al maximo 1210mV antes de subir frecuencia (temp 49.6C)
RAMPA: subiendo frecuencia a 480MHz (temp 49.85C, 1210mV, techo 925MHz)
...
Estado RAMPA -> BUSCAR_VOLTAJE: a 58.1C ya no hay margen bajo 60.0C (margen 2.0C)
```

Fíjate en que la rampa **no llega a los 925 MHz** del techo: la para la
temperatura, y con `TEMP_MARGIN: 2.0` la para 2 °C antes del objetivo. Los
925 MHz son un tope, no una meta.

**2. BUSCAR_VOLTAJE** — baja voltaje de 5 en 5 mV hasta que los errores tocan el
2 %, y entonces vuelve al último que cumplía:

```
BUSCAR_VOLTAJE: midiendo (1/7 muestras)
BUSCAR_VOLTAJE: errores 0.00% <= 2.0%, bajando voltaje a 1205mV
...
Estado BUSCAR_VOLTAJE -> OPTIMIZAR: errores 2.91% > 2.0%, volviendo a 1200mV (ultimo voltaje que cumplia)
```

Las líneas `midiendo (n/7 muestras)` no son relleno: decide con la **mediana** de
`ERROR_WINDOW: 7` muestras, porque el `errorPercentage` del miner es ruidoso y
una sola lectura cruza cualquier umbral en las dos direcciones. Con
`SAMPLE_INTERVAL: 30` eso son tres minutos y medio por decisión.

**3. OPTIMIZAR** — régimen permanente. Errores por encima del objetivo suben
voltaje; margen térmico sobrante sube frecuencia:

```
OPTIMIZAR: midiendo (3/7 muestras) en 1200mV/640MHz
OPTIMIZAR: errores 0.66% con margen, subiendo frecuencia a 645MHz
```

Cuando ya no queda nada por mover, cada muestra lo dice:

```
Estable en 1200mV/640MHz: errores 1.70% contra objetivo 2.0% (banda 1.50-2.0%), 59.0C
```

Ver `Estable en` repetido es la señal de que encontró su punto. No es un estado
final: pasadas `ERROR_RETRY_CEILING: 50` decisiones estables olvida la frecuencia
que le falló y la vuelve a intentar, por si mejoraron las condiciones — más
ventilación, menos calor en la habitación:

```
Estable 51 decisiones: reintentando la frecuencia 645MHz, que fallo antes
```

El suelo de voltaje se reintenta al doble de decisiones, con la misma forma de
línea. Es deliberado: recuperar frecuencia da hashrate, y bajar voltaje solo
ahorra unos milivatios.

**Cuando se pasa de temperatura, lo que baja es la frecuencia**, no el voltaje:

```
Bajando frecuencia a 635MHz por temperatura 60.5C > 60.0C (errores 0.66% contra objetivo 2.0%)
```

El voltaje solo se toca por calor cuando la frecuencia ya está en
`MIN_FREQUENCY`, y entonces lo dice explícitamente. El orden es deliberado:
bajar voltaje sube los errores, así que responder al calor quitando voltaje
empeora la estabilidad justo cuando el chip va más forzado.

Estas líneas de decisión **no llevan marca de tiempo**: van por stdout
(`console.print` de `rich`) y no por el logger. Están en castellano.

Si vas a buscarlas con `grep`, hazlo por el trozo **anterior al primer número**:
el texto lleva valores interpolados en medio, así que una frase entera copiada de
aquí puede no encontrar nada. `grep "Bajando frecuencia"` funciona;
`grep "Bajando frecuencia a 635MHz"` depende de que ese sea justo el valor de esa
muestra.

Los topes son duros en los dos caminos que escriben al hardware: el valor
inicial y cada propuesta del bucle. Si pides algo fuera de rango, lo recorta y lo
dice:

```
WARNING - INITIAL_VOLTAGE=1250.0mV esta fuera del rango 1180-1210mV
          (MIN_VOLTAGE/MAX_VOLTAGE): se usara 1210mV
```

**No toca la configuración de pools de tu miner** y no lo reinicia al arrancar.
Si algún día quieres lo contrario, añade `--manage-pools` al `command` del
compose; es mejor eso que dejarlo activado en un fichero. Ojo: entonces entra en
juego `user.yaml`, que viene **con la dirección del dueño del fork**: si tu miner
no tiene usuario configurado en AxeOS, minarías ahí y no a tu dirección, y nada
en el log lo dice. Edítalo antes.

## Comprobar que los límites están puestos

La forma rápida, desde cualquier navegador de tu red:

```
http://<ip-del-umbrel>:8093/metrics
```

Los primeros segundos devuelve exactamente `{"endpoints": []}`: la lista se
rellena con la primera muestra del bucle, no al arrancar. Espera un
`SAMPLE_INTERVAL` y vuelve a mirar. Dentro de `pid_settings` tienen que estar tus
números:

```json
"MIN_VOLTAGE": 1180, "MAX_VOLTAGE": 1210,
"MIN_FREQUENCY": 475, "MAX_FREQUENCY": 925,
"TARGET_TEMP": 60.0, "ERROR_TUNING": true, "ERROR_TARGET_PERCENT": 2.0
```

Si ahí ves `1250` y `625`, el perfil no se aplicó. Junto a `pid_settings`, cada
muestra trae además `"estado": "RAMPA"` (o `BUSCAR_VOLTAJE`, u `OPTIMIZAR`),
`error_percent` y `error_target`, que es la forma de ver en qué fase va sin leer
el log.

Ojo: sirve JSON, no el formato de Prometheus, así que Prometheus no lo puede
raspar directamente.

En `pid_settings` también aparecen `HASHRATE_SETPOINT` y las seis ganancias
`PID_*`. **No se leen**: se publican porque el volcado incluye la configuración
entera. No hay ningún PID en este programa.

El historial de tuning queda en `data/` dentro del clon, que sobrevive a
`docker compose down`.

## Ajustar el perfil

Todo está en `perfiles/gamma-estabilidad.yaml`, con un comentario por clave
explicando el por qué. Declara **las 32 claves legibles** de forma explícita, sin
heredar nada de `chips/BM1370.yaml`, para que leyendo un solo fichero sepas con
qué corre. Los que probablemente querrás tocar:

| Clave | Valor | Para qué |
|---|---|---|
| `TARGET_TEMP` | 60.0 | Temperatura objetivo: para la rampa y dispara la bajada |
| `ERROR_TARGET_PERCENT` | 2.0 | Errores de hardware que se aceptan. Es el criterio central |
| `MAX_VOLTAGE` | 1210 | Tope de voltaje, y donde RAMPA lo pone de entrada |
| `MIN_VOLTAGE` | 1180 | Suelo del voltaje |
| `MAX_FREQUENCY` | 925 | Tope de frecuencia (la temperatura para la rampa mucho antes) |
| `MIN_FREQUENCY` | 475 | Suelo: hasta dónde baja la rama térmica |
| `SAMPLE_INTERVAL` | 30 | Segundos entre muestras |
| `ERROR_WINDOW` | 7 | Muestras de la mediana. Súbelo si las decisiones te parecen nerviosas |
| `TEMP_MARGIN` | 2.0 | Margen que exige para subir, y evita el sube-baja de un paso |
| `POWER_LIMIT` | 30.0 | Actúa alrededor de 32 W (se compara contra `POWER_LIMIT * 1.075`) |

Después de editar: `docker compose restart`.

### El otro perfil, `perfiles/gamma-conservador.yaml`

Es la alternativa conservadora, y usa la **otra** estrategia (`ERROR_TUNING` sin
declarar, decide solo con temperatura y potencia): 55 °C, 1100-1150 mV,
425-500 MHz, arranque en 1100 mV / 450 MHz, muestras de 60 s. Se pasa con:

```bash
docker compose down
# BITAXEPID_CONFIG=perfiles/gamma-conservador.yaml en .env
docker compose up -d
```

Con él no verás ninguna línea `RAMPA:` ni `BUSCAR_VOLTAJE:`, porque esos estados
no existen en esa estrategia; el arranque dirá `Estrategia por limites`. No está
probado en hardware real. Si no tienes un motivo concreto para elegirlo, quédate
con el de estabilidad.

## Si algo va mal

**El contenedor se reinicia en bucle.** `docker compose logs --tail 50`. Lo más
probable es la IP: si el miner no responde, el programa registra
`Failed to fetch system info from API` y termina, y `restart: unless-stopped` lo
vuelve a levantar. No falla rápido — el cliente HTTP hace 5 reintentos con
backoff, así que verás medio minuto de `Retrying (Retry(total=...))` antes de que
se rinda. Comprueba con `curl http://<ip-del-miner>/api/system/info` desde el
propio Umbrel.

**`User config file perfiles/gamma-estabilidad.yaml not found`.** El perfil no
llegó al contenedor, o `BITAXEPID_CONFIG` en tu `.env` sigue con el nombre viejo
sin el directorio. Comprueba el `.env` y reconstruye con
`docker compose up -d --build`. Este error es deliberado: antes se ignoraba en
silencio y el miner acababa corriendo con los límites de fábrica creyendo que
estaba limitado.

**`ASIC model YAML file chips/BM1370.yaml not found`.** Es distinto del anterior:
falta el YAML de fábrica, no tu perfil. En una imagen recién construida significa
que al `Containerfile` le faltan los `COPY chips/` y `COPY perfiles/` — los
comodines de `COPY *.yaml` no bajan a subdirectorios, así que sin esas dos líneas
la imagen sale sin ninguna configuración.

**`errorPercentage ausente en la respuesta del miner`.** Esta estrategia se queda
sin su señal principal: no sale de RAMPA y solo actuarán temperatura y potencia.
Lo dice en el log con esas palabras. Es cosa del firmware del miner; mira si
AxeOS está actualizado.

**El puerto 8093 está ocupado** (Umbrel corre bastantes cosas). Cambia
`BITAXEPID_METRICS_PORT` en `.env` y `docker compose up -d`.

**Temperaturas por encima de 60 °C y no bajan.** Mira si la frecuencia está ya
en `MIN_FREQUENCY` (475) y el voltaje en `MIN_VOLTAGE` (1180): si el tuner llegó
al suelo y sigue caliente, el problema es de refrigeración, no de configuración.
Ningún ajuste de software lo arregla.

**Quieres parar todo ya.** `docker compose down`. Deja al miner con los últimos
valores aplicados, que estarán dentro de tus topes; no lo devuelve a los de
fábrica.

## Qué está verificado y qué no

Verificado contra un miner simulado que responde como la API real, con
`ASICModel=BM1370` para que se cargue el YAML correcto:

- **El log de arranque de arriba está copiado de una corrida real**, no escrito a
  mano, igual que las líneas de los tres estados y las dos transiciones.
- La máquina de estados recorre RAMPA → BUSCAR_VOLTAJE → OPTIMIZAR y las
  transiciones salen con su motivo. La rampa la para la temperatura a 58,1 °C,
  muy por debajo del techo de 925 MHz.
- El volcado de `:8093/metrics` de arriba es la respuesta real: `pid_settings`
  con los límites del perfil, y `estado`, `error_percent` y `error_target` en
  cada muestra.
- Los topes en los dos caminos que escriben al hardware: el valor inicial (con su
  aviso al recortar) y cada propuesta del bucle. En ninguna corrida se aplica un
  valor fuera de 1180-1210 mV / 475-925 MHz.
- 134 tests unitarios y el smoke test del proyecto: 67 ok, 0 fallos, 0 saltados.

**Verificado**

- **Tu miner.** Verificado
- **`errorPercentage`.** Verificado
- **`docker compose up`.** Verificado
- **La primera media hora.** Déjalo con `docker compose logs -f` delante y mira
  las temperaturas así te quedas tranquilo/a
