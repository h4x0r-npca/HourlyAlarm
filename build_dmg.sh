#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

APP_NAME="HourlyAlarm"
VERSION="${1:-${VERSION:-1.0.1}}"
ARCH="${ARCH:-$(uname -m)}"
APP_PATH="dist/$APP_NAME.app"
RELEASE_DIR="release"
DMG_PATH="$RELEASE_DIR/$APP_NAME-$VERSION-macos-$ARCH.dmg"
CHECKSUM_PATH="$DMG_PATH.sha256"
STAGING_DIR=""

cleanup() {
  if [[ -n "$STAGING_DIR" && -d "$STAGING_DIR" ]]; then
    rm -rf "$STAGING_DIR"
  fi
}
trap cleanup EXIT

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "오류: DMG 파일은 macOS에서만 만들 수 있습니다."
  exit 1
fi

if [[ ! "$VERSION" =~ ^[0-9A-Za-z._-]+$ ]]; then
  echo "오류: 버전에는 영문, 숫자, 점(.), 밑줄(_), 하이픈(-)만 사용할 수 있습니다."
  exit 1
fi

for command_name in hdiutil ditto codesign shasum; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "오류: 필수 macOS 도구를 찾을 수 없습니다: $command_name"
    exit 1
  fi
done

for required_file in \
  build_macos.sh \
  HourlyAlram.py \
  requirements-macos.txt \
  Ring10.wav \
  love-emote-animal-crossing.mp3 \
  clock.ico; do
  if [[ ! -f "$required_file" ]]; then
    echo "오류: 빌드에 필요한 파일이 없습니다: $required_file"
    exit 1
  fi
done

echo "[1/4] 최신 소스로 macOS 앱을 빌드합니다."
APP_VERSION="$VERSION" ./build_macos.sh

if [[ ! -x "$APP_PATH/Contents/MacOS/$APP_NAME" ]]; then
  echo "오류: 앱 실행 파일이 생성되지 않았습니다: $APP_PATH"
  exit 1
fi

echo "[2/4] 앱 번들과 코드 서명을 확인합니다."
codesign --verify --deep --strict "$APP_PATH"

mkdir -p "$RELEASE_DIR"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hourlyalarm-dmg.XXXXXX")"

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

echo "[3/4] 설치용 DMG를 생성합니다."
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "[4/4] DMG 무결성과 체크섬을 확인합니다."
hdiutil verify "$DMG_PATH"
(
  cd "$RELEASE_DIR"
  shasum -a 256 "$(basename "$DMG_PATH")" > "$(basename "$CHECKSUM_PATH")"
)

echo
echo "완료: $PROJECT_DIR/$DMG_PATH"
echo "SHA-256: $PROJECT_DIR/$CHECKSUM_PATH"
