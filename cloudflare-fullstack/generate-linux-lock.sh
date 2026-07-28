#!/bin/sh
set -eu

python -m pip install --disable-pip-version-check --quiet "pip-tools==7.6.0"
export CUSTOM_COMPILE_COMMAND="docker run python:3.11-slim cloudflare-fullstack/generate-linux-lock.sh"
python -m piptools compile \
  --allow-unsafe \
  --generate-hashes \
  --output-file=requirements-datahub-sidecar-linux.lock \
  --strip-extras \
  requirements-datahub-sidecar.txt
