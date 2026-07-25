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

# Activar el entorno virtual
source .venv/bin/activate

# Instalar las dependencias
# Las dependencias se declaran en requirements.txt (no duplicar la lista aqui)
uv pip install --requirement requirements.txt

# Desactivar el entorno virtual
deactivate
