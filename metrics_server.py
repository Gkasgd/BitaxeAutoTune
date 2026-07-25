#!/usr/bin/env python3
"""
Servidor HTTP de metricas para Prometheus y Grafana.

Expone en http://0.0.0.0:8093/metrics un JSON con la ultima muestra de cada
miner monitorizado, identificado por su direccion MAC. Solo se arranca si se
pasa --serve-metrics o si METRICS_SERVE esta activo en la configuracion.

Uso:
    from metrics_server import start_metrics_server, update_metrics

    start_metrics_server()          # arranca el servidor en un hilo daemon
    update_metrics(mac, muestra)    # publica la ultima muestra de ese miner

Dependencias:
    - Estandar: http.server, json, logging, socketserver, threading, typing
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from threading import Lock, Thread
from typing import Any, Dict, List

METRICS_PORT = 8093

logger = logging.getLogger(__name__)

# Ultima muestra publicada por cada miner. El hilo del servidor HTTP lee esta
# lista mientras el bucle de tuning la escribe, asi que todo acceso pasa por
# _METRICS_LOCK.
_latest_metrics: List[Dict[str, Any]] = []
_METRICS_LOCK = Lock()


def update_metrics(mac_address: str, metrics: Dict[str, Any]) -> None:
    """
    Publicar la ultima muestra de un miner, sustituyendo la anterior.

    Se expone como funcion en lugar de dejar que el llamante manipule la lista
    directamente: al vivir la lista en este modulo, reasignarla desde fuera
    (global latest_metrics) no seria visible para el handler HTTP.

    Args:
        mac_address (str): MAC del miner, clave de identificacion.
        metrics (Dict[str, Any]): Muestra a publicar.
    """
    global _latest_metrics
    with _METRICS_LOCK:
        _latest_metrics = [
            m for m in _latest_metrics if m["mac_address"] != mac_address
        ]
        _latest_metrics.append(metrics)


def get_metrics() -> List[Dict[str, Any]]:
    """Devolver una copia de las muestras publicadas."""
    with _METRICS_LOCK:
        return list(_latest_metrics)


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler to serve JSON metrics for Prometheus and Grafana."""

    def do_GET(self) -> None:
        """
        Handle GET requests to the /metrics endpoint.

        Serves the latest metrics as a JSON object with a list of endpoints, otherwise returns a 404.
        """
        if self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            metrics_json = json.dumps({"endpoints": get_metrics()}).encode("utf-8")
            self.wfile.write(metrics_json)
        else:
            self.send_response(404)
            self.end_headers()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server to handle multiple requests concurrently."""

    pass


def start_metrics_server() -> None:
    """Start the HTTP server on port 8093 in a separate thread."""
    server = ThreadedHTTPServer(("0.0.0.0", METRICS_PORT), MetricsHandler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    logging.info(f"Metrics server started on http://0.0.0.0:{METRICS_PORT}/metrics")
