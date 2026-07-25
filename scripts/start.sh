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

if [ ! -f .venv/bin/activate ]; then
  echo "no existe .venv: ejecuta primero 'bash scripts/setup.sh'" >&2
  exit 2
fi

IP="$1"
shift

source .venv/bin/activate
python ./bitaxepid.py --ip "$IP" --logging-level debug "$@"
