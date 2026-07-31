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


def documentos():
    """Todos los .md del arbol, no solo los tres que se revisaron a mano.

    APLICAR.md se escapo de la primera version de este fichero justamente por
    estar en un subdirectorio y sin seguimiento en git: la suite pasaba en verde
    con una frase inventada dentro. Mejor recorrer todo lo que haya.
    """
    paths = sorted(glob.glob(os.path.join(REPO_ROOT, "*.md")))
    paths += sorted(glob.glob(os.path.join(REPO_ROOT, "*", "*.md")))
    leeme = os.path.join(BUNDLE, "LEEME.md")
    if os.path.exists(leeme):
        paths.append(leeme)
    # docs/ suele traer material de upstream que no describe este fork.
    return [p for p in paths if os.sep + "docs" + os.sep not in p]


# Marcas de que el texto DESMIENTE la frase citada, en vez de mandar buscarla.
#
# Cuidado al ampliar esta lista: tiene que seguir dando False sobre el texto que
# tenia APLICAR.md antes del arreglo, y lo comprueba
# TestLaExcepcionNoEsDemasiadoAncha. Una marca como "ya no" no vale, porque
# aparece dentro de la propia frase inventada ("el voltaje ya no puede bajar").
# Ojo con los acentos: el codigo va sin ellos y el Markdown con ellos, asi que
# cada marca se declara en las dos formas o se recorta antes del acento.
MARCAS_EXPLICATIVAS = (
    "no existe en ning",  # ningun / ningún
    "no existe en el c",  # codigo / código
    "**no existe**",
    "no est",  # no estan / no están en ningun .py
    "no lo emite",
    "no escribe",
    "se quit",  # se quito, se quitaron
    "promet",  # prometia
    "invent",
    "al rev",  # al reves de como decia
    "documento hist",  # historico / histórico
    "vac",  # vacio / vacío siempre
    "ni antes ni ahora",
)


def explicativo(contenido, pos, ventana=400):
    """True si alrededor de pos se explica que la frase no existe.

    Sin esto el test prohibiria hablar del fallo, que es justo lo que el LEEME y
    el propio APLICAR.md tienen que hacer para explicarlo.
    """
    trozo = contenido[max(0, pos - ventana) : pos + ventana].lower()
    return any(m in trozo for m in MARCAS_EXPLICATIVAS)


def contexto(contenido, pos, ancho=90):
    """Un trozo corto para el mensaje de fallo, sin volcar el fichero entero."""
    return contenido[max(0, pos - ancho // 2) : pos + ancho].replace("\n", " ")


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
        """El fallo real: UMBREL.md mandaba buscar los tres primeros.

        Mencionarlos para explicar que se quitaron es legitimo, y el LEEME lo
        hace en el hallazgo 13. Lo que no vale es presentarlos como algo que el
        usuario vera en el log.
        """
        for path in documentos():
            with open(path, encoding="utf-8") as fh:
                contenido = fh.read()
            nombre = os.path.relpath(path, REPO_ROOT)
            for texto in self.FANTASMAS:
                desde = 0
                while (i := contenido.find(texto, desde)) != -1:
                    desde = i + 1
                    if explicativo(contenido, i):
                        continue
                    self.fail(
                        f"{nombre} cita '{texto}' como algo que se vera en el "
                        f"log, y el programa no lo emite: el grep saldria "
                        f"vacio. Contexto: ...{contexto(contenido, i)}..."
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


class TestNingunDocumentoInventaMensajes(unittest.TestCase):
    """El caso de APLICAR.md, generalizado a todos los .md.

    Ese documento mandaba buscar en el log "el voltaje ya no puede bajar sin
    pasarse del ...% de errores". La frase no existe ni existio nunca en ningun
    .py. Y catorce lineas mas abajo ofrecia un `git revert` de cuatro commits,
    asi que la conclusion falsa ("el arreglo no esta") llevaba derecha a la
    accion destructiva sobre un miner encendido.

    Se escapo de la primera version de este fichero porque solo miraba
    README.md, UMBREL.md y LEEME.md: la suite pasaba en verde con el error
    dentro. Ahora se recorre todo .md y se comprueban las frases que parecen
    mensajes del programa.
    """

    # Fragmentos que delatan una cita de mensaje: si un .md los contiene, la
    # frase de alrededor tiene que existir en el codigo.
    SENAS = (
        "Bajando frecuencia",
        "Bajando voltaje",
        "Subiendo voltaje",
        "RAMPA:",
        "BUSCAR_VOLTAJE:",
        "OPTIMIZAR:",
        "Ajuste cambiado fuera del tuner",
        "Estable en",
    )

    # Coletillas concretas que estuvieron citadas y nunca existieron.
    INVENTADAS = (
        "ya no puede bajar sin pasarse",
        "el voltaje ya no puede bajar",
    )

    def test_no_reaparecen_las_coletillas_inventadas(self):
        for path in documentos():
            with open(path, encoding="utf-8") as fh:
                contenido = fh.read()
            nombre = os.path.relpath(path, REPO_ROOT)
            for frase in self.INVENTADAS:
                desde = 0
                while (i := contenido.find(frase, desde)) != -1:
                    desde = i + 1
                    if explicativo(contenido, i):
                        continue  # se menciona para desmentirla
                    self.fail(
                        f"{nombre} cita '{frase}', que no existe en ningun .py: "
                        f"el grep saldria vacio siempre. "
                        f"Contexto: ...{contexto(contenido, i)}..."
                    )

    def test_las_coletillas_inventadas_siguen_sin_existir(self):
        """Si alguna se implementara, habria que sacarla de INVENTADAS."""
        for frase in self.INVENTADAS:
            self.assertNotIn(
                frase,
                FUENTES_PEGADAS,
                f"'{frase}' ya existe en el codigo: quitala de INVENTADAS y "
                "la documentacion puede citarla",
            )

    def test_lo_que_parece_un_mensaje_existe(self):
        """Toda seña citada en un .md tiene que salir tambien del codigo."""
        for path in documentos():
            with open(path, encoding="utf-8") as fh:
                contenido = fh.read()
            for sena in self.SENAS:
                if sena in contenido:
                    self.assertIn(
                        sena,
                        FUENTES_PEGADAS,
                        f"{os.path.relpath(path, REPO_ROOT)} cita '{sena}' y el "
                        "codigo no lo emite",
                    )


class TestLaExcepcionNoEsDemasiadoAncha(unittest.TestCase):
    """Que `explicativo()` no acabe tapando el fallo que debe cazar.

    La primera version de MARCAS_EXPLICATIVAS incluia "ya no", y esa cadena esta
    DENTRO de la frase inventada ("el voltaje ya no puede bajar"), asi que daba
    por explicativo el texto original y el test pasaba en verde sobre el propio
    fallo. Este caso lo fija con el texto tal y como estaba.
    """

    # Copia literal de parches-estabilidad/APLICAR.md:83-84 antes del arreglo.
    TEXTO_DEL_FALLO = (
        "- Al pasarse de `TARGET_TEMP`: `Bajando voltaje a ...mV por "
        "temperatura ...`, y\n  solo cuando el voltaje ya no tiene sitio, "
        "`Bajando frecuencia a ...MHz ... (el\n  voltaje ya no puede bajar sin "
        "pasarse del ...% de errores)`.\n"
    )

    def test_el_texto_original_no_cuenta_como_explicativo(self):
        pos = self.TEXTO_DEL_FALLO.find("ya no puede bajar")
        self.assertGreater(pos, -1)
        self.assertFalse(
            explicativo(self.TEXTO_DEL_FALLO, pos),
            "explicativo() da True sobre el texto que tenia el fallo: la "
            "excepcion tapa justo lo que el test tiene que cazar",
        )

    def test_el_texto_corregido_si_cuenta(self):
        path = os.path.join(REPO_ROOT, "parches-estabilidad", "APLICAR.md")
        if not os.path.exists(path):
            self.skipTest("no hay parches-estabilidad/ en este arbol")
        with open(path, encoding="utf-8") as fh:
            contenido = fh.read()
        pos = contenido.find("ya no puede bajar")
        if pos == -1:
            self.skipTest("el documento ya no menciona la frase")
        self.assertTrue(
            explicativo(contenido, pos),
            "el documento la menciona para desmentirla y el test la marca como "
            "fallo: falta una marca en MARCAS_EXPLICATIVAS",
        )

    def test_el_documento_del_fallo_falla_de_verdad(self):
        """Prueba de extremo a extremo con el texto original en un fichero."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "parches")
            os.makedirs(sub)
            malo = os.path.join(sub, "APLICAR.md")
            with open(malo, "w", encoding="utf-8") as fh:
                fh.write(self.TEXTO_DEL_FALLO)
            # Mismo recorrido que hace el test real, sobre el arbol de pruebas.
            encontrado = False
            with open(malo, encoding="utf-8") as fh:
                contenido = fh.read()
            for frase in TestNingunDocumentoInventaMensajes.INVENTADAS:
                i = contenido.find(frase)
                if i != -1 and not explicativo(contenido, i):
                    encontrado = True
            self.assertTrue(
                encontrado,
                "el texto original pasaria el filtro: el test no sirve",
            )


class TestLaPalancaTermicaSeDescribeBien(unittest.TestCase):
    """El calor baja FRECUENCIA primero; el voltaje solo en el suelo.

    APLICAR.md lo contaba al reves porque documentaba c7db4b3, que d2ef8dc
    revirtio a proposito: bajar voltaje sube los errores justo cuando el chip va
    mas forzado. Un documento que invierte el orden no es un detalle de
    redaccion, describe otro comportamiento de seguridad.
    """

    def test_el_codigo_baja_frecuencia_primero(self):
        with open(
            os.path.join(REPO_ROOT, "tuning_estabilidad.py"), encoding="utf-8"
        ) as fh:
            texto = fh.read()
        # La rama termica: if <frecuencia por encima del suelo> ... elif <voltaje>
        rama = texto.split("if temp > self.target_temp:", 1)[1][:1800]
        pos_f = rama.find("current_frequency > self.min_frequency")
        pos_v = rama.find("current_voltage > self.min_voltage")
        self.assertGreater(pos_f, -1, "no encuentro la rama de frecuencia")
        self.assertGreater(pos_v, -1, "no encuentro la rama de voltaje")
        self.assertLess(
            pos_f,
            pos_v,
            "el voltaje se comprueba antes que la frecuencia: la palanca "
            "termica se ha invertido y hay documentacion que hay que revisar",
        )

    def test_ningun_documento_dice_lo_contrario(self):
        """Cita textual del error que tenia APLICAR.md."""
        for path in documentos():
            with open(path, encoding="utf-8") as fh:
                contenido = fh.read()
            nombre = os.path.relpath(path, REPO_ROOT)
            # "Bajando voltaje ... y solo cuando ... Bajando frecuencia" es el
            # orden invertido, salvo si la frase va marcada como historica.
            if "Bajando voltaje" not in contenido:
                continue
            i_v = contenido.find("Bajando voltaje")
            i_f = contenido.find("Bajando frecuencia")
            if i_f == -1 or i_v >= i_f:
                continue
            ventana = contenido[i_v:i_f]
            if "solo cuando" not in ventana and "solo con" not in ventana:
                continue
            self.assertTrue(
                "al rev" in ventana or "hist" in ventana.lower(),
                f"{nombre} presenta el voltaje como primera reaccion al calor "
                "y la frecuencia como segunda: es el orden invertido",
            )


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
