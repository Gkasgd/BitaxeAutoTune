# `chips/` — límites de fábrica, no los edites

Un fichero por modelo de ASIC. **El programa elige uno solo, y no se le puede
decir cuál**: al arrancar lee el `ASICModel` que reporta el miner por la API y
carga `chips/<modelo>.yaml` (`config.ruta_yaml_de_chip`). Si no existe, termina.

| Fichero | Voltaje | Frecuencia | Arranque |
|---|---|---|---|
| `BM1366.yaml` | 1100-1300 mV | 400-575 MHz | 1200 mV / 485 MHz |
| `BM1368.yaml` | 1100-1300 mV | 400-575 MHz | 1166 mV / 490 MHz |
| `BM1370.yaml` | 1000-1250 mV | 400-625 MHz | 1150 mV / 550 MHz |
| `BM1397.yaml` | 1100-1500 mV | 400-650 MHz | 1200 mV / 425 MHz |

(Los cuatro vienen de upstream sin tocar. El BM1370 es el del Bitaxe Gamma, que
es el único chip con el que se ha probado este fork.)

## Por qué no editarlos

Estos rangos son los del desplegable de AxeOS para cada chip: el espacio que el
firmware considera admisible, no un ajuste recomendado. Son el techo de todo lo
demás, y sirven de red de seguridad cuando un perfil de `perfiles/` no declara
una clave.

Subir un máximo aquí lo sube **para cualquier perfil que no lo declare**,
incluidos los que se llaman conservadores. Es el único cambio del repositorio que
puede acabar escribiendo al hardware un valor más alto sin que ningún fichero
llamado "seguro" lo mencione.

Si quieres otros límites, escribe un perfil en `perfiles/` y pásalo con
`--config`. Lo que declares ahí manda, porque se aplica encima.

## Comprobar qué rige de verdad

```bash
python bitaxepid.py --dry-run --asic BM1370 --config perfiles/gamma-estabilidad.yaml
```

Imprime cada clave con el fichero del que sale, sin conectar con ningún miner.
Las líneas que digan `<- chips/...` son las que tu perfil hereda de aquí.

Los dos perfiles de `perfiles/` no heredan ninguna: declaran todo lo que el
programa lee.
