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
# El interprete se puede elegir con la variable PYTHON, util en Windows, donde
# el ejecutable se llama "python" y no "python3":
#   PYTHON=python ./scripts/smoke_test.sh
#
# Necesita bash. En Windows funciona en Git Bash y en WSL.
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
# 1b. Nombres libres: variables o funciones que un modulo usa pero no define ni
#     importa. Esto NO lo detecta py_compile, y tampoco necesariamente el import
#     del modulo, porque el fallo solo salta al ejecutar la linea afectada. Al
#     mover codigo entre modulos es el error mas facil de cometer: te llevas la
#     clase y te dejas el import.
# ---------------------------------------------------------------------------
echo
echo "nombres libres:"
libres="$("$PY" - "$ROOT" <<'PYEOF'
import ast
import builtins
import glob
import os
import sys

root = sys.argv[1]
paths = sorted(glob.glob(os.path.join(root, "*.py"))) + sorted(
    glob.glob(os.path.join(root, "tests", "*.py"))
)
for path in paths:
    name = os.path.relpath(path, root)
    try:
        tree = ast.parse(open(path).read())
    except SyntaxError as exc:
        print(f"FAIL|{name} no parsea: {exc}")
        continue
    defined = set(dir(builtins)) | {"__file__", "__name__", "self"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
    used = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    missing = sorted(used - defined)
    if missing:
        print(f"FAIL|{name} usa nombres que no define ni importa: {', '.join(missing)}")
    else:
        print(f"PASS|{name} sin nombres libres")
PYEOF
)"
while IFS='|' read -r status msg; do
  [ -z "$status" ] && continue
  if [ "$status" = "PASS" ]; then ok "$msg"; else bad "$msg"; fi
done <<< "$libres"

# ---------------------------------------------------------------------------
# 2. Dependencias de terceros
# ---------------------------------------------------------------------------
echo
echo "dependencias:"
DEPS_OK=1
# simple_pid ya no esta en la lista: no queda ningun PID en el programa y nadie
# lo importa. Dejarlo tenia un efecto peor que el ruido: al no instalarse ya con
# requirements.txt, ponia DEPS_OK a 0 y con eso se SALTABAN los imports del
# proyecto, la CLI y la suite entera, sin marcar un solo fallo.
for mod in rich pyfiglet urllib3 yaml; do
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
# 4b. El despliegue con docker compose: que el YAML sea valido y que el comando
#     que se le pasa al contenedor encaje con el ENTRYPOINT del Containerfile.
#     El ENTRYPOINT termina en --ip, asi que el primer elemento de command debe
#     ser la IP y no un flag; si alguien reordena uno de los dos ficheros sin
#     mirar el otro, el contenedor arranca con --ip apuntando a un flag.
# ---------------------------------------------------------------------------
echo
echo "despliegue con docker compose:"
if [ ! -f "$ROOT/docker-compose.yml" ]; then
  skipped "docker-compose.yml (no existe)"
elif ! "$PY" -c "import yaml" 2>/dev/null; then
  skipped "docker-compose.yml (PyYAML no instalado)"
else
  compose_report="$("$PY" - "$ROOT" <<'COMPOSEEOF'
import json
import os
import re
import sys

import yaml

root = sys.argv[1]
out = []

try:
    with open(os.path.join(root, "docker-compose.yml")) as fh:
        compose = yaml.safe_load(fh)
except Exception as exc:
    print(f"FAIL|docker-compose.yml no es YAML valido: {exc}")
    sys.exit(0)

services = (compose or {}).get("services") or {}
if not services:
    print("FAIL|docker-compose.yml no define ningun servicio")
    sys.exit(0)
out.append(f"PASS|docker-compose.yml es YAML valido ({len(services)} servicio)")

svc = services.get("bitaxepid")
if svc is None:
    print("FAIL|docker-compose.yml no define el servicio bitaxepid")
    sys.exit(0)

# El ENTRYPOINT se lee del Containerfile, no se da por supuesto.
entry = None
try:
    with open(os.path.join(root, "Containerfile")) as fh:
        match = re.search(r"^ENTRYPOINT\s+(\[.*\])\s*$", fh.read(), re.M)
    if match:
        entry = json.loads(match.group(1))
except Exception:
    entry = None

command = svc.get("command")
if not isinstance(command, list) or not command:
    out.append("FAIL|el servicio bitaxepid no define command como lista")
elif entry is None:
    out.append("FAIL|no se pudo leer el ENTRYPOINT del Containerfile")
elif entry[-1] != "--ip":
    out.append(f"FAIL|el ENTRYPOINT no termina en --ip sino en {entry[-1]}")
elif command[0].startswith("-"):
    out.append(
        f"FAIL|command[0] es {command[0]}, pero el ENTRYPOINT espera ahi la IP"
    )
else:
    out.append("PASS|command encaja con el ENTRYPOINT (la IP va primera)")

# La plantilla de variables debe declarar las que el compose usa: si falta una,
# el fallo aparece en el despliegue del usuario y no aqui.
env_vars = set(re.findall(r"\$\{(\w+)", yaml.safe_dump(compose)))
example = os.path.join(root, ".env.example")
if not env_vars:
    out.append("PASS|el compose no depende de variables de entorno")
elif not os.path.exists(example):
    out.append(f"FAIL|el compose usa {len(env_vars)} variables y no hay .env.example")
else:
    with open(example) as fh:
        declared = {
            line.split("=", 1)[0].strip()
            for line in fh
            if "=" in line and not line.lstrip().startswith("#")
        }
    faltan = sorted(env_vars - declared)
    if faltan:
        out.append(f"FAIL|.env.example no declara: {', '.join(faltan)}")
    else:
        out.append(f"PASS|.env.example declara las {len(env_vars)} variables usadas")

# El perfil que el compose usa por defecto tiene que existir en el repo.
default_cfg = None
if isinstance(command, list):
    for i, arg in enumerate(command):
        if arg == "--config" and i + 1 < len(command):
            default_cfg = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", command[i + 1])
if default_cfg:
    if os.path.exists(os.path.join(root, default_cfg)):
        out.append(f"PASS|el perfil por defecto del compose existe ({default_cfg})")
    else:
        out.append(f"FAIL|el compose apunta a {default_cfg}, que no esta en el repo")

for line in out:
    print(line)
COMPOSEEOF
)"
  while IFS='|' read -r status msg; do
    [ -z "$status" ] && continue
    if [ "$status" = "PASS" ]; then ok "$msg"; else bad "$msg"; fi
  done <<< "$compose_report"
fi

# ---------------------------------------------------------------------------
# 5. requirements.txt y los imports del codigo tienen que coincidir EN LOS DOS
#    SENTIDOS.
#
#    Nota: el nombre del paquete en PyPI no siempre coincide con el del modulo
#    (simple-pid -> simple_pid, pyyaml -> yaml), asi que la comparacion
#    normaliza guiones y guiones bajos.
#
#    La segunda direccion se anadio porque faltaba: requirements.txt declaraba
#    simple-pid mucho despues de que el fork se quedara sin ningun PID, y nada lo
#    detectaba. El Containerfile instala este fichero tal cual, asi que una
#    dependencia declarada y no importada se instala en el nodo para no
#    ejecutarse nunca. El par simple_pid:simple-pid se deja en la lista a
#    proposito: si algun dia vuelve un PID, la primera direccion avisa de que
#    hay que declararlo.
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

  # La direccion contraria: declarado y no importado por nadie.
  sobra_req=""
  for pair in "rich:rich" "simple_pid:simple-pid" "yaml:pyyaml" "urllib3:urllib3" "pyfiglet:pyfiglet"; do
    mod="${pair%%:*}"; pkg="${pair##*:}"
    if grep -qx "$pkg" <<< "$declared"; then
      if ! grep -rqE "^[[:space:]]*(import|from)[[:space:]]+$mod\b" "$ROOT"/*.py 2>/dev/null; then
        sobra_req="$sobra_req $pkg"
      fi
    fi
  done
  if [ -z "$sobra_req" ]; then
    ok "no declara nada que el codigo no importe"
  else
    bad "declara sin usar (el Containerfile lo instalaria):$sobra_req"
  fi
else
  bad "falta requirements.txt"
fi

# ---------------------------------------------------------------------------
# 6. Tests unitarios de tests/, si las dependencias lo permiten.
# ---------------------------------------------------------------------------
echo
echo "tests unitarios:"
if [ -d "$ROOT/tests" ]; then
  if [ "$DEPS_OK" = "1" ]; then
    if out="$(cd "$ROOT" && "$PY" -m unittest discover -s tests -t . 2>&1)"; then
      ok "unittest discover ($(grep -oE 'Ran [0-9]+ test' <<< "$out" | head -1))"
    else
      bad "unittest discover"
      echo "$out" | tail -12 | sed 's/^/          /'
    fi
  else
    skipped "unittest discover (faltan dependencias)"
  fi
else
  skipped "no hay directorio tests/"
fi

echo
echo "resultado: $pass ok, $fail fallos, $skip saltados"
[ "$fail" -eq 0 ] || exit 1
exit 0
