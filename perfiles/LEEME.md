# `perfiles/` — lo que tú tocas

Los dos ficheros de aquí se pasan con `--config` y sus claves se aplican **encima**
del YAML de `chips/` que el miner determine. Los dos son para el Bitaxe Gamma
(BM1370).

Ninguno de los dos hereda nada: cada uno declara todas las claves que el programa
lee, así que basta leer un fichero para saber con qué corre.

## Los dos perfiles

| | `gamma-estabilidad.yaml` | `gamma-conservador.yaml` |
|---|---|---|
| **Estrategia** | estabilidad (`ERROR_TUNING: TRUE`) | por límites (`ERROR_TUNING` ausente) |
| **Criterio** | busca el voltaje mínimo que mantiene los errores bajo el objetivo | no busca: reacciona cuando se pasa de un límite |
| Temperatura objetivo | 60 °C | 55 °C |
| Errores aceptados | 2,0 % | — (no hay objetivo) |
| Voltaje | 1180-1210 mV | 1100-1150 mV |
| Frecuencia | 475-925 MHz | 425-500 MHz |
| Arranque | 1185 mV / 475 MHz (el suelo, y sube) | 1100 mV / 450 MHz |
| Paso | 5 mV / 5 MHz | 10 mV / 25 MHz |
| Muestreo | 30 s | 60 s |
| Límite de potencia | 30 W (actúa sobre 32 W) | 13 W (actúa sobre 14 W) |
| Claves declaradas | 32 | 24 |
| Probado en hardware | sí | no |

**Si no tienes un motivo concreto, usa `gamma-estabilidad.yaml`.** Es el que el
despliegue trae por defecto y el único que se ha usado en un miner real. El
conservador está más abajo en todo, pero corre la otra estrategia, que es un
comportamiento distinto y no solo unos números más prudentes.

La diferencia de estrategia es la que importa, no el rango: la de estabilidad
sube frecuencia hasta que la temperatura la para, luego baja voltaje hasta
encontrar el mínimo que aguanta el 2 % de errores, y se queda ahí. La de límites
no busca nada: se mueve cuando cruza un límite. Con el conservador **no verás
ninguna línea `RAMPA:` ni `BUSCAR_VOLTAJE:`**, porque esos estados no existen en
esa estrategia.

## Cambiar de perfil

En el despliegue con `docker compose`, editando `BITAXEPID_CONFIG` en `.env`:

```bash
BITAXEPID_CONFIG=perfiles/gamma-conservador.yaml
```

Incluye el directorio: es la ruta que ve el programa, relativa a su directorio de
trabajo. Si apunta a un fichero que no existe, el arranque termina en lugar de
seguir con los límites de fábrica del chip.

Ejecutándolo directamente:

```bash
python bitaxepid.py --ip <ip-del-miner> --config perfiles/gamma-estabilidad.yaml
```

## Escribir tu propio perfil

Copia uno de los dos y edita lo que quieras. Dos cosas que muerden:

**Declara los cuatro extremos, no solo los máximos.** Lo que no esté en tu
fichero sale del YAML de `chips/`, y eso incluye `MIN_VOLTAGE` y `MIN_FREQUENCY`.
Un perfil que baja el techo a 1150 mV y se deja el suelo heredado acaba con un
rango efectivo de 1000-1150 mV, que no es el que su nombre promete. El suelo no es
decorativo: es hasta dónde baja la búsqueda del voltaje mínimo, y hasta dónde baja
la rama térmica cuando ya no queda frecuencia.

**`ERROR_TUNING: TRUE` es lo que elige la estrategia.** Sin esa línea corre la
otra, y todo lo demás que declares para la de estabilidad (ventana, histéresis,
techo de reintentos) se ignora en silencio. El arranque lo avisa por log, pero es
un WARNING fácil de pasar por alto.

Compruébalo antes de dejarlo corriendo, sin conectar con ningún miner:

```bash
python bitaxepid.py --dry-run --asic BM1370 --config perfiles/mi-perfil.yaml
```

Imprime cada clave con el fichero del que sale y termina con código 0 si la
configuración es válida, 1 si no. Las líneas que digan `<- chips/...` son las que
tu perfil hereda.

Para ver qué significa cada clave, los comentarios de `gamma-estabilidad.yaml`
las explican una por una.
