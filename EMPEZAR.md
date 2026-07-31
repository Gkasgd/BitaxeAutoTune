# Empezar desde cero

Ya has descargado los archivos. Esto es lo mínimo para dejar el tuner
funcionando, sin pasos de adorno.

Antes de nada: este programa **escribe voltaje de core y frecuencia reales** en
tu ASIC. No hay modo de simulación. El paso 3 valida la configuración sin tocar
el miner y no es opcional.

## 0. Comprueba que tu miner encaja

```bash
curl http://<ip-de-tu-miner>/api/system/info
```

Busca el campo `ASICModel`. Tiene que ser uno de estos cuatro:
`BM1366`, `BM1368`, `BM1370`, `BM1397`. Con cualquier otro el programa termina
en el arranque, porque no existe el YAML de límites de fábrica correspondiente.

**Si no es `BM1370`, sigue leyendo pero no uses los perfiles que vienen.** Los
dos de `perfiles/` son para el Gamma (BM1370) y sus voltajes matarían o
subalimentarían a otro chip. Ve al paso 6.

Ponle al miner una **IP fija** (reserva DHCP en el router). El programa no lo
descubre por mDNS; si la IP cambia, se queda hablando solo.

## 1. Qué archivos necesitas de verdad

Si descargaste el repo entero, ya los tienes todos y puedes saltar al paso 2.
Esta lista está aquí por si copiaste a mano y quieres saber qué es
imprescindible. Está comprobada arrancando con solo esto y nada más:

| Ruta | Por qué |
|---|---|
| Los 12 `.py` de la raíz | El proceso los importa todos, incluso `tuning.py`, que es la estrategia que probablemente no uses |
| `chips/<tu-modelo>.yaml` | Límites de fábrica. Los otros tres puedes borrarlos |
| `perfiles/<un-perfil>.yaml` | Tus límites. Manda sobre el anterior |
| `requirements.txt` | Solo si instalas las dependencias a mano |
| `Containerfile`, `docker-compose.yml`, `.env.example` | Solo para la vía Docker |

Lo que **no** hace falta: `pools.yaml` y `user.yaml` (comprobado: se arranca sin
ellos, ver paso 5), `banner.txt` (sin él sale `Banner file not found` y sigue),
`tests/`, `scripts/`, los `.md`.

## 2. Instala las dependencias

Cuatro paquetes: `pyyaml`, `urllib3`, `rich`, `pyfiglet`. Todo lo demás es
biblioteca estándar. Necesitas **Python 3.9 o superior**.

```bash
python3 -m venv .venv
source .venv/bin/activate        # en Windows: .venv/Scripts/activate
pip install -r requirements.txt
```

(`scripts/setup.sh` hace lo mismo pero exige `uv` instalado. Si no lo tienes, no
lo instales solo para esto.)

Con Docker sáltate este paso: la imagen las instala.

## 3. Valida el perfil antes de tocar el miner

Esto no abre ninguna conexión, ni al miner ni a internet:

```bash
python3 bitaxepid.py --dry-run --asic BM1370 --config perfiles/gamma-estabilidad.yaml
```

Sale una tabla con el valor efectivo de cada clave y **de qué fichero viene**.
Termina en código 0 si la configuración es válida y 1 si no.

Lo único que tienes que mirar son los seis límites. Con este perfil las 32
claves las declara él y no se hereda nada:

```
MIN_VOLTAGE      1180   <- perfiles/gamma-estabilidad.yaml
MAX_VOLTAGE      1210   <- perfiles/gamma-estabilidad.yaml
MIN_FREQUENCY     475   <- perfiles/gamma-estabilidad.yaml
MAX_FREQUENCY     925   <- perfiles/gamma-estabilidad.yaml
```

Si en la columna de la derecha ves `<- chips/BM1370.yaml` en un límite, ese valor
lo pone la fábrica y no tu perfil. Con los que vienen no pasa; con uno propio,
es exactamente el fallo que hay que cazar aquí: bajar `MAX_VOLTAGE` y dejarse
`MIN_VOLTAGE` heredado da un rango efectivo que el nombre del fichero no dice.

Hay que pasarle `--asic` porque el modelo lo reporta el miner, y aquí no se le
pregunta a ninguno. Usa el que viste en el paso 0.

## 4. Arranca

**Con Docker** (recomendado si vas a dejarlo permanente; es lo documentado):

```bash
cp .env.example .env
nano .env                        # pon tu IP en BITAXEPID_MINER_IP
docker compose up -d --build
docker compose logs -f
```

`BITAXEPID_CONFIG` ya viene apuntando a `perfiles/gamma-estabilidad.yaml`. Si lo
cambias, **incluye el subdirectorio**: la ruta es la que ve el programa dentro
del contenedor, y un `--config` que no existe aborta el arranque.

**Directo, sin Docker** (para probar un rato y ver la interfaz):

```bash
python3 bitaxepid.py --ip <ip-de-tu-miner> --config perfiles/gamma-estabilidad.yaml
```

Añade `--log-to-console` si prefieres el log plano a la interfaz de `rich`.
`Ctrl+C` para y deja al miner con los últimos valores aplicados.

## 5. Comprueba que arrancó bien

En el log tienen que salir estas cuatro líneas, en este orden:

```
INFO - 32 claves, todas declaradas en perfiles/gamma-estabilidad.yaml: no se hereda nada de chips/BM1370.yaml
INFO - Estrategia de estabilidad: objetivo 2.0% de errores de hardware, temperatura objetivo 60.0C. El hashrate no interviene en las decisiones.
INFO - Gestion de pools desactivada: se respeta la configuracion stratum del miner.
INFO - Applied settings: Voltage=1185mV, Frequency=475MHz
```

Cada una dice algo que conviene entender:

- **La primera** es la trazabilidad del paso 3, ya con el miner delante.
- **La segunda** confirma la estrategia. Si dice `Estrategia por limites`, tu
  `--config` no llegó y estás con la otra.
- **La tercera** es la razón de que no necesites `pools.yaml` ni `user.yaml`: por
  defecto el programa **no toca la configuración de pools de tu miner**. Sigue
  minando donde ya minaba. Solo con `--manage-pools` entran en juego esos dos
  ficheros, y `user.yaml` viene **vacío a propósito**, así que en ese caso el
  arranque termina en `Stratum users missing` hasta que pongas tu dirección.
- **La cuarta** es la primera escritura al hardware: el suelo del perfil,
  1185 mV / 475 MHz. Si ves `1150mV, 550MHz` estás con los valores de fábrica.

Y desde el navegador, pasado un `SAMPLE_INTERVAL` (30 s con este perfil):

```
http://<ip-del-host>:8093/metrics
```

Los primeros segundos devuelve `{"endpoints": []}`: la lista se rellena con la
primera muestra, no al arrancar. Dentro de `pid_settings` tienen que estar tus
límites. (Es JSON, no formato Prometheus.)

## 6. Si tu miner no es un Gamma

Copia un perfil y ajústalo a tu chip:

```bash
cp perfiles/gamma-estabilidad.yaml perfiles/mi-perfil.yaml
```

Edita **los seis límites** para tu modelo: `MIN_VOLTAGE`, `MAX_VOLTAGE`,
`MIN_FREQUENCY`, `MAX_FREQUENCY`, `INITIAL_VOLTAGE`, `INITIAL_FREQUENCY`. Saca
los valores de `chips/<tu-modelo>.yaml`, que son los de fábrica, y empieza por
**dentro** de ese rango, no en los extremos.

Después vuelve al paso 3 con tu fichero y tu `--asic`. Los tests exigen que todo
perfil de `perfiles/` declare los seis límites, precisamente para que no herede
la mitad sin darse cuenta.

Lo que **no** debes editar es `chips/*.yaml`: subir un máximo ahí lo sube para
cualquier perfil que no lo declare.

## Qué va a pasar durante la primera hora

El perfil por defecto usa la estrategia de estabilidad: busca el punto más alto
que aguante tu chip con menos del 2 % de errores de hardware por debajo de
60 °C. El hashrate no interviene en ninguna decisión; es el resultado.

Arranca en el suelo (475 MHz) y sube de 5 en 5 MHz una vez por muestra, o sea
cada 30 s. Llegar a 900 MHz son unos **43 minutos** de rampa. Es normal y no es
un cuelgue; las líneas `RAMPA:` van saliendo. Luego busca el voltaje mínimo y
entra en régimen permanente, donde repite `Estable en ...` cada muestra.

**Quédate delante durante esa primera media hora** y mira las temperaturas de
verdad, no las del log. Si sube de 60 °C, lo que baja es la frecuencia, no el
voltaje. Si llega al suelo de los dos y sigue caliente, el problema es de
refrigeración y ningún ajuste lo arregla.

## Si algo falla

**`Failed to fetch system info from API`** y el proceso termina. Es la IP. No
falla rápido: el cliente hace 5 reintentos con backoff, así que verás medio
minuto de `Retrying` antes de rendirse. Con Docker, `restart: unless-stopped` lo
vuelve a levantar y parece un bucle. Comprueba el `curl` del paso 0 **desde el
mismo host** donde corre el tuner.

**`User config file perfiles/… not found`.** La ruta del `--config`. Con Docker,
además, comprueba que reconstruiste la imagen: `docker compose up -d --build`.

**`ASIC model YAML file chips/BM1370.yaml not found`.** Falta el YAML de fábrica,
no tu perfil. Si es una imagen que construiste tú modificando el
`Containerfile`, le faltan los `COPY chips/` y `COPY perfiles/`: los comodines de
`COPY *.yaml` no bajan a subdirectorios.

**`errorPercentage ausente en la respuesta del miner`.** Tu firmware no publica
ese campo, que es la señal principal de esta estrategia: no saldrá de RAMPA y
solo actuarán temperatura y potencia. Mira si AxeOS está actualizado.

**El puerto 8093 está ocupado.** Con Docker, cambia `BITAXEPID_METRICS_PORT` en
`.env`: eso mueve el puerto del host, no el de dentro del contenedor, y basta.
Ejecutando directo no hay forma de cambiarlo sin editar `METRICS_PORT` en
`metrics_server.py`, donde está fijo; la alternativa es poner `METRICS_SERVE:
FALSE` en tu perfil y quedarte sin métricas.

**Quieres parar ya.** `docker compose down`, o `Ctrl+C`. Deja al miner con los
últimos valores aplicados, dentro de tus topes; no lo devuelve a los de fábrica.

## Un aviso honesto

Los perfiles que vienen están probados en un miner **simulado**. El de
estabilidad, además, en un Bitaxe Gamma real. Nada más lo está: ni el
conservador, ni ningún otro chip, ni la imagen de Docker construida en tu
máquina. Los números concretos de los ejemplos son de un simulador cuyo modelo
térmico es una fórmula.

Detalle completo de qué está verificado y qué no, en `UMBREL.md`. El por qué de
cada clave, en el propio perfil y en `perfiles/LEEME.md`.
