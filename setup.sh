#!/bin/bash

# Create a virtual environment
uv venv

# Activate the virtual environment
source .venv/bin/activate

# Install required Python packages
# Las dependencias se declaran en requirements.txt (no duplicar la lista aqui)
uv pip install --requirement requirements.txt

# Deactivate the virtual environment
deactivate

