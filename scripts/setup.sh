#!/bin/bash
# Crea el entorno virtual e instala las dependencias.
#
# Requiere uv: https://docs.astral.sh/uv/getting-started/installation/
#
# Uso:  bash scripts/setup.sh
#
# El entorno se crea en la raiz del proyecto, no en el directorio desde el que
# se invoque el script.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Crear el entorno virtual
uv venv

# Activar el entorno virtual.
#
# La ruta del activate depende del sistema: en Linux y macOS es
# .venv/bin/activate, y en Windows (Git Bash, MSYS) uv crea
# .venv/Scripts/activate. Estaba fijo en bin/ y por eso el guion fallaba en
# Windows aunque uv hubiera creado el entorno bien.
ACTIVATE=""
for candidato in .venv/bin/activate .venv/Scripts/activate; do
  if [ -f "$candidato" ]; then
    ACTIVATE="$candidato"
    break
  fi
done

if [ -z "$ACTIVATE" ]; then
  echo "uv venv no dejo ningun activate donde se esperaba." >&2
  echo "Rutas buscadas: .venv/bin/activate, .venv/Scripts/activate" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$ACTIVATE"

# Instalar las dependencias
# Las dependencias se declaran en requirements.txt (no duplicar la lista aqui)
uv pip install --requirement requirements.txt

# Desactivar el entorno virtual
deactivate
