#!/usr/bin/env python3
"""
Interfaz de linea de comandos de BitaxePID.

Define las opciones aceptadas y su ayuda. Los valores que aqui se recogen se
aplican por encima de la configuracion cargada de los YAML (ver config.py):
la precedencia es CLI > YAML de usuario > YAML del modelo de ASIC.

Uso:
    from cli import parse_arguments

    args = parse_arguments()

Dependencias:
    - Estandar: argparse
"""

import argparse

__version__ = "1.0.3"  # add connection pool for reuse to bitaxe.


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments for the BitaxePID tuner.

    Returns:
        argparse.Namespace: Parsed arguments with command-line options.

    Example:
        >>> args = parse_arguments()  # Run with: python bitaxepid.py --ip 192.168.1.1 --serve-metrics
        >>> args.ip
        '192.168.1.1'
        >>> args.serve_metrics
        True
    """
    parser = argparse.ArgumentParser(description="BitaxePID Auto-Tuner")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    # --ip deja de ser obligatorio SOLO con --dry-run, que no abre ninguna
    # conexion. La comprobacion se hace despues de parsear, para poder dar el
    # mismo error de argparse ("--ip es obligatorio") en el resto de los casos.
    parser.add_argument(
        "--ip", type=str, help="IP address of the Bitaxe miner"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Cargar y validar la configuracion, imprimirla con el fichero del "
            "que sale cada clave, y salir sin conectar con ningun miner. "
            "Necesita --asic, porque el modelo se lee del miner y aqui no se "
            "consulta"
        ),
    )
    parser.add_argument(
        "--asic",
        type=str,
        choices=["BM1366", "BM1368", "BM1370", "BM1397"],
        help=(
            "Modelo de ASIC para --dry-run. En una ejecucion normal no se usa: "
            "el modelo lo reporta el propio miner"
        ),
    )
    parser.add_argument(
        "--config", type=str, help="Path to optional user YAML configuration file"
    )
    parser.add_argument(
        "--user-file",
        type=str,
        default=None,
        help="Path to user YAML file (default: from config)",
    )
    parser.add_argument(
        "--pools-file",
        type=str,
        default=None,
        help="Path to pools YAML file (default: from config)",
    )
    parser.add_argument(
        "--primary-stratum",
        type=str,
        help="Primary stratum URL (e.g., stratum+tcp://host:port)",
    )
    parser.add_argument(
        "--backup-stratum",
        type=str,
        help="Backup stratum URL (e.g., stratum+tcp://host:port)",
    )
    parser.add_argument(
        "--stratum-user", type=str, help="Stratum user for primary pool"
    )
    parser.add_argument(
        "--fallback-stratum-user", type=str, help="Stratum user for backup pool"
    )
    # Enteros, no float: son mV y MHz que se escriben en el hardware y AxeOS no
    # aplica fracciones. Aceptar "--frequency 493.75" solo conseguia meter un
    # decimal que la estrategia arrastra sumandole pasos enteros el resto de la
    # ejecucion (493.75, 498.75, 503.75...). Con type=int argparse lo rechaza en
    # el momento, que es donde el usuario puede corregirlo.
    parser.add_argument("--voltage", type=int, help="Initial voltage override (mV)")
    parser.add_argument("--frequency", type=int, help="Initial frequency override (MHz)")
    parser.add_argument(
        "--sample-interval", type=float, help="Sample interval override (seconds)"
    )
    parser.add_argument(
        "--log-to-console", action="store_true", help="Log to console instead of UI"
    )
    parser.add_argument(
        "--logging-level",
        type=str,
        choices=["info", "debug"],
        default="info",
        help="Logging level",
    )
    parser.add_argument(
        "--serve-metrics",
        action="store_true",
        help="Serve metrics via HTTP on port 8093 (default: False)",
    )
    parser.add_argument(
        "--manage-pools",
        action="store_true",
        help=(
            "Permitir que BitaxePID reconfigure los pools stratum del miner y "
            "lo reinicie al arrancar (default: False, no se toca la "
            "configuracion de pools existente)"
        ),
    )
    args = parser.parse_args()

    # --ip era required=True. Lo sigue siendo en la practica, salvo con
    # --dry-run: pedir una IP para un modo que promete no abrir ninguna conexion
    # obligaria a inventarse una, y quien la lea en el historial no sabria que no
    # se uso. La comprobacion se hace aqui, con parser.error, para que el mensaje
    # y el codigo de salida (2) sean los mismos que daba argparse.
    if not args.dry_run and not args.ip:
        parser.error(
            "--ip es obligatorio (salvo con --dry-run, que no conecta con "
            "ningun miner)"
        )

    # El modelo de ASIC lo reporta el propio miner, y de ahi sale el YAML base.
    # Sin miner al que preguntar no hay forma de adivinarlo, y elegir uno por
    # omision seria peor: validaria la configuracion contra los limites de otro
    # chip y diria que todo esta bien.
    if args.dry_run and not args.asic:
        parser.error(
            "--dry-run necesita --asic MODELO: el modelo de chip lo reporta el "
            "miner, y en --dry-run no se consulta a ninguno"
        )
    if args.asic and not args.dry_run:
        parser.error(
            "--asic solo tiene sentido con --dry-run: en una ejecucion normal el "
            "modelo se lee del miner y este valor se ignoraria en silencio"
        )

    return args
