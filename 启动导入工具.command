#!/bin/bash
cd "$(dirname "$0")"
PY="/Users/yanghaoxiang/miniforge3/bin/python3"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi
exec "$PY" main.py gui
