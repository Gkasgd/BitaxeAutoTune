#!/usr/bin/env python3
"""Tests de que lo que la documentacion manda buscar en el log existe.

El patron que motiva este fichero es peor que una errata. La documentacion le
dice al usuario "comprueba que el arreglo esta puesto buscando esta linea en el
log". Si la linea no existe, el grep sale vacio y la conclusion del usuario no es
"la documentacion esta mal", es "el arreglo NO esta puesto". Con las manos en un
miner encendido, eso lleva a deshacer un cambio que si estaba bien.

Hay que distinguir DOS destinos de grep, porque no fallan igual:

A. Grep sobre el LOG. Ahi la frase sale ya montada en una sola linea, con los
   valores puestos. Lo que rompe el grep es un valor INTERPOLADO EN MEDIO:
   "Bajando frecuencia a 475MHz por temperatura 62C" no se encuentra buscando
   "Bajando frecuencia a MHz por temperatura". De ahi la regla que el LEEME
   explica al usuario: citar solo el trozo anterior al primer valor.

B. Grep sobre el .py, que es lo que hace el LEEME para comprobar que la imagen
   del contenedor se reconstruyo. Ahi rompe algo distinto: un mensaje largo se
   escribe como varios literales en LINEAS CONSECUTIVAS del fuente, y grep
   trabaja linea a linea. La frase existe en el log pero no en ninguna linea
   del fichero.

Los dos casos que habia:

1. UMBREL.md prometia `Increasing voltage to`, `System stable at` y
   `Reducing frequency to`. El fork tradujo las decisiones al castellano hace
   tiempo; esos tres strings en ingles no estan en ningun .py. La unica
   aparicion de "System stable" en todo el arbol es un comentario que explica
   por que se quito. Esto no era un problema de formato: la frase no existia.

2. LEEME.md citaba `... ya en la frecuencia minima ...MHz` de una forma que no
   cuadraba con el fuente. Esa frase SI sale seguida en el log
   (tuning_estabilidad.py:391-392 la parte entre "ya en la " y "frecuencia
   minima", pero eso es un corte de linea del fuente, no una interpolacion),
   asi que el caso A esta bien y el grep al log funciona. Lo que no funcionaria
   es grepearla contra el .py: caso B.

Por eso `TestLosGrepsContraElFuente` comprueba aparte que toda frase que la
documentacion manda buscar DENTRO DE UN .py quepa en una linea fisica.

Ejecutar:  python3 -m unittest tests.test_citas_de_log -v
No necesita miner ni red.
"""

import glob
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(os.path.dirname(REPO_ROOT), "archivos-para-umbrel")


def fuentes():
    """El texto de todos los .py del proyecto, concatenado."""
    trozos = []
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, "*.py"))):
        with open(path, encoding="utf-8") as fh:
            trozos.append(fh.read())
    return "\n".join(trozos)


FUENTES = fuentes()


def normalizar(texto):
    """Quitar los saltos de linea y la sangria que parten los f-strings.

    Un mensaje largo se escribe en el codigo como varios literales consecutivos:

        f"Bajando voltaje a {nueva_v}mV por "
        f"temperatura {temp}C > {self.target_temp}C: ya en la "
        f"frecuencia minima {self.min_frequency}MHz"

    En la salida eso es una sola linea. Para comprobar que una cita existe hay
    que buscarla sobre el texto reconstruido, no sobre el fuente en bruto.
    """
    # Cierre de un literal, espacios y salto, apertura del siguiente.
    pegado = re.sub(r'"\s*\n\s*f?"', "", texto)
    return re.sub(r"\s+", " ", pegado)


FUENTES_PEGADAS = normalizar(FUENTES)


class TestLosStringsEnInglesYaNoEstan(unittest.TestCase):
    """Regresion: no volver a citar los mensajes de antes de la traduccion."""

    FANTASMAS = (
        "Increasing voltage to",
        "System stable at",
        "Reducing frequency to",
        "Decreasing frequency to",
        "Reducing voltage to",
    )

    def test_no_los_emite_el_codigo(self):
        """Si alguno reapareciera, esta lista habria que revisarla."""
        for texto in self.FANTASMAS:
            self.assertNotIn(
                texto,
                FUENTES_PEGADAS,
                f"'{texto}' ha vuelto al codigo: revisa si la documentacion "
                "deberia citarlo otra vez",
            )

    def test_no_los_promete_la_documentacion(self):
        """El fallo real: UMBREL.md mandaba buscar los tres primeros."""
        for doc in ("README.md", "UMBREL.md"):
            path = os.path.join(REPO_ROOT, doc)
            with open(path, encoding="utf-8") as fh:
                contenido = fh.read()
            for texto in self.FANTASMAS:
                self.assertNotIn(
                    texto,
                    contenido,
                    f"{doc} cita '{texto}', que el programa no emite: "
                    "un grep del usuario saldria vacio",
                )


class TestLasCitasDelLEEMEExisten(unittest.TestCase):
    """Cada frase que el LEEME manda buscar tiene que estar en el codigo.

    Se citan solo los trozos anteriores al primer valor interpolado, que es
    justamente la regla que el propio LEEME explica al usuario.
    """

    CITAS = (
        # El arreglo de la RAMPA que no abandona por el calor anterior.
        "al arrancar puede ser calor del ajuste anterior",
        # La RAMPA sube voltaje de golpe y luego frecuencia.
        "RAMPA: voltaje al maximo",
        "RAMPA: subiendo frecuencia a",
        # Adopcion de un cambio hecho desde la web de AxeOS.
        "Ajuste cambiado fuera del tuner",
        "Se adopta y se sigue optimizando desde ahi",
        # La palanca termica es la frecuencia.
        "Bajando frecuencia a",
        "por temperatura",
        # Y el voltaje solo cuando ya no queda frecuencia. En el log esta frase
        # sale seguida; en el fuente esta partida en dos lineas (caso B).
        "ya en la frecuencia minima",
        # La bajada de voltaje con su propia espera.
        "OPTIMIZAR: estable",
        "para buscar el minimo",
    )

    def test_todas_estan_en_el_codigo(self):
        ausentes = [c for c in self.CITAS if c not in FUENTES_PEGADAS]
        self.assertEqual(
            ausentes,
            [],
            f"el LEEME manda buscar frases que el codigo no emite: {ausentes}",
        )

    def test_el_leeme_sigue_citandolas(self):
        """Si se reescribe el LEEME, que no se pierdan las comprobaciones."""
        path = os.path.join(BUNDLE, "LEEME.md")
        if not os.path.exists(path):
            self.skipTest("el paquete de entrega no esta en este arbol")
        with open(path, encoding="utf-8") as fh:
            contenido = fh.read()
        # Las mas importantes: las que verifican los arreglos de hardware.
        for cita in (
            "calor del ajuste anterior",
            "Ajuste cambiado fuera del tuner",
            "Bajando frecuencia a",
            "OPTIMIZAR: estable",
        ):
            self.assertIn(cita, contenido, f"el LEEME ya no verifica '{cita}'")

    def test_avisa_de_como_hacer_el_grep(self):
        """La causa raiz: copiar la frase entera no funciona."""
        path = os.path.join(BUNDLE, "LEEME.md")
        if not os.path.exists(path):
            self.skipTest("el paquete de entrega no esta en este arbol")
        with open(path, encoding="utf-8") as fh:
            contenido = fh.read()
        self.assertIn("grep", contenido)
        self.assertIn("anterior al primer", contenido)


class TestLasCitasDeUmbrelExisten(unittest.TestCase):
    """UMBREL.md cita el log de arranque linea por linea."""

    ARRANQUE = (
        "Initialized BitaxeAPIClient",
        "Gestion de pools desactivada",
        "Initializing hardware",
        "Applied settings",
        "Metrics server started",
        "Starting BitaxePID tuner",
        "esta fuera del rango",
    )

    def test_el_log_de_arranque_es_real(self):
        ausentes = [c for c in self.ARRANQUE if c not in FUENTES_PEGADAS]
        self.assertEqual(ausentes, [], f"UMBREL.md cita lo inexistente: {ausentes}")

    def test_cita_las_decisiones_en_castellano(self):
        path = os.path.join(REPO_ROOT, "UMBREL.md")
        with open(path, encoding="utf-8") as fh:
            contenido = fh.read()
        for cita in ("Bajando frecuencia a", "Estable en"):
            self.assertIn(cita, contenido)
            self.assertIn(cita, FUENTES_PEGADAS, f"'{cita}' no lo emite el codigo")


class TestLosGrepsContraElFuente(unittest.TestCase):
    """Caso B: lo que se busca dentro de un .py tiene que caber en una linea.

    El LEEME manda comprobar que la imagen se reconstruyo con

        docker compose exec bitaxepid grep -c "..." tuning_estabilidad.py

    y grep casa linea a linea. Si la frase citada esta repartida en dos
    literales consecutivos del fuente, el comando devuelve 0 aunque el codigo
    nuevo este dentro, y el usuario concluye que el --build no se aplico.

    Es el mismo desenlace que el caso A y por el camino contrario: alli fallaba
    porque el log lleva numeros en medio, aqui porque el fuente lleva saltos de
    linea en medio.
    """

    # Frases que la documentacion greperea contra un .py, no contra el log.
    CONTRA_FUENTE = ("calor del ajuste anterior",)

    def _lineas_del_fuente(self):
        lineas = []
        for path in sorted(glob.glob(os.path.join(REPO_ROOT, "*.py"))):
            with open(path, encoding="utf-8") as fh:
                lineas.extend(fh.readlines())
        return lineas

    def test_caben_en_una_linea_fisica(self):
        lineas = self._lineas_del_fuente()
        for cita in self.CONTRA_FUENTE:
            self.assertTrue(
                any(cita in linea for linea in lineas),
                f"'{cita}' no cabe en ninguna linea de ningun .py: el "
                "grep -c del LEEME devolveria 0 y pareceria que falta el arreglo",
            )

    def test_el_leeme_manda_ese_grep(self):
        """Si se cambia el comando, esta lista hay que revisarla."""
        path = os.path.join(BUNDLE, "LEEME.md")
        if not os.path.exists(path):
            self.skipTest("el paquete de entrega no esta en este arbol")
        with open(path, encoding="utf-8") as fh:
            contenido = fh.read()
        for cita in self.CONTRA_FUENTE:
            if f'grep -c "{cita}"' not in contenido:
                self.fail(
                    f"el LEEME ya no greperea '{cita}' contra el fuente: "
                    "actualiza CONTRA_FUENTE con la frase que use ahora"
                )

    def test_la_frase_del_log_no_cabe_y_por_eso_no_se_greperea_asi(self):
        """Documenta el caso B con el ejemplo real, para que no se repita.

        "ya en la frecuencia minima" existe en el log pero NO en ninguna linea
        del fuente. Sirve de recordatorio de que las dos listas no son
        intercambiables.
        """
        lineas = self._lineas_del_fuente()
        frase = "ya en la frecuencia minima"
        self.assertIn(frase, FUENTES_PEGADAS, "deberia existir en el log")
        self.assertFalse(
            any(frase in linea for linea in lineas),
            "ahora si cabe en una linea del fuente: se puede grepear contra el "
            ".py y conviene aniadirla a CONTRA_FUENTE",
        )


class TestNadieDeclaraDependenciasSinUsarlas(unittest.TestCase):
    """El hallazgo de simple-pid, fijado desde Python.

    El Containerfile instala requirements.txt tal cual, asi que una dependencia
    declarada y no importada se instala en el nodo para no ejecutarse nunca.
    smoke_test.sh ya lo comprueba; esto lo repite aqui para que salga tambien en
    la suite, que es lo que corre generar-paquete-umbrel.sh antes de empaquetar.
    """

    MODULO_POR_PAQUETE = {
        "rich": "rich",
        "pyyaml": "yaml",
        "urllib3": "urllib3",
        "pyfiglet": "pyfiglet",
        "simple-pid": "simple_pid",
    }

    def _declarados(self):
        path = os.path.join(REPO_ROOT, "requirements.txt")
        nombres = []
        with open(path, encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.split("#")[0].strip()
                if not linea:
                    continue
                nombres.append(re.split(r"[<>=!~\[]", linea)[0].strip().lower())
        return nombres

    def test_simple_pid_no_esta_declarado(self):
        """No queda ningun PID: declararlo instalaba codigo muerto en el nodo."""
        self.assertNotIn("simple-pid", self._declarados())

    def test_nadie_importa_simple_pid(self):
        self.assertNotRegex(
            FUENTES,
            r"^\s*(import|from)\s+simple_pid\b",
            "alguien ha vuelto a importar simple_pid: hay que declararlo en "
            "requirements.txt",
        )

    def test_todo_lo_declarado_se_importa(self):
        sobra = []
        for paquete in self._declarados():
            modulo = self.MODULO_POR_PAQUETE.get(paquete)
            if modulo is None:
                continue  # paquete nuevo: aniadelo al mapa de arriba
            if not re.search(rf"^\s*(import|from)\s+{modulo}\b", FUENTES, re.M):
                sobra.append(paquete)
        self.assertEqual(sobra, [], f"declarado y no importado: {sobra}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
