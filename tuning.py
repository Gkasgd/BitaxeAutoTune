#!/usr/bin/env python3
"""
Estrategia de tuning PID para el voltaje y la frecuencia del miner.

Recibe el estado actual (voltaje, frecuencia, temperatura, hashrate, potencia) y
devuelve el siguiente par voltaje/frecuencia a aplicar. Dos controladores PID
persiguen el setpoint de hashrate, pero por delante de ellos manda la seguridad:
si la temperatura o la potencia se pasan del limite, se baja aunque el hashrate
quede corto. Cada decision se explica por pantalla, porque es la unica forma que
tiene el usuario de entender por que el tuner sube o baja.

Uso:
    from tuning import PIDTuningStrategy

    strategy = PIDTuningStrategy(kp_freq=..., ki_freq=..., ...)
    new_voltage, new_frequency = strategy.apply_strategy(
        current_voltage, current_frequency, temp, hashrate, power
    )

Dependencias:
    - Terceros: simple_pid, rich (a traves de ui_rich, para los mensajes)
    - Estandar: typing
"""

from typing import Optional, Tuple

from simple_pid import PID

from interfaces import TuningStrategy
from ui_rich import (
    PRIMARY_ACCENT,
    SECONDARY_ACCENT,
    WARNING_COLOR,
    console,
)


class PIDTuningStrategy(TuningStrategy):
    """Concrete implementation of a PID-based tuning strategy for miner settings."""

    def __init__(
        self,
        kp_freq: float,
        ki_freq: float,
        kd_freq: float,
        kp_volt: float,
        ki_volt: float,
        kd_volt: float,
        min_voltage: float,
        max_voltage: float,
        min_frequency: float,
        max_frequency: float,
        voltage_step: float,
        frequency_step: float,
        setpoint: float,
        sample_interval: float,
        target_temp: float,
        power_limit: float,
    ) -> None:
        """
        Initialize the PID tuning strategy with control parameters.
        Args:
            kp_freq (float): Proportional gain for frequency PID.
            ki_freq (float): Integral gain for frequency PID.
            kd_freq (float): Derivative gain for frequency PID.
            kp_volt (float): Proportional gain for voltage PID.
            ki_volt (float): Integral gain for voltage PID.
            kd_volt (float): Derivative gain for voltage PID.
            min_voltage (float): Minimum allowed voltage (mV).
            max_voltage (float): Maximum allowed voltage (mV).
            min_frequency (float): Minimum allowed frequency (MHz).
            max_frequency (float): Maximum allowed frequency (MHz).
            voltage_step (float): Voltage adjustment step size (mV).
            frequency_step (float): Frequency adjustment step size (MHz).
            setpoint (float): Target hashrate setpoint (GH/s).
            sample_interval (float): PID sample interval (seconds).
            target_temp (float): Target temperature (°C).
            power_limit (float): Power limit (W).
        """
        self.pid_freq = PID(
            kp_freq, ki_freq, kd_freq, setpoint=setpoint, sample_time=sample_interval
        )
        self.pid_volt = PID(
            kp_volt, ki_volt, kd_volt, setpoint=setpoint, sample_time=sample_interval
        )
        self.pid_freq.output_limits = (min_frequency, max_frequency)
        self.pid_volt.output_limits = (min_voltage, max_voltage)
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.min_frequency = min_frequency
        self.max_frequency = max_frequency
        self.voltage_step = voltage_step
        self.frequency_step = frequency_step
        self.target_temp = target_temp
        self.power_limit = power_limit
        self.last_hashrate: Optional[float] = None
        self.stagnation_count = 0
        # Removed drop_count since we're not tracking hashrate drops anymore, this was an overall network factor and not addressable in the hardware.

    def apply_strategy(
        self,
        current_voltage: float,
        current_frequency: float,
        temp: float,
        hashrate: float,
        power: float,
    ) -> Tuple[float, float]:
        """
        Calculate new voltage and frequency settings based on the current miner status.
        Uses PID to maintain hashrate setpoint and reduces frequency to control temperature.
        """
        # Calculate PID outputs
        freq_output = self.pid_freq(hashrate)
        volt_output = self.pid_volt(hashrate)
        proposed_frequency = (
            round(freq_output / self.frequency_step) * self.frequency_step
        )
        proposed_frequency = max(
            self.min_frequency, min(self.max_frequency, proposed_frequency)
        )
        proposed_voltage = round(volt_output / self.voltage_step) * self.voltage_step
        proposed_voltage = max(
            self.min_voltage, min(self.max_voltage, proposed_voltage)
        )

        # Track hashrate stagnation but not drops
        stagnated = self.last_hashrate == hashrate
        self.stagnation_count = self.stagnation_count + 1 if stagnated else 0

        new_voltage = current_voltage
        new_frequency = current_frequency

        # Temperature control - reduce frequency first, then voltage if needed
        if temp > self.target_temp:
            if current_frequency > self.min_frequency:
                new_frequency = current_frequency - self.frequency_step
                console.print(
                    f"[{WARNING_COLOR}]Reducing frequency to {new_frequency}MHz due to temp {temp}°C > {self.target_temp}°C[/]"
                )
            elif current_voltage > self.min_voltage:
                new_voltage = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Reducing voltage to {new_voltage}mV due to temp {temp}°C > {self.target_temp}°C[/]"
                )
        # Power limit control
        elif power > self.power_limit * 1.075:
            if current_voltage > self.min_voltage:
                new_voltage = current_voltage - self.voltage_step
                console.print(
                    f"[{WARNING_COLOR}]Reducing voltage to {new_voltage}mV due to power {power}W > {self.power_limit * 1.075}W[/]"
                )
        # Hashrate control using PID
        elif hashrate < self.pid_freq.setpoint:
            # If hashrate is significantly low, try increasing voltage first
            if (
                hashrate < 0.85 * self.pid_freq.setpoint
                and current_voltage < self.max_voltage
            ):
                new_voltage = min(proposed_voltage, current_voltage + self.voltage_step)
                console.print(
                    f"[{SECONDARY_ACCENT}]Increasing voltage to {new_voltage}mV due to hashrate {hashrate} < {0.85 * self.pid_freq.setpoint}[/]"
                )
            # Apply PID-calculated frequency
            new_frequency = proposed_frequency
            console.print(
                f"[{SECONDARY_ACCENT}]Adjusting frequency to {new_frequency}MHz via PID[/]"
            )
            # If at max frequency but still below setpoint, increase voltage
            if (
                current_frequency >= self.max_frequency
                and current_voltage < self.max_voltage
            ):
                new_voltage = current_voltage + self.voltage_step
                console.print(
                    f"[{SECONDARY_ACCENT}]Increasing voltage to {new_voltage}mV as frequency at max[/]"
                )
        else:
            console.print(
                f"[{PRIMARY_ACCENT}]System stable at Voltage={current_voltage}mV, Frequency={new_frequency}MHz[/]"
            )

        self.last_hashrate = hashrate
        return new_voltage, new_frequency
