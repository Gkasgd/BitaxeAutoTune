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
    parser.add_argument(
        "--ip", required=True, type=str, help="IP address of the Bitaxe miner"
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
    parser.add_argument("--voltage", type=float, help="Initial voltage override (mV)")
    parser.add_argument(
        "--frequency", type=float, help="Initial frequency override (MHz)"
    )
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
    return parser.parse_args()
