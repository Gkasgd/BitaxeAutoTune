#!/usr/bin/env python3
"""Tests de que se exige lo que se usa y se avisa de lo que se supone.

Dos problemas distintos que salieron de la revision de coherencia config-docs, y
que tienen la misma raiz: el fork cambio de estrategia y la capa de validacion
siguio hablando de la anterior.

1. `required_keys` exigia siete claves que NINGUN modulo lee (las seis ganancias
   PID_* y HASHRATE_SETPOINT). Consecuencia medida: un perfil limpio y correcto
   para la estrategia de estabilidad no arranca, y el mensaje
   "Missing required config keys: PID_FREQ_KP, ..." manda a rellenar ganancias
   de un controlador PID que no existe en el programa.

2. Trece claves se leian con `config.get(clave, defecto)` y no estaban en
   ninguna lista, asi que faltar era invisible. La peor es ERROR_TUNING: su
   defecto (False) no es un matiz, es la OTRA estrategia. Un perfil escrito
   entero para la de estabilidad al que se le olvide esa linea arranca con la de
   limites y todo lo demas que declara se ignora sin una sola linea de log.

Ejecutar:  python3 -m unittest tests.test_claves_config -v
No necesita miner ni red.
"""

import glob
import os
import unittest

import yaml

from config import (
    CLAVES_OPCIONALES,
    CLAVES_SOLO_PID,
    opcional,
    validate_config,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Los YAML de fabrica viven en chips/ y los perfiles de usuario en perfiles/.
# Antes estaban los seis en la raiz, con nombres (safe-BM1370.yaml,
# safe-BM1370-estabilidad.yaml) que no decian ni donde ni que eran.
PERFIL_ESTABILIDAD = "perfiles/gamma-estabilidad.yaml"
PERFIL_CONSERVADOR = "perfiles/gamma-conservador.yaml"

# Los limites que un perfil de usuario NO puede dejarse heredar. Los cuatro
# extremos mas la temperatura objetivo y el limite de potencia: los seis valores
# que deciden que se escribe al hardware y cuando se retrocede.
LIMITES_DUROS = (
    "MIN_VOLTAGE",
    "MAX_VOLTAGE",
    "MIN_FREQUENCY",
    "MAX_FREQUENCY",
    "TARGET_TEMP",
    "POWER_LIMIT",
)

# Lo minimo con lo que el programa puede escribir un valor al miner. Es a
# proposito un perfil de estabilidad SIN ninguna clave PID: es el caso que
# fallaba.
BASE_ESTABILIDAD = {
    "INITIAL_VOLTAGE": 1185,
    "INITIAL_FREQUENCY": 475,
    "SAMPLE_INTERVAL": 30,
    "LOG_FILE": "data/x.csv",
    "SNAPSHOT_FILE": "data/x.json",
    "POOLS_FILE": "pools.yaml",
    "MIN_VOLTAGE": 1180,
    "MAX_VOLTAGE": 1210,
    "MIN_FREQUENCY": 475,
    "MAX_FREQUENCY": 925,
    "VOLTAGE_STEP": 5,
    "FREQUENCY_STEP": 5,
    "TARGET_TEMP": 60.0,
    "POWER_LIMIT": 30.0,
    "ERROR_TUNING": True,
    "ERROR_TARGET_PERCENT": 2.0,
}


def perfil(**extra):
    c = dict(BASE_ESTABILIDAD)
    c.update(extra)
    return c


class TestPerfilDeEstabilidadSinClavesPID(unittest.TestCase):
    """El caso del bug: un perfil correcto que no arrancaba."""

    def test_arranca_sin_ninguna_ganancia_pid(self):
        for clave in CLAVES_SOLO_PID:
            self.assertNotIn(clave, BASE_ESTABILIDAD, "el perfil base no debe traerlas")
        validate_config(perfil())  # no debe llamar a sys.exit

    def test_el_mensaje_no_pedia_lo_que_no_se_usa(self):
        """Antes salia 'Missing required config keys: PID_FREQ_KP, ...'."""
        with self.assertRaises(SystemExit):
            with self.assertLogs("config", level="ERROR") as captura:
                c = perfil()
                del c["MAX_VOLTAGE"]  # esta si es imprescindible
                validate_config(c)
        texto = "\n".join(captura.output)
        self.assertIn("MAX_VOLTAGE", texto)
        for clave in CLAVES_SOLO_PID:
            self.assertNotIn(clave, texto, f"sigue pidiendo {clave}, que nadie lee")


class TestLaOtraEstrategiaSiLasExige(unittest.TestCase):
    """Relajar la validacion no debe relajarla donde importa.

    Con ERROR_TUNING desactivado el CSV es el de esa estrategia y sus siete
    columnas se comparan con historiales antiguos, asi que ahi se siguen
    pidiendo.
    """

    def test_sin_error_tuning_faltan_las_pid(self):
        with self.assertRaises(SystemExit):
            validate_config(perfil(ERROR_TUNING=False))

    def test_con_las_pid_declaradas_arranca(self):
        extra = {k: 0.1 for k in CLAVES_SOLO_PID}
        validate_config(perfil(ERROR_TUNING=False, **extra))

    def test_error_tuning_ausente_cuenta_como_desactivado(self):
        """El defecto es False, asi que omitirlo entra en la rama estricta."""
        c = perfil()
        del c["ERROR_TUNING"]
        with self.assertRaises(SystemExit):
            validate_config(c)


class TestAvisoDeLosDefectos(unittest.TestCase):
    """Faltar no es un error, pero tiene que poder verse."""

    def test_avisa_de_las_opcionales_ausentes(self):
        with self.assertLogs("config", level="WARNING") as captura:
            validate_config(perfil())
        texto = "\n".join(captura.output)
        # ERROR_TUNING si esta en el perfil; el resto no.
        self.assertIn("ERROR_WINDOW=7", texto)
        self.assertIn("LOWER_VOLTAGE_AFTER=4", texto)
        self.assertNotIn("ERROR_TUNING=", texto)

    def test_el_aviso_de_error_tuning_es_explicito(self):
        """El caso que mas duele: cambia de estrategia, no de matiz."""
        c = perfil()
        del c["ERROR_TUNING"]
        c.update({k: 0.1 for k in CLAVES_SOLO_PID})  # para no morir antes
        with self.assertLogs("config", level="WARNING") as captura:
            validate_config(c)
        texto = "\n".join(captura.output)
        self.assertIn("ERROR_TUNING", texto)
        self.assertIn("estrategia", texto)

    def test_no_avisa_de_lo_declarado(self):
        declaradas = dict(CLAVES_OPCIONALES)
        declaradas["ERROR_TUNING"] = True  # su defecto es False y exigiria las PID
        c = perfil(**declaradas)
        with self.assertLogs("config", level="WARNING") as captura:
            import logging

            logging.getLogger("config").warning("centinela: assertLogs exige uno")
            validate_config(c)
        self.assertEqual(len(captura.output), 1, f"aviso de mas: {captura.output}")


class TestOpcionalEsLaUnicaFuente(unittest.TestCase):
    """Un defecto escrito en dos sitios se separa; por eso solo hay una tabla."""

    def test_devuelve_lo_configurado(self):
        self.assertEqual(opcional({"ERROR_WINDOW": 9}, "ERROR_WINDOW"), 9)

    def test_devuelve_el_defecto_si_falta(self):
        self.assertEqual(opcional({}, "ERROR_WINDOW"), CLAVES_OPCIONALES["ERROR_WINDOW"])

    def test_una_clave_no_declarada_es_un_error_del_programador(self):
        with self.assertRaises(KeyError):
            opcional({}, "NO_DECLARADA")

    def test_nadie_lee_con_un_defecto_suelto(self):
        """Ningun modulo debe hacer config.get("CLAVE_OPCIONAL", X).

        Es la regresion que se quiere impedir: mientras los defectos vivan
        tambien en las llamadas, el YAML puede documentar un numero y el codigo
        aplicar otro sin que nada falle.
        """
        culpables = []
        for path in sorted(glob.glob(os.path.join(REPO_ROOT, "*.py"))):
            with open(path, encoding="utf-8") as fh:
                for n, linea in enumerate(fh, 1):
                    for clave in CLAVES_OPCIONALES:
                        if f'get("{clave}"' in linea and linea.count(",") >= 1:
                            culpables.append(f"{os.path.basename(path)}:{n} {clave}")
        self.assertEqual(
            culpables, [], "leer con un defecto propio en vez de opcional(): " + str(culpables)
        )


class TestLosPerfilesDelProyectoSonValidos(unittest.TestCase):
    """Lo que se envia al nodo tiene que pasar su propia validacion."""

    def _cargar(self, nombre):
        with open(os.path.join(REPO_ROOT, nombre), encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_el_perfil_de_estabilidad_valida(self):
        base = self._cargar("chips/BM1370.yaml")
        base.update(self._cargar(PERFIL_ESTABILIDAD))
        validate_config(base)

    def test_el_perfil_de_estabilidad_no_hereda_nada(self):
        """Lo que se lee en ese fichero es lo que corre, sin excepciones."""
        base = self._cargar("chips/BM1370.yaml")
        propio = self._cargar(PERFIL_ESTABILIDAD)
        efectivo = dict(base)
        efectivo.update(propio)
        heredadas = sorted(k for k in efectivo if k not in propio)
        self.assertEqual(heredadas, [], f"hereda del YAML del chip: {heredadas}")

    def test_el_perfil_conservador_declara_sus_cuatro_limites(self):
        """El hallazgo: heredaba MIN_VOLTAGE 1000 y MIN_FREQUENCY 400.

        Un perfil llamado "safe" cuyo suelo efectivo era el de fabrica. Importa
        porque el suelo es hasta donde baja la busqueda del voltaje minimo y la
        rama termica.
        """
        propio = self._cargar(PERFIL_CONSERVADOR)
        for clave in ("MIN_VOLTAGE", "MAX_VOLTAGE", "MIN_FREQUENCY", "MAX_FREQUENCY"):
            self.assertIn(clave, propio, f"{clave} se heredaria del YAML del chip")
        self.assertGreater(propio["MIN_VOLTAGE"], 1000, "el suelo de fabrica no es seguro")

    def test_el_perfil_conservador_valida(self):
        base = self._cargar("chips/BM1370.yaml")
        base.update(self._cargar(PERFIL_CONSERVADOR))
        validate_config(base)


class TestTodoPerfilDeclaraSusLimites(unittest.TestCase):
    """Vale para los perfiles que existan, no solo para los dos de hoy.

    El hallazgo del que sale: el perfil conservador heredaba MIN_VOLTAGE 1000 y
    MIN_FREQUENCY 400 de chips/BM1370.yaml, o sea los de fabrica. Un fichero
    llamado "safe" con el suelo efectivo sin recortar.

    Se comprueba por glob y no contra una lista de nombres para que un perfil
    nuevo que alguien anada a perfiles/ quede cubierto sin tener que acordarse de
    tocar este test. Es lo que hace que la comprobacion sobreviva al proximo
    perfil, que es cuando vuelve a hacer falta.
    """

    def test_los_seis_limites_estan_declarados(self):
        rutas = sorted(glob.glob(os.path.join(REPO_ROOT, "perfiles", "*.yaml")))
        self.assertTrue(rutas, "no se encontro ningun perfil en perfiles/")
        for ruta in rutas:
            nombre = os.path.basename(ruta)
            with self.subTest(perfil=nombre):
                with open(ruta, encoding="utf-8") as fh:
                    propio = yaml.safe_load(fh)
                faltan = [k for k in LIMITES_DUROS if k not in propio]
                self.assertEqual(
                    faltan,
                    [],
                    f"{nombre} heredaria de chips/ estos limites: "
                    f"{', '.join(faltan)}. Un perfil tiene que declarar su propio "
                    "rango: lo que no declara sale de los limites de fabrica, que "
                    "es justo lo que un perfil existe para recortar",
                )

    def test_los_limites_no_estan_invertidos(self):
        """El recorte de seguridad devuelve el minimo si min > max."""
        for ruta in sorted(glob.glob(os.path.join(REPO_ROOT, "perfiles", "*.yaml"))):
            nombre = os.path.basename(ruta)
            with self.subTest(perfil=nombre):
                with open(ruta, encoding="utf-8") as fh:
                    propio = yaml.safe_load(fh)
                self.assertLessEqual(propio["MIN_VOLTAGE"], propio["MAX_VOLTAGE"], nombre)
                self.assertLessEqual(
                    propio["MIN_FREQUENCY"], propio["MAX_FREQUENCY"], nombre
                )


class TestElContainerfileCopiaLaConfiguracion(unittest.TestCase):
    """El riesgo que ninguna otra prueba local cubre.

    `COPY *.yaml *.py banner.txt ./` no incluye subdirectorios: los comodines de
    COPY no bajan de nivel. Con los seis YAML en la raiz bastaba esa linea; al
    moverlos a chips/ y perfiles/ hacen falta dos COPY explicitos, y si faltan la
    imagen se construye sin ninguna configuracion. El programa termina con "ASIC
    model YAML file chips/BM1370.yaml not found" y `restart: unless-stopped` lo
    deja en bucle de reinicio contra un miner encendido.

    Solo se ve construyendo la imagen, que no se puede hacer aqui. Esto es lo
    mas cerca que se llega sin Docker: que las rutas esten declaradas.
    """

    def test_declara_los_dos_directorios(self):
        with open(os.path.join(REPO_ROOT, "Containerfile"), encoding="utf-8") as fh:
            lineas = [
                l.strip() for l in fh if l.strip().upper().startswith("COPY")
            ]
        texto = "\n".join(lineas)
        for directorio in ("chips/", "perfiles/"):
            self.assertIn(
                directorio,
                texto,
                f"ningun COPY del Containerfile menciona {directorio}: la imagen "
                "se construiria sin configuracion y el contenedor entraria en "
                "bucle de reinicio",
            )

    def test_los_directorios_que_copia_existen(self):
        """Un COPY de un directorio que no esta hace fallar el build entero."""
        with open(os.path.join(REPO_ROOT, "Containerfile"), encoding="utf-8") as fh:
            copias = [
                l.split()[1]
                for l in fh
                if l.strip().upper().startswith("COPY") and len(l.split()) >= 3
            ]
        for origen in copias:
            if "*" in origen:
                continue
            with self.subTest(origen=origen):
                self.assertTrue(
                    os.path.exists(os.path.join(REPO_ROOT, origen)),
                    f"el Containerfile copia {origen}, que no esta en el repo",
                )


class TestElDefaultDeDespliegueEsElQueSeUsa(unittest.TestCase):
    """.env.example y docker-compose.yml deben apuntar al perfil real.

    El hallazgo lo encontro g: las instrucciones decian editar
    safe-BM1370-estabilidad.yaml mientras el .env.example enviado cargaba
    safe-BM1370.yaml, o sea la otra estrategia con otros limites.
    """

    PERFIL = PERFIL_ESTABILIDAD

    def test_env_example(self):
        with open(os.path.join(REPO_ROOT, ".env.example"), encoding="utf-8") as fh:
            for linea in fh:
                if linea.startswith("BITAXEPID_CONFIG="):
                    self.assertEqual(linea.strip(), f"BITAXEPID_CONFIG={self.PERFIL}")
                    return
        self.fail("no hay linea BITAXEPID_CONFIG en .env.example")

    def test_compose_usa_el_mismo_por_defecto(self):
        with open(os.path.join(REPO_ROOT, "docker-compose.yml"), encoding="utf-8") as fh:
            texto = fh.read()
        self.assertIn(f"BITAXEPID_CONFIG:-{self.PERFIL}", texto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
