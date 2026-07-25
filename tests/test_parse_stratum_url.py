#!/usr/bin/env python3
"""Tests de parse_stratum_url, la unica implementacion del parseo de endpoints.

Antes habia dos parseadores incompatibles (parse_stratum_url en bitaxepid.py y
parse_endpoint en pools.py). Al unificarlos hubo que elegir una semantica; este
fichero la fija por escrito para que no vuelva a divergir.

Ejecutar:  python3 -m unittest test_parse_stratum_url -v
No necesita miner ni red: parse_stratum_url no abre conexiones.
"""

import unittest

from pools import parse_stratum_url


class TestFormatosValidos(unittest.TestCase):
    def test_con_esquema(self):
        self.assertEqual(
            parse_stratum_url("stratum+tcp://solo.ckpool.org:3333"),
            {"hostname": "solo.ckpool.org", "port": 3333},
        )

    def test_sin_esquema(self):
        """Tolerancia heredada de pools.py: si falta el esquema, se asume."""
        self.assertEqual(
            parse_stratum_url("solo.ckpool.org:3333"),
            {"hostname": "solo.ckpool.org", "port": 3333},
        )

    def test_ip_literal(self):
        self.assertEqual(
            parse_stratum_url("stratum+tcp://192.168.1.10:3333"),
            {"hostname": "192.168.1.10", "port": 3333},
        )

    def test_ipv6_entre_corchetes(self):
        """El parseador antiguo de pools.py partia por el primer ':' y rompia
        las direcciones IPv6. urlparse las maneja bien."""
        self.assertEqual(
            parse_stratum_url("stratum+tcp://[2001:db8::1]:3333"),
            {"hostname": "2001:db8::1", "port": 3333},
        )

    def test_espacios_alrededor(self):
        self.assertEqual(
            parse_stratum_url("  stratum+tcp://host.example.com:3333  "),
            {"hostname": "host.example.com", "port": 3333},
        )


class TestNormalizacion(unittest.TestCase):
    def test_hostname_a_minusculas(self):
        """Los nombres de host no distinguen mayusculas; normalizarlos evita
        que el mismo pool parezca dos pools distintos."""
        self.assertEqual(
            parse_stratum_url("stratum+tcp://Pool.Example.COM:3333")["hostname"],
            "pool.example.com",
        )

    def test_descarta_userinfo(self):
        """"user@host" -> "host". El usuario stratum se configura aparte, en
        user.yaml o por CLI; no se toma del endpoint."""
        self.assertEqual(
            parse_stratum_url("stratum+tcp://user@host.example.com:3333"),
            {"hostname": "host.example.com", "port": 3333},
        )

    def test_descarta_ruta(self):
        self.assertEqual(
            parse_stratum_url("stratum+tcp://host.example.com:3333/algo"),
            {"hostname": "host.example.com", "port": 3333},
        )


class TestRechazos(unittest.TestCase):
    def test_sin_puerto(self):
        with self.assertRaises(ValueError):
            parse_stratum_url("stratum+tcp://solo.ckpool.org")

    def test_esquema_incorrecto(self):
        with self.assertRaises(ValueError):
            parse_stratum_url("tcp://host:3333")

    def test_esquema_http(self):
        with self.assertRaises(ValueError):
            parse_stratum_url("http://host:3333")

    def test_puerto_no_numerico(self):
        with self.assertRaises(ValueError):
            parse_stratum_url("stratum+tcp://host:abc")

    def test_puerto_fuera_de_rango(self):
        """El parseador antiguo de pools.py aceptaba 99999 sin quejarse y el
        error aparecia mas tarde, al intentar conectar."""
        with self.assertRaises(ValueError):
            parse_stratum_url("stratum+tcp://host:99999")

    def test_puerto_negativo(self):
        with self.assertRaises(ValueError):
            parse_stratum_url("stratum+tcp://host:-1")

    def test_cadena_vacia(self):
        with self.assertRaises(ValueError):
            parse_stratum_url("")

    def test_solo_hostname(self):
        with self.assertRaises(ValueError):
            parse_stratum_url("solo.ckpool.org")


class TestEndpointsDelRepo(unittest.TestCase):
    """Todos los endpoints de pools.yaml deben parsear sin excepciones: es el
    fichero que el programa lee en cada arranque."""

    def test_pools_yaml(self):
        import os

        import yaml

        # pools.yaml vive en la raiz del repo, un nivel por encima de tests/
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "pools.yaml")
        self.assertTrue(os.path.exists(path), f"no se encontro {path}")
        with open(path) as fh:
            pools = yaml.safe_load(fh) or []
        self.assertTrue(pools, "pools.yaml esta vacio")
        for pool in pools:
            endpoint = pool.get("endpoint")
            self.assertIsNotNone(endpoint, f"pool sin endpoint: {pool}")
            with self.subTest(endpoint=endpoint):
                result = parse_stratum_url(endpoint)
                self.assertIsInstance(result["port"], int)
                self.assertTrue(result["hostname"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
