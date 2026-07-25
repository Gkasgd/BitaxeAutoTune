#!/usr/bin/env bash
# Smoke test de BitaxePID: comprobaciones rápidas que no necesitan un miner.
#
# Existe para que un refactor incremental tenga una red de seguridad mínima:
# tras cada cambio, este script debe seguir pasando. No sustituye a probar
# contra hardware real, pero detecta lo que más se rompe al mover código
# (errores de sintaxis, imports circulares o inexistentes, CLI roto, YAML
# de configuracion incompletos).
#
# Uso:
#   ./scripts/smoke_test.sh
#
# Salida: 0 si todo pasa. Las comprobaciones que requieren dependencias no
# instaladas se SALTAN de forma explícita en lugar de fallar en silencio.

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2
ROOT="$PWD"

pass=0
fail=0
skip=0

ok()      { echo "  PASS  $1"; pass=$((pass + 1)); }
bad()     { echo "  FAIL  $1"; fail=$((fail + 1)); }
skipped() { echo "  SKIP  $1"; skip=$((skip + 1)); }

PY="${PYTHON:-python3}"

echo "BitaxePID smoke test"
echo "  raiz:   $ROOT"
echo "  python: $($PY --version 2>&1)"
echo

# ---------------------------------------------------------------------------
# 1. Sintaxis: todos los modulos compilan
# ---------------------------------------------------------------------------
echo "sintaxis:"
for f in "$ROOT"/*.py; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  if err="$("$PY" -m py_compile "$f" 2>&1)"; then
    ok "compila $name"
  else
    bad "compila $name"
    echo "$err" | sed 's/^/          /'
  fi
done
find "$ROOT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null

# ---------------------------------------------------------------------------
# 2. Dependencias de terceros
# ---------------------------------------------------------------------------
echo
echo "dependencias:"
DEPS_OK=1
for mod in rich simple_pid pyfiglet urllib3 yaml; do
  if "$PY" -c "import $mod" 2>/dev/null; then
    ok "import $mod"
  else
    skipped "import $mod (no instalado: pip install -r requirements.txt)"
    DEPS_OK=0
  fi
done

# ---------------------------------------------------------------------------
# 3. Imports del proyecto y CLI. Solo si las dependencias estan disponibles:
#    sin ellas el fallo seria de entorno, no del codigo.
# ---------------------------------------------------------------------------
echo
echo "modulos del proyecto:"
if [ "$DEPS_OK" = "1" ]; then
  for f in "$ROOT"/*.py; do
    [ -e "$f" ] || continue
    mod="$(basename "$f" .py)"
    if err="$(cd "$ROOT" && "$PY" -c "import $mod" 2>&1)"; then
      ok "import $mod"
    else
      bad "import $mod"
      echo "$err" | tail -3 | sed 's/^/          /'
    fi
  done
else
  skipped "imports del proyecto (faltan dependencias)"
fi

echo
echo "interfaz de linea de comandos:"
ENTRY="bitaxepid.py"
[ -f "$ROOT/main.py" ] && ENTRY="main.py"
if [ "$DEPS_OK" = "1" ]; then
  if (cd "$ROOT" && "$PY" "$ENTRY" --help >/dev/null 2>&1); then
    ok "$ENTRY --help"
  else
    bad "$ENTRY --help"
  fi
  # --ip es obligatorio: invocar sin argumentos debe fallar, no arrancar.
  if (cd "$ROOT" && "$PY" "$ENTRY" >/dev/null 2>&1); then
    bad "$ENTRY sin --ip deberia fallar y no lo hace"
  else
    ok "$ENTRY sin --ip falla como se espera"
  fi
else
  skipped "CLI (faltan dependencias)"
fi

# ---------------------------------------------------------------------------
# 4. Configuracion: cada YAML de chip debe traer las claves que el programa
#    exige en tiempo de arranque. Un YAML incompleto revienta el proceso ya
#    con el miner conectado, asi que conviene detectarlo aqui.
#
#    La lista de claves obligatorias NO se duplica aqui: se extrae del propio
#    codigo (la lista `required_keys` de validate_config) parseando el AST, sin
#    importar el modulo. Asi el test no se desincroniza del programa ni depende
#    de que las dependencias esten instaladas.
# ---------------------------------------------------------------------------
echo
echo "ficheros de configuracion:"
if "$PY" -c "import yaml" 2>/dev/null; then
  cfg_report="$("$PY" - "$ROOT" <<'PYEOF'
import ast
import glob
import os
import sys

import yaml

root = sys.argv[1]


def required_keys_from_source(root):
    """Lee la lista `required_keys` del fuente sin importar el modulo."""
    for path in sorted(glob.glob(os.path.join(root, "*.py"))):
        try:
            with open(path) as fh:
                tree = ast.parse(fh.read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "required_keys" not in names:
                continue
            if not isinstance(node.value, ast.List):
                continue
            keys = [
                el.value
                for el in node.value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            ]
            if keys:
                return keys, os.path.basename(path)
    return None, None


required, source_file = required_keys_from_source(root)
if required is None:
    print("FAIL|no se pudo localizar la lista required_keys en el codigo")
    sys.exit(0)
print(f"PASS|claves obligatorias leidas de {source_file} ({len(required)})")

chip_files = sorted(
    p for p in glob.glob(os.path.join(root, "BM*.yaml"))
)
if not chip_files:
    print("FAIL|no se encontro ningun BM*.yaml")
for path in chip_files:
    name = os.path.basename(path)
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:
        print(f"FAIL|{name} no es YAML valido: {exc}")
        continue
    if not isinstance(data, dict):
        print(f"FAIL|{name} no contiene un mapa de claves")
        continue
    missing = [k for k in required if k not in data]
    if missing:
        print(f"FAIL|{name} le faltan claves: {', '.join(missing)}")
    else:
        print(f"PASS|{name} tiene las {len(required)} claves requeridas")

for name in ("pools.yaml", "user.yaml"):
    path = os.path.join(root, name)
    if not os.path.exists(path):
        print(f"FAIL|falta {name}")
        continue
    try:
        with open(path) as fh:
            yaml.safe_load(fh)
        print(f"PASS|{name} es YAML valido")
    except Exception as exc:
        print(f"FAIL|{name} no es YAML valido: {exc}")
PYEOF
)"
  while IFS='|' read -r status msg; do
    [ -z "$status" ] && continue
    if [ "$status" = "PASS" ]; then ok "$msg"; else bad "$msg"; fi
  done <<< "$cfg_report"
else
  skipped "validacion de YAML (PyYAML no instalado)"
fi

# ---------------------------------------------------------------------------
# 5. requirements.txt debe cubrir lo que el codigo importa de terceros.
#    Nota: el nombre del paquete en PyPI no siempre coincide con el del modulo
#    (simple-pid -> simple_pid, pyyaml -> yaml), asi que la comparacion
#    normaliza guiones y guiones bajos.
# ---------------------------------------------------------------------------
echo
echo "requirements.txt:"
if [ -f "$ROOT/requirements.txt" ]; then
  declared="$(sed -E 's/#.*//; s/[<>=!~].*//; s/\[.*//; s/[[:space:]]//g; s/_/-/g' \
    "$ROOT/requirements.txt" | tr 'A-Z' 'a-z' | grep -v '^$' | sort -u)"
  missing_req=""
  for pair in "rich:rich" "simple_pid:simple-pid" "yaml:pyyaml" "urllib3:urllib3" "pyfiglet:pyfiglet"; do
    mod="${pair%%:*}"; pkg="${pair##*:}"
    if grep -rqE "^[[:space:]]*(import|from)[[:space:]]+$mod\b" "$ROOT"/*.py 2>/dev/null; then
      if ! grep -qx "$pkg" <<< "$declared"; then
        missing_req="$missing_req $pkg"
      fi
    fi
  done
  if [ -z "$missing_req" ]; then
    ok "declara todo lo que el codigo importa"
  else
    bad "no declara:$missing_req"
  fi
else
  bad "falta requirements.txt"
fi

echo
echo "resultado: $pass ok, $fail fallos, $skip saltados"
[ "$fail" -eq 0 ] || exit 1
exit 0
