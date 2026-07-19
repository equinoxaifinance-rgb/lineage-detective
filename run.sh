#!/usr/bin/env bash
# Lineage Detective — one-click setup + launch for macOS / Linux.  Run:  ./run.sh
set -e
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then python3 quickstart.py; else python quickstart.py; fi
