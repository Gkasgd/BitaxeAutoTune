#!/usr/bin/env bash
#
# Genera archivos-para-umbrel/ desde el arbol de trabajo.
#
# El paquete se mantenia a mano y se quedo atras: en la revision de julio de 2026
# le faltaban config.py, stratum.py y api_client.py, que era justo donde vivian
# tres de los ocho arreglos. Es decir, el nodo habria recibido una correccion a
# medias sin que nada lo avisara. Este script existe para que eso no pueda volver
# a pasar: la lista de archivos esta declarada UNA vez, aqui abajo, y el paquete
# se regenera entero cada vez.
#
# Uso:
#     scripts/generar-paquete-umbrel.sh [directorio-destino]
#
# Por defecto escribe en ../archivos-para-umbrel relativo a la raiz del repo.
#
# Lo que NO hace, a proposito:
#   - No toca LEEME.md. Es prosa escrita a mano (incluye la tabla de "tu tienes /
#     este trae" con los valores del nodo concreto) y regenerarla desde una
#     plantilla la degradaria. El script solo AVISA si parece desactualizada.
#   - No comitea ni sube nada. Empaquetar y publicar son decisiones distintas.

set -euo pipefail

# --- Los archivos del paquete ---------------------------------------------
#
# Esta lista ES la definicion del paquete. Al anadir un modulo al proyecto que
# el nodo necesite, se anade aqui y en la tabla de LEEME.md, y con eso basta.
#
# Criterio: va al paquete todo modulo que el tuner importe en tiempo de
# ejecucion y que haya cambiado respecto al upstream. Los que no cambian
# (ui_rich.py, ui_null.py, metrics_server.py) no se envian: el nodo ya los tiene
# y mandarlos solo agranda la transferencia y la lista de hashes que hay que
# comprobar a mano.
#
# Ojo con las dependencias entre versiones: tuning.py no es la estrategia que
# corre el nodo (usa ERROR_TUNING: TRUE), pero bitaxepid.py lo importa SIEMPRE y
# le pasa parametros que la version vieja no acepta. Copiar uno sin el otro
# revienta el arranque con un TypeError. El criterio real es "todo lo que el
# proceso importa y ha cambiado", no "todo lo que se ejecuta".
ARCHIVOS_RAIZ=(
    api_client.py
    bitaxepid.py
    cli.py
    config.py
    logger.py
    stratum.py
    tuning.py
    tuning_estabilidad.py
    tuning_manager.py
    safe-BM1370-estabilidad.yaml
)

# Rutas con subdirectorio, que hay que crear en el destino.
ARCHIVOS_ANIDADOS=(
    tests/test_estabilidad.py
)

# --- Localizar el repo ----------------------------------------------------

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
raiz=$(cd "$script_dir/.." && pwd)
destino=${1:-$(cd "$raiz/.." && pwd)/archivos-para-umbrel}

cd "$raiz"

echo "Origen : $raiz"
echo "Destino: $destino"
echo

# --- Comprobaciones previas ------------------------------------------------

# Que exista todo lo declarado. Sin esto, un `cp` fallido a mitad dejaria el
# paquete con una mezcla de versiones nueva y vieja, que es peor que no tenerlo:
# el SHA256SUMS.txt saldria consistente y el paquete estaria mal.
faltan=()
for f in "${ARCHIVOS_RAIZ[@]}" "${ARCHIVOS_ANIDADOS[@]}"; do
    [[ -f "$f" ]] || faltan+=("$f")
done
if (( ${#faltan[@]} > 0 )); then
    echo "ERROR: no estan en el repo: ${faltan[*]}" >&2
    echo "Corrige la lista de este script o recupera los archivos." >&2
    exit 1
fi

# Los tests tienen que pasar antes de empaquetar. Un paquete que se instala en
# hardware que controla voltaje de core no se genera "a ver si va".
if [[ "${SALTAR_TESTS:-}" == "1" ]]; then
    echo "AVISO: tests saltados por SALTAR_TESTS=1"
else
    echo "Ejecutando la suite antes de empaquetar..."
    if ! python -m unittest discover -s tests -t . -q >/tmp/paquete-tests.log 2>&1; then
        echo "ERROR: la suite NO pasa. No se genera el paquete." >&2
        tail -20 /tmp/paquete-tests.log >&2
        echo >&2
        echo "Si estas seguro y solo quieres el paquete, repite con SALTAR_TESTS=1." >&2
        exit 1
    fi
    echo "Suite OK."
fi

# Empaquetar con cambios sin comitear es legitimo (asi se probo en el nodo antes
# de comitear), pero conviene saberlo: el paquete no sera reproducible desde
# ningun commit.
if git rev-parse --git-dir >/dev/null 2>&1; then
    commit=$(git rev-parse --short HEAD 2>/dev/null || echo "sin-commits")
    sucio=$(git status --porcelain -- "${ARCHIVOS_RAIZ[@]}" "${ARCHIVOS_ANIDADOS[@]}" 2>/dev/null || true)
    if [[ -n "$sucio" ]]; then
        echo
        echo "AVISO: hay cambios sin comitear en archivos del paquete."
        echo "       El paquete NO sera reproducible desde $commit."
        echo "$sucio" | sed 's/^/         /'
    fi
else
    commit="sin-git"
fi

# --- Copiar ---------------------------------------------------------------

echo
mkdir -p "$destino"

for f in "${ARCHIVOS_RAIZ[@]}"; do
    cp -- "$f" "$destino/$f"
    echo "  copiado $f"
done

for f in "${ARCHIVOS_ANIDADOS[@]}"; do
    mkdir -p "$destino/$(dirname "$f")"
    cp -- "$f" "$destino/$f"
    echo "  copiado $f"
done

# Retirar del destino lo que ya no esta declarado. Sin esto, quitar un archivo
# de la lista lo dejaria en el paquete para siempre, y el nodo seguiria
# recibiendo una version congelada de algo que el repo ya no envia.
declarados=" ${ARCHIVOS_RAIZ[*]} ${ARCHIVOS_ANIDADOS[*]} "
while IFS= read -r presente; do
    rel=${presente#"$destino/"}
    [[ "$rel" == "LEEME.md" || "$rel" == "SHA256SUMS.txt" ]] && continue
    if [[ "$declarados" != *" $rel "* ]]; then
        echo "  RETIRADO $rel (ya no esta declarado en el script)"
        rm -- "$presente"
    fi
done < <(find "$destino" -type f \( -name '*.py' -o -name '*.yaml' \) | sort)

# --- Manifiesto -----------------------------------------------------------
#
# El LEEME manda comprobarlo con `sha256sum -c` en el nodo, asi que las rutas
# tienen que ser relativas al destino y en el mismo orden siempre: un manifiesto
# que cambia de orden sin que cambie el contenido hace ruido en los diffs.
(
    cd "$destino"
    sha256sum -- "${ARCHIVOS_RAIZ[@]}" "${ARCHIVOS_ANIDADOS[@]}" > SHA256SUMS.txt
)

echo
echo "SHA256SUMS.txt regenerado. Verificando..."
( cd "$destino" && sha256sum -c SHA256SUMS.txt )

# --- Avisar si el LEEME se quedo atras ------------------------------------
#
# No se regenera (es prosa a mano), pero si la tabla no menciona un archivo del
# paquete, quien lo instale no sabra que le llego. Es justo el fallo que dejo
# fuera config.py, stratum.py y api_client.py.
leeme="$destino/LEEME.md"
if [[ -f "$leeme" ]]; then
    sin_documentar=()
    for f in "${ARCHIVOS_RAIZ[@]}" "${ARCHIVOS_ANIDADOS[@]}"; do
        grep -qF -- "$f" "$leeme" || sin_documentar+=("$f")
    done
    if (( ${#sin_documentar[@]} > 0 )); then
        echo
        echo "AVISO: LEEME.md no menciona: ${sin_documentar[*]}"
        echo "       Anadelos a la tabla de archivos y al recuento del titulo."
    fi

    total=$(( ${#ARCHIVOS_RAIZ[@]} + ${#ARCHIVOS_ANIDADOS[@]} ))
    if ! grep -qiE "^# .*(archivos para copiar)" "$leeme"; then
        : # titulo con otra forma, no se comprueba el recuento
    else
        echo
        echo "Recuerda: el paquete tiene $total archivos. Comprueba que el titulo"
        echo "y el paso de verificacion de LEEME.md digan ese numero."
    fi
else
    echo
    echo "AVISO: no hay LEEME.md en el destino. El paquete se instala a mano y"
    echo "       sin instrucciones nadie sabra en que directorio copiarlo."
fi

echo
echo "Paquete generado desde $commit: $destino"
