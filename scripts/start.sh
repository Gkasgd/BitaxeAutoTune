#!/bin/bash
# Arranca el auto-tuner contra un miner, usando el entorno virtual del proyecto.
#
# Uso:  bash scripts/start.sh <ip_del_miner> [opciones adicionales]
#
# Ejemplos:
#   bash scripts/start.sh 192.168.68.111
#   bash scripts/start.sh 192.168.68.111 --serve-metrics
#   bash scripts/start.sh 192.168.68.111 --manage-pools
#
# Por defecto BitaxePID no toca la configuracion de pools del miner; hace falta
# --manage-pools para autorizarlo.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ "$#" -lt 1 ]; then
  echo "uso: bash scripts/start.sh <ip_del_miner> [opciones adicionales]" >&2
  exit 2
fi

# La ruta del activate depende del sistema: bin/ en Linux y macOS, Scripts/ en
# Windows (Git Bash, MSYS). Estaba fijo en bin/ y en Windows este guion abortaba
# diciendo que no habia entorno virtual justo despues de crearlo con exito.
ACTIVATE=""
for candidato in .venv/bin/activate .venv/Scripts/activate; do
  if [ -f "$candidato" ]; then
    ACTIVATE="$candidato"
    break
  fi
done

if [ -z "$ACTIVATE" ]; then
  echo "no existe .venv: ejecuta primero 'bash scripts/setup.sh'" >&2
  echo "Rutas buscadas: .venv/bin/activate, .venv/Scripts/activate" >&2
  exit 2
fi

IP="$1"
shift

# shellcheck source=/dev/null
source "$ACTIVATE"
python ./bitaxepid.py --ip "$IP" --logging-level debug "$@"
