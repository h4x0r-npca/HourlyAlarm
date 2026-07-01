#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if command -v python3.13 >/dev/null 2>&1 && python3.13 -c "import tkinter" >/dev/null 2>&1; then
    PYTHON_BIN="python3.13"
  elif [[ "$(uname -s)" == "Darwin" ]] && /usr/bin/python3 -c "import tkinter" >/dev/null 2>&1; then
    PYTHON_BIN="/usr/bin/python3"
  else
    PYTHON_BIN="python3"
  fi
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
VENV_DIR="${VENV_DIR:-.venv-macos-$PY_VERSION}"
APP_NAME="HourlyAlarm"
BUNDLE_ID="com.kyo.hourlyalarm"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements-macos.txt

"$VENV_DIR/bin/python" scripts/create_macos_icon.py

"$VENV_DIR/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --icon assets/HourlyAlarm.icns \
  --add-data "Ring10.wav:." \
  --add-data "clock.ico:." \
  HourlyAlram.py

echo "Built dist/$APP_NAME.app"
