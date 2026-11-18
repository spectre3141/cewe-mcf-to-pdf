#!/usr/bin/env bash
# Builds dist/mcf2pdf - a single stand-alone Linux program (no Python needed to run it).
# Building needs Python 3.10+ with tkinter (Debian/Ubuntu: apt install python3-venv python3-tk).
# Tip: build on an older distro (or in a container, e.g. python:3.12-bookworm) so the
# binary also runs on older systems.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .build-venv
. .build-venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --clean --onefile --windowed \
  --name mcf2pdf \
  --add-data "$PWD/fonts:fonts" \
  mcf2pdf_gui.py

echo
echo "Done: $PWD/dist/mcf2pdf"
