# Use the official Python base image
FROM python:3.12-slim-bookworm

# Add metadata about the maintainer
LABEL maintainer="bitaxepid@starficient.com"

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy YAML, Python files and the banner into the container.
# banner.txt hace falta: RichTerminalUI lo abre al arrancar y sin el la TUI
# muestra "Banner file not found".
COPY *.yaml *.py banner.txt ./

# Expose port
# El servidor de metricas solo escucha si se arranca con --serve-metrics
# (o con METRICS_SERVE en la configuracion).
EXPOSE 8093

# Set the default command
#   podman build -t bitaxepid-container -f Containerfile .
#   podman run -it --publish 8093:8093 bitaxepid-container 192.168.68.111
#   podman run --publish 8093:8093 bitaxepid-container 192.168.68.111 --serve-metrics
#
# El argumento posicional de `podman run` es la IP del miner. Cualquier flag
# adicional que se pase despues se añade a la invocacion.
#
# -u: salida sin buffer, para que los logs aparezcan en `podman logs` en
# tiempo real en lugar de acumularse en el buffer de stdout.
ENTRYPOINT ["python", "-u", "./bitaxepid.py", "--logging-level", "debug", "--ip"]
