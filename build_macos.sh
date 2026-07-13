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
APP_VERSION="${APP_VERSION:-1.0.1}"

if [[ ! "$APP_VERSION" =~ ^[0-9]+([.][0-9]+){1,2}$ ]]; then
  echo "Invalid APP_VERSION: $APP_VERSION (expected: 1.0 or 1.0.1)"
  exit 1
fi

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
  --collect-data customtkinter \
  --add-data "Ring10.wav:." \
  --add-data "love-emote-animal-crossing.mp3:." \
  --add-data "clock.ico:." \
  HourlyAlram.py

PLIST_PATH="dist/$APP_NAME.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$PLIST_PATH"
if ! /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $APP_VERSION" "$PLIST_PATH" 2>/dev/null; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $APP_VERSION" "$PLIST_PATH"
fi
codesign --force --deep --sign - "dist/$APP_NAME.app"

echo "Built dist/$APP_NAME.app"
