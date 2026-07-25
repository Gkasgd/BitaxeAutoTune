# BitaxePID en Umbrel, con límites seguros

Objetivo: dejar el tuner corriendo en el Umbrel apuntando a tu Bitaxe Gamma
(BM1370), sin pasar nunca de **55 °C de objetivo, 500 MHz y 1150 mV**.

Antes de nada, lo importante: **nada de esto se ha probado en tu miner ni en tu
Umbrel.** Lo he verificado contra un miner simulado y sin poder construir la
imagen del contenedor (el entorno donde lo preparé no tiene Docker ni red). Al
final hay una lista de qué está comprobado y qué no.

## Antes de empezar

Dale al miner una **IP fija** (reserva DHCP en el router). El contenedor no
puede descubrirlo por mDNS, así que si la IP cambia, el tuner se queda hablando
solo.

Apunta también la IP del Umbrel y comprueba que tienes SSH. Por defecto el
usuario es `umbrel`.

## Puesta en marcha

Desde tu máquina, con el fork ya empujado a GitHub:

```bash
ssh umbrel@<ip-del-umbrel>

git clone https://github.com/<tu-usuario>/BitaxePID.git
cd BitaxePID

cp .env.example .env
nano .env          # pon la IP de tu miner en BITAXEPID_MINER_IP

docker compose up -d --build
docker compose logs -f
```

En el log tienen que aparecer, en este orden:

```
INFO - Initialized BitaxeAPIClient for <ip> with timeout=10s, retries=5, pool_maxsize=10
INFO - Gestion de pools desactivada: se respeta la configuracion stratum del miner.
INFO - Initializing hardware: Voltage=1100mV, Frequency=450MHz
INFO - Applied settings: Voltage=1100mV, Frequency=450MHz
INFO - Metrics server started on http://0.0.0.0:8093/metrics
INFO - Starting BitaxePID tuner...
INFO - Starting BitaxePID tuner...
```

Arranca en 1100 mV / 450 MHz, por debajo de los topes, y sube desde ahí. Si ves
`Voltage=1150mV, Frequency=550MHz` es que **no** se cargó el perfil seguro: son
los valores de fábrica del BM1370.

("Starting BitaxePID tuner" sale dos veces: está en `main()` y otra vez dentro
de `start_tuning()`. Es cosmético, viene del código original y no lo he tocado.)

`Ctrl+C` sale del log sin parar el contenedor. Para pararlo de verdad:
`docker compose down`.

## Comprobar que los límites están puestos

La forma rápida, desde cualquier navegador de tu red:

```
http://<ip-del-umbrel>:8093/metrics
```

Los primeros segundos devuelve `{"endpoints": []}`: la lista se rellena con la
primera muestra del bucle, no al arrancar. Espera un `SAMPLE_INTERVAL` y vuelve
a mirar. Dentro de `pid_settings` tienen que estar tus tres números:

```json
"MAX_VOLTAGE": 1150, "MAX_FREQUENCY": 500, "TARGET_TEMP": 55.0
```

Si ahí ves `1250` y `625`, el perfil no se aplicó. Ojo: sirve JSON, no el
formato de Prometheus, así que Prometheus no lo puede raspar directamente
(el README original decía lo contrario; está corregido).

El historial de tuning queda en `~/BitaxePID/data/`, que sobrevive a
`docker compose down`.

## Qué va a hacer el tuner

Sube voltaje y frecuencia mientras haya margen, y en cuanto la temperatura pasa
de 55 °C baja **primero frecuencia y luego voltaje**, un paso por muestra (25 MHz
y 10 mV). Muestrea cada 60 segundos, así que reacciona en minutos, no en
segundos.

Cada decisión sale en el log, pero sin marca de tiempo: esas líneas van por
stdout y no por el logger. Son las que empiezan por `Reducing frequency to...`,
`Increasing voltage to...` o `System stable at...`. Ver `System stable` repetido
es la señal de que ha encontrado su punto.

Los topes son duros en los dos caminos que escriben al hardware: el valor
inicial y cada propuesta del bucle. Si pides algo fuera de rango, lo recorta y lo
dice:

```
WARNING - INITIAL_VOLTAGE=1250.0mV esta fuera del rango 1000-1150mV
          (MIN_VOLTAGE/MAX_VOLTAGE): se usara 1150mV
```

**No toca la configuración de pools de tu miner** y no lo reinicia al arrancar.
Si algún día quieres lo contrario, añade `--manage-pools` al `command` del
compose; es mejor eso que dejarlo activado en un fichero.

## Ajustar el perfil

Todo está en `safe-BM1370.yaml`, con un comentario por clave explicando el por
qué. Los que probablemente querrás tocar:

| Clave | Valor | Para qué |
|---|---|---|
| `TARGET_TEMP` | 55.0 | Temperatura objetivo |
| `MAX_FREQUENCY` | 500 | Tope de frecuencia |
| `MAX_VOLTAGE` | 1150 | Tope de voltaje |
| `HASHRATE_SETPOINT` | 400 | Objetivo del PID, en GH/s |
| `SAMPLE_INTERVAL` | 60 | Segundos entre muestras |
| `POWER_LIMIT` | 13.0 | Actúa alrededor de 14 W (se compara contra `POWER_LIMIT * 1.075`) |

Un aviso sobre `HASHRATE_SETPOINT`: si lo pones por encima de lo que se puede
alcanzar dentro de los topes, el PID pide más para siempre y se queda pegado al
techo de voltaje sin ganar hashrate. Con 500 MHz de tope, 400 es razonable.

Después de editar: `docker compose restart`.

## Si algo va mal

**El contenedor se reinicia en bucle.** `docker compose logs --tail 50`. Lo más
probable es la IP: si el miner no responde, el programa registra
`Failed to fetch system info from API` y termina, y `restart: unless-stopped` lo
vuelve a levantar. No falla rápido — el cliente HTTP hace 5 reintentos con
backoff, así que verás medio minuto de `Retrying (Retry(total=...))` con
`Connection refused` antes de que se rinda. Comprueba con
`curl http://<ip-del-miner>/api/system/info` desde el propio Umbrel.

**`User config file safe-BM1370.yaml not found`.** El perfil no llegó al
contenedor. Reconstruye con `docker compose up -d --build`. Este error es
deliberado: antes se ignoraba en silencio y el miner acababa corriendo con los
límites de fábrica creyendo que estaba limitado.

**El puerto 8093 está ocupado** (Umbrel corre bastantes cosas). Cambia
`BITAXEPID_METRICS_PORT` en `.env` y `docker compose up -d`.

**Temperaturas por encima de 55 °C y no bajan.** Mira si la frecuencia está ya
en `MIN_FREQUENCY` (400) y el voltaje en `MIN_VOLTAGE` (1000): si el tuner llegó
al suelo y sigue caliente, el problema es de refrigeración, no de configuración.
Ningún ajuste de software lo arregla.

**Quieres parar todo ya.** `docker compose down`. Deja al miner con los últimos
valores aplicados, que estarán dentro de tus topes; no lo devuelve a los de
fábrica.

## Qué está verificado y qué no

Verificado contra un miner simulado que responde como la API real, con
`ASICModel=BM1370` para que se cargue el YAML correcto:

- Seis escenarios (normal, caliente, arranque en el tope, arranque fuera de
  rango, con métricas, y con un setpoint inalcanzable). En ninguno se aplica un
  valor por encima de 1150 mV o 500 MHz; el máximo aplicado es exactamente
  1150 mV / 500 MHz.
- El caso peligroso: pidiendo `--voltage 1250 --frequency 625`, al miner llegan
  1150 mV / 500 MHz, con el aviso en el log.
- La medida diferencial que demuestra que los arreglos hacen falta: el código de
  antes manda **1155 mV** al miner con el tope en 1150; el de ahora manda 1150.
- A 70 °C simulados el tuner baja frecuencia de 450 a 400 y voltaje de 1100 a
  1060, sin pasarse del mínimo.
- El comando exacto que genera el compose, ejecutado tal cual: crea `data/`,
  escribe el CSV ahí y nada en la raíz, y sirve métricas en 8093 (comprobado con
  una petición HTTP real).
- 71 tests unitarios y el smoke test del proyecto: 61 ok, 0 fallos.

**No verificado, y conviene que lo tengas presente:**

- **Tu miner.** Nada se ha medido en un chip real. Que 500 MHz a 1150 mV se
  mantenga por debajo de 55 °C depende de tu refrigeración, y el perfil no puede
  saberlo. Si no llega, el tuner bajará frecuencia hasta que llegue.
- **`docker compose up`.** La imagen no se ha construido nunca: no había Docker
  ni red. Lo comprobado es el comando y el comportamiento del programa.
- **Umbrel.** No he ejecutado nada en un Umbrel. El compose es estándar y no
  necesita privilegios, pero no es una app del store de Umbrel: es un
  `docker compose` que lanzas por SSH.
- **Las dependencias reales.** `rich`, `simple_pid` y `pyfiglet` eran stubs. El
  comportamiento del PID que he medido es el del stub, no el de `simple-pid`. La
  forma de las curvas puede diferir; los topes no, porque el recorte es
  independiente del controlador.
- **La primera media hora.** Déjalo con `docker compose logs -f` delante y mira
  las temperaturas de verdad antes de irte.
