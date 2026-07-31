#!/usr/bin/env python3
"""Tests de que --dry-run valida la configuracion sin tocar el miner.

`--dry-run` existe para poder comprobar un perfil antes de dejarlo corriendo
contra hardware: carga los dos YAML, los fusiona, los valida y dice de que
fichero sale cada clave. La promesa es que no abre ninguna conexion, y esa
promesa es facil de romper sin que se note: `BitaxeAPIClient` monta la sesion
HTTP en su constructor, asi que basta con colocar la salida una linea mas abajo
para que el modo haga justo lo que dice no hacer. Un test que solo comprobara el
codigo de salida no lo detectaria.

Por eso el doble de la API falla al construirse, no al usarse: lo que se fija
aqui es que en --dry-run ni se instancia.

Tambien se comprueba la relajacion de --ip. Era `required=True`; ahora solo se
exige fuera de --dry-run, y esa condicion tiene que seguir dando el mismo error
que antes, porque es la que evita arrancar el tuner sin saber contra quien.

Ejecutar:  python3 -m unittest tests.test_dry_run -v
No necesita miner ni red: cualquier intento de conectar es un fallo del test.
"""

import contextlib
import io
import logging
import os
import tempfile
import unittest
from unittest import mock

import bitaxepid
from cli import parse_arguments

# Un chip de fabrica con margen de sobra y un perfil que solo baja los maximos.
# Es el reparto que hace falta para que la procedencia signifique algo: la mitad
# de las claves las declara el perfil y la otra mitad las hereda.
CHIP = """
INITIAL_VOLTAGE: 1150
MIN_VOLTAGE: 1000
MAX_VOLTAGE: 1250
INITIAL_FREQUENCY: 550
MIN_FREQUENCY: 400
MAX_FREQUENCY: 625
VOLTAGE_STEP: 10
FREQUENCY_STEP: 25
SAMPLE_INTERVAL: 30
TARGET_TEMP: 60.0
POWER_LIMIT: 30.0
LOG_FILE: tuning.csv
SNAPSHOT_FILE: snapshot.json
POOLS_FILE: pools.yaml
ERROR_TUNING: TRUE
ERROR_TARGET_PERCENT: 2.0
"""

PERFIL = """
MAX_VOLTAGE: 1150
MAX_FREQUENCY: 500
"""


class ApiClientProhibido:
    """Doble de BitaxeAPIClient que falla en el constructor.

    El original abre la sesion HTTP al construirse, asi que instanciarlo YA es
    la conexion que --dry-run promete no abrir.
    """

    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "--dry-run construyo el cliente de la API: la salida temprana esta "
            "colocada demasiado abajo"
        )


class BaseDryRun(unittest.TestCase):
    def setUp(self):
        # Se trabaja en un directorio temporal porque main() crea
        # bitaxepid_monitor.log en el directorio actual, y los YAML se resuelven
        # tambien relativos a el.
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        anterior = os.getcwd()
        os.chdir(self.dir.name)
        self.addCleanup(os.chdir, anterior)
        # En chips/, que es donde el programa lo busca (config.ruta_yaml_de_chip).
        os.mkdir("chips")
        self.escribir(os.path.join("chips", "BM1370.yaml"), CHIP)
        self.perfil = self.escribir("perfil.yaml", PERFIL)

        # logging.basicConfig no hace nada si el root ya tiene handlers, y varios
        # tests de la bateria configuran el suyo. Se limpia para que el
        # --dry-run de este test escriba donde cree que escribe.
        root = logging.getLogger()
        handlers_previos = root.handlers[:]
        nivel_previo = root.level

        def restaurar():
            for h in root.handlers[:]:
                root.removeHandler(h)
                h.close()
            for h in handlers_previos:
                root.addHandler(h)
            root.setLevel(nivel_previo)

        self.addCleanup(restaurar)
        for h in root.handlers[:]:
            root.removeHandler(h)

    def escribir(self, nombre, contenido):
        ruta = os.path.join(self.dir.name, nombre)
        with open(ruta, "w") as fh:
            fh.write(contenido)
        return ruta

    def correr(self, *argv):
        """Ejecutar main() con esos argumentos y devolver (codigo, stdout)."""
        salida = io.StringIO()
        with mock.patch.object(bitaxepid, "BitaxeAPIClient", ApiClientProhibido):
            with mock.patch("sys.argv", ["bitaxepid.py", *argv]):
                with contextlib.redirect_stdout(salida):
                    with self.assertRaises(SystemExit) as ctx:
                        bitaxepid.main()
        return ctx.exception.code, salida.getvalue()


class TestNoTocaElMiner(BaseDryRun):
    """El caso que importa: --dry-run no debe abrir ninguna conexion."""

    def test_no_construye_el_cliente_de_la_api(self):
        codigo, _ = self.correr("--dry-run", "--asic", "BM1370", "--config", "perfil.yaml")
        self.assertEqual(codigo, 0)

    def test_sale_con_cero_aunque_no_haya_red(self):
        """Sin --ip y sin miner alcanzable, sigue siendo un exito."""
        codigo, _ = self.correr("--dry-run", "--asic", "BM1370")
        self.assertEqual(codigo, 0)

    def test_una_configuracion_invalida_falla(self):
        """Si no sirviera para detectar un perfil roto, no serviria para nada."""
        self.escribir("perfil.yaml", "MIN_VOLTAGE: 1200\nMAX_VOLTAGE: 1100\n")
        codigo, _ = self.correr("--dry-run", "--asic", "BM1370", "--config", "perfil.yaml")
        self.assertEqual(codigo, 1)


class TestSalidaDeProcedencia(BaseDryRun):
    """La salida tiene que decir de que fichero sale cada clave."""

    def test_distingue_las_dos_capas(self):
        _, salida = self.correr(
            "--dry-run", "--asic", "BM1370", "--config", "perfil.yaml"
        )
        # Declarada en el perfil, y con el valor del perfil, no el del chip.
        self.assertRegex(salida, r"MAX_VOLTAGE\s+1150\s+<- perfil\.yaml")
        # Heredada del chip: el caso que motiva todo esto. Un perfil que baja el
        # maximo y se deja el minimo tiene un rango efectivo que su nombre no
        # dice.
        # La ruta la construye config.ruta_yaml_de_chip con una barra normal,
        # tambien en Windows: es la que se pasa a open(), no una ruta del sistema.
        self.assertRegex(salida, r"MIN_VOLTAGE\s+1000\s+<- chips/BM1370\.yaml")

    def test_lista_las_opcionales_ausentes_con_su_defecto(self):
        _, salida = self.correr(
            "--dry-run", "--asic", "BM1370", "--config", "perfil.yaml"
        )
        self.assertIn("rige el defecto del programa", salida)
        self.assertRegex(salida, r"ERROR_WINDOW\s+7")

    def test_marca_los_overrides_de_linea_de_comandos(self):
        """Un valor de la CLI no puede aparecer atribuido a un YAML."""
        _, salida = self.correr(
            "--dry-run", "--asic", "BM1370", "--config", "perfil.yaml",
            "--voltage", "1100",
        )
        self.assertRegex(salida, r"INITIAL_VOLTAGE\s+1100\s+<- --voltage")

    def test_marca_los_valores_recortados(self):
        """El chip arranca a 550MHz y el perfil baja el techo a 500.

        El 500 resultante no lo escribio nadie: lo puso clamp_initial_values. Si
        la tabla lo atribuyera al YAML del chip, quien la lea buscaria un 500 que
        no esta en ningun fichero.
        """
        _, salida = self.correr(
            "--dry-run", "--asic", "BM1370", "--config", "perfil.yaml"
        )
        self.assertRegex(salida, r"INITIAL_FREQUENCY\s+500\s+<- recortado al rango")
        self.assertIn("se pidio 550", salida)


class TestArgumentos(unittest.TestCase):
    """La relajacion de --ip no debe abrir agujeros en el arranque normal."""

    def correr(self, *argv):
        with mock.patch("sys.argv", ["bitaxepid.py", *argv]):
            with contextlib.redirect_stderr(io.StringIO()):
                return parse_arguments()

    def test_sin_ip_y_sin_dry_run_aborta(self):
        with self.assertRaises(SystemExit) as ctx:
            self.correr("--config", "perfil.yaml")
        self.assertEqual(ctx.exception.code, 2)

    def test_dry_run_sin_asic_aborta(self):
        """Sin modelo no hay YAML de chip, y adivinarlo validaria contra otro."""
        with self.assertRaises(SystemExit) as ctx:
            self.correr("--dry-run")
        self.assertEqual(ctx.exception.code, 2)

    def test_asic_sin_dry_run_aborta(self):
        """En una ejecucion normal el modelo lo da el miner: --asic se ignoraria."""
        with self.assertRaises(SystemExit) as ctx:
            self.correr("--ip", "192.0.2.1", "--asic", "BM1370")
        self.assertEqual(ctx.exception.code, 2)

    def test_dry_run_no_exige_ip(self):
        args = self.correr("--dry-run", "--asic", "BM1370")
        self.assertIsNone(args.ip)
        self.assertTrue(args.dry_run)


if __name__ == "__main__":
    unittest.main()
