#!/usr/bin/env python3
"""
Interfaz de terminal nula: no dibuja nada.

Se usa con --log-to-console, cuando la salida util es el log y no una pantalla
que se redibuja. Implementa el mismo contrato que RichTerminalUI para que el
bucle de tuning no tenga que preguntar con cual esta trabajando.

Uso:
    from ui_null import NullTerminalUI

    ui = NullTerminalUI()
    ui.update(system_info, voltage, frequency)   # no hace nada

Dependencias:
    - Estandar: typing
"""

from typing import Any, Dict

from interfaces import ITerminalUI


class NullTerminalUI(ITerminalUI):
    """Null implementation of the terminal UI for console-only logging."""

    def update(
        self, system_info: Dict[str, Any], voltage: float, frequency: float
    ) -> None:
        """
        Do nothing (placeholder for UI updates).

        Args:
            system_info (Dict[str, Any]): Current system information (ignored).
            voltage (float): Current target voltage setting (mV, ignored).
            frequency (float): Current target frequency setting (MHz, ignored).
        """
        pass
