# 시간 알림 프로그램

매 시간 정각과 30분에 각각 원하는 알림음을 재생하고 데스크톱 알림을 표시하는 프로그램입니다.

## 주요 기능

1. **모던 GUI 인터페이스**: `customtkinter` 기반 라이트/다크 모드 디자인
2. **백그라운드 실행**: Windows는 시스템 트레이, macOS는 메뉴바 상태 아이콘으로 실행 가능
3. **자동 시작 설정**: Windows 시작 또는 macOS 로그인 시 자동 실행 On/Off
4. **정각 알림**: On/Off 및 전용 알림음 변경 가능 (기본 `Ring10.wav`)
5. **30분 알림**: On/Off 및 전용 알림음 변경 가능 (기본 `love-emote-animal-crossing.mp3`)
6. **설정 저장**: 알림 상태와 선택한 음원을 재실행 후에도 유지
7. **데스크톱 알림**: 정각과 30분마다 현재 시각 메시지 표시

## Python으로 실행

1. 필요한 패키지 설치:
```bash
pip install -r requirements.txt
```

macOS에서 Homebrew Python에 `tkinter`가 없으면 `python-tk` 패키지가 필요합니다. `build_macos.sh`는 가능한 경우 `python3.13`을 우선 사용하고, Python 3.13에 Tk가 없으면 `/usr/bin/python3`처럼 Tk가 포함된 Python으로 대체합니다.

2. Ring10.wav와 love-emote-animal-crossing.mp3 파일을 프로그램과 같은 폴더에 배치
   (없으면 다른 오디오 파일을 선택할 수 있습니다)

## 사용 방법

1. 프로그램 실행:
```bash
python HourlyAlram.py
```

2. GUI에서 설정:
   - 정각 알림과 30분 알림 스위치로 각각 On/Off
   - "컴퓨터 시작 시 자동 실행" 스위치로 자동 시작 설정
   - 각 알림 카드의 "소리 변경" 버튼으로 개별 알림음 변경
   - "미리 듣기" 버튼으로 선택한 알림음 확인
   - Windows는 "시스템 트레이로 최소화", macOS는 "창 숨기기" 버튼으로 백그라운드 실행

3. 백그라운드 아이콘에서:
   - Windows는 시스템 트레이, macOS는 메뉴바 아이콘에서 창 표시 또는 종료 선택

## macOS 앱으로 빌드

macOS에서 `.app` 파일을 만들려면 아래 명령을 실행합니다.

```bash
./build_macos.sh
```

빌드가 끝나면 `dist/HourlyAlarm.app`이 생성됩니다. Python 3.13이 설치되어 있고 `python-tk@3.13`이 준비되어 있으면 `.venv-macos-3.13` 환경으로 빌드됩니다.

```bash
open dist/HourlyAlarm.app
```

macOS에서 "Mac 로그인 시 자동 실행"을 켜면 `~/Library/LaunchAgents/com.kyo.hourlyalarm.plist`가 생성됩니다.

macOS에서는 실행 시 Dock과 메뉴바 상태 아이콘에 함께 표시됩니다. "창 숨기기"를 누르면 Dock에서는 사라지고 메뉴바 아이콘은 유지됩니다. 메뉴바 아이콘을 두 번 클릭하면 창이 다시 보이고, 오른쪽 클릭하면 "화면보기"와 "종료" 메뉴를 사용할 수 있습니다.

실행 시 macOS 알림 권한과 배너 표시 상태를 확인합니다. 알림 권한이 없으면 앱에서 허용 여부를 먼저 묻고, 이미 거부되었거나 배너 표시가 꺼져 있으면 알림 설정 화면으로 이동할 수 있도록 안내합니다.

## macOS DMG 배포 파일 만들기

다른 Mac 사용자에게 공유할 설치용 DMG 파일은 아래 명령 하나로 만듭니다.

```bash
./build_dmg.sh
```

스크립트는 실행할 때마다 현재 소스로 macOS 앱을 새로 빌드한 후 코드 서명 구조와 DMG 무결성을 검사합니다. 따라서 프로그램, 음원 또는 의존성을 수정한 뒤에도 같은 명령을 다시 실행하면 최신 내용이 반영됩니다.

버전 번호를 지정하려면 첫 번째 인수로 전달합니다.

```bash
./build_dmg.sh 1.1.0
```

빌드가 끝나면 아래 두 파일이 생성됩니다.

- `release/HourlyAlarm-1.1.0-macos-$(uname -m).dmg`
- `release/HourlyAlarm-1.1.0-macos-$(uname -m).dmg.sha256`

버전을 생략하면 현재 버전인 `1.0.1`을 사용합니다. 환경 변수 방식인 `VERSION=1.1.0 ./build_dmg.sh`도 지원합니다. DMG를 열면 `HourlyAlarm.app`과 `Applications` 바로가기가 보이고, 사용자는 앱을 `Applications`로 드래그해서 설치하면 됩니다.

Apple Developer ID로 코드 서명과 공증을 하지 않은 상태에서는 처음 실행할 때 macOS가 "확인되지 않은 개발자" 경고를 표시할 수 있습니다. 일반 배포에서 이 경고까지 없애려면 Apple Developer Program 가입 후 Developer ID 서명과 notarization 과정이 필요합니다.

## 요구사항

- Python 3.7 이상
- Windows 10/11 또는 macOS
- 오디오 파일 (WAV, MP3, OGG 형식 지원)

## 라이센스

MIT License
