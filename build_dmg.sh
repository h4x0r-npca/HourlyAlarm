#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="HourlyAlarm"
VERSION="${VERSION:-1.0.0}"
ARCH="${ARCH:-$(uname -m)}"
APP_PATH="dist/$APP_NAME.app"
RELEASE_DIR="release"
DMG_PATH="$RELEASE_DIR/$APP_NAME-$VERSION-macos-$ARCH.dmg"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hourlyalarm-dmg.XXXXXX")"

cleanup() {
  rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "DMG packaging requires macOS."
  exit 1
fi

if ! command -v hdiutil >/dev/null 2>&1; then
  echo "hdiutil was not found. This script must be run on macOS."
  exit 1
fi

if [[ ! -d "$APP_PATH" || HourlyAlram.py -nt "$APP_PATH/Contents/MacOS/$APP_NAME" ]]; then
  echo "Building the macOS app first..."
  ./build_macos.sh
fi

mkdir -p "$RELEASE_DIR"

ditto "$APP_PATH" "$STAGING_DIR/$APP_NAME.app"
ln -s /Applications "$STAGING_DIR/Applications"

cat > "$STAGING_DIR/Install.txt" <<'EOF'
HourlyAlarm 설치 방법

1. HourlyAlarm.app을 Applications 폴더로 드래그하세요.
2. Applications 폴더에서 HourlyAlarm을 실행하세요.
3. 알림 권한과 배너 표시 안내가 나오면 허용하세요.

macOS가 "확인되지 않은 개발자" 경고를 표시하면 HourlyAlarm.app을
Control-클릭 또는 오른쪽 클릭한 뒤 "열기"를 선택하세요.
EOF

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

hdiutil verify "$DMG_PATH"

echo "Built $DMG_PATH"
