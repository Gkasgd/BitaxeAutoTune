#!/usr/bin/env python3
"""Tests de que el Logger puede escribir en un subdirectorio.

LOG_FILE y SNAPSHOT_FILE se configuran en el YAML. Para montar un volumen en un
contenedor hay que poder apuntarlos a un subdirectorio ("data/tuning.csv"), y
`Logger.__init__` abria el CSV directamente: si el directorio no existia, el
proceso moria con un FileNotFoundError que no menciona la configuracion.

Ejecutar:  python3 -m unittest tests.test_logger_directorios -v
No necesita miner ni red.
"""

import json
import os
import tempfile
import unittest

from logger import Logger


class BaseEnDirectorioTemporal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def ruta(self, *partes):
        return os.path.join(self.dir.name, *partes)


class TestCreaElDirectorio(BaseEnDirectorioTemporal):
    def test_subdirectorio_que_no_existe(self):
        csv = self.ruta("data", "tuning.csv")
        Logger(csv, self.ruta("data", "snapshot.json"))
        self.assertTrue(os.path.isdir(self.ruta("data")))
        self.assertTrue(os.path.exists(csv), "el CSV deberia estar creado")

    def test_varios_niveles(self):
        csv = self.ruta("a", "b", "c", "tuning.csv")
        Logger(csv, self.ruta("a", "b", "c", "snapshot.json"))
        self.assertTrue(os.path.exists(csv))

    def test_directorios_distintos_para_csv_y_snapshot(self):
        Logger(self.ruta("uno", "t.csv"), self.ruta("dos", "s.json"))
        self.assertTrue(os.path.isdir(self.ruta("uno")))
        self.assertTrue(os.path.isdir(self.ruta("dos")))

    def test_el_snapshot_se_puede_escribir(self):
        """Crear el directorio no sirve de nada si luego el guardado falla."""
        snap = self.ruta("data", "snapshot.json")
        log = Logger(self.ruta("data", "tuning.csv"), snap)
        log.save_snapshot(voltage=1100, frequency=450)
        with open(snap) as fh:
            self.assertEqual(json.load(fh), {"voltage": 1100, "frequency": 450})


class TestNoRompeElUsoDeSiempre(BaseEnDirectorioTemporal):
    def test_ruta_plana(self):
        """Sin directorio en la ruta, el comportamiento es el de antes."""
        cwd = os.getcwd()
        os.chdir(self.dir.name)
        self.addCleanup(os.chdir, cwd)
        Logger("tuning.csv", "snapshot.json")
        self.assertTrue(os.path.exists(self.ruta("tuning.csv")))

    def test_directorio_existente_se_reutiliza(self):
        os.makedirs(self.ruta("data"))
        with open(self.ruta("data", "tuning.csv"), "w") as fh:
            fh.write("cabecera,previa\n")
        Logger(self.ruta("data", "tuning.csv"), self.ruta("data", "s.json"))
        with open(self.ruta("data", "tuning.csv")) as fh:
            self.assertEqual(
                fh.read(), "cabecera,previa\n", "no debe pisar un CSV existente"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
