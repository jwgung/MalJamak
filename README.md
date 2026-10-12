# Voice Keyboard

트레이에 숨어서 도는 음성 입력기 겸 실시간 번역 자막.

- **음성 입력**: 단축키를 누르고 말하면 지금 커서가 있는 입력창(Discord, 게임 채팅, 메신저 …)에 글자가 들어간다.
- **번역 자막**: PC에서 나는 소리(영어·일본어·중국어)를 한국어 자막으로 화면 위에 띄운다.
- 음성 인식 엔진은 정식 Google Chrome 에 내장된 구글 음성 인식(무료). Chrome 은 창 없이(headless) 뒤에서 돈다.
- Groq API 키를 넣으면 확정된 문장만 Groq LLM 으로 교정(리액트 → React)하고 번역한다. 없어도 동작한다.

## 현장 자막 (청각장애인용 실시간 자막)

문자통역사가 듣고 타이핑하던 일을 STT 가 초안으로 대신 쓰고, 조작자는 검토·수정해 내보낸다.

1. 트레이 메뉴 → **현장 자막 (교정 화면)** 을 연다. 설정에서 소리 입력(믹서 출력을 받는 USB 오디오 인터페이스나 마이크)을 고른다.
2. **자막 화면 열기** → 창을 프로젝터 모니터로 옮기고 더블클릭하면 전체 화면.
3. **자막 시작**. 말이 문장 끝·잠깐 멈춤·어미("~다, ~요, ~고, ~는데") 같은 자연스러운 곳에서 조각으로 잘려 대기열에 쌓인다.
   - `Enter` 내보내기(고친 내용 포함) · `Esc` 버리기 · `↑↓` 이동 · `Ctrl+Enter` 대기 중 모두 내보내기
   - 검토 방식: **자동 내보내기**(카운트다운 후 자동, 고치기 시작하면 멈춤) 또는 **승인해야 내보내기**
   - 이미 내보낸 조각도 고칠 수 있고 자막 화면에 그 자리에서 반영된다.
4. 내보낸 자막은 시간과 함께 설정 폴더의 `transcripts/자막_<날짜>.txt` 에 저장된다.

믹서 출력을 PC에 직접 넣으면 공간 마이크보다 정확하다. 이때 "통화용 보정"은 끈다.

**테스트 소리**: 마이크 없이 시험하려면 교정 화면의 "테스트 소리"에 유튜브 링크와 시작 위치(예: `5:00`)를 넣고 불러온 뒤
"이 소리로 자막 시작"을 켠 채 자막을 시작한다. 영상 소리를 받아(설정 폴더 `test-audio/`에 캐시) 엔진이 재생하며 인식하고,
교정 화면에서도 같은 소리가 재생된다. 시험용 기능이다.

## 구조

```
트레이 앱 (main.py)
 ├─ 로컬 서버 localhost:8765 ─ 설정 화면(/settings), 엔진 페이지(/engine)
 ├─ 숨긴 Chrome ─ engine.html: 마이크/시스템 소리 → 구글 음성 인식 → 확정 문장
 ├─ 붙여넣기 ─ 확정 문장(→ Groq 교정) → 포커스된 창에 Ctrl/Cmd+V
 ├─ 시스템 소리 캡처 ─ 스피커 출력(loopback) → 엔진 (자막용)
 └─ 자막 창 ─ 항상 위의 반투명 창 (별도 프로세스)
```

## 설치 (Windows)

[Releases](https://github.com/jwgung/voice-keyboard/releases)에서 `VoiceKeyboard-Setup-<버전>.exe`를 받아 실행한다.
관리자 권한 없이 `%LOCALAPPDATA%\Programs\VoiceKeyboard`에 설치되고 시작 메뉴에 바로가기가 생긴다.
코드 서명이 없어 SmartScreen 경고가 뜨면 "추가 정보 → 실행".

## 소스에서 실행

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

트레이 아이콘 색: 주황 엔진 준비 중 · 회색 대기 · 빨강 듣는 중 · 파랑 자막 중.
아이콘 클릭(또는 메뉴 → 설정)으로 설정 화면이 브라우저에 열린다.

- 음성 입력: 기본 `Ctrl+Alt+Space` (설정에서 변경, "누르고 있는 동안만" 방식 선택 가능)
- 자막: 트레이 메뉴 → 자막 켜기. 자막 창은 드래그로 이동, 더블클릭으로 원문 표시 전환.
- 외부 단축키 도구용: `curl -X POST http://localhost:8765/toggle`, `.../captions/toggle`

옵션: `--no-tray`(트레이 없이), `--dry-run`(붙여넣지 않고 출력), `--port`.
설정 파일: Windows `%APPDATA%\VoiceKeyboard\config.json`, macOS `~/Library/Application Support/VoiceKeyboard/`, Linux `~/.config/voice-keyboard/`.

## OS별 준비

공통: 정식 Google Chrome 설치 필요. 음성은 구글로 전송된다.

### Windows
- 추가 준비 없음. 관리자 권한으로 실행된 앱에 입력하려면 이 프로그램도 관리자로 실행.

### macOS
- 시스템 설정 > 개인정보 보호 및 보안 > **손쉬운 사용**, **입력 모니터링**에 이 앱(또는 터미널) 허용.
- 자막: macOS 는 스피커 출력을 바로 녹음할 수 없다. [BlackHole](https://github.com/ExistentialAudio/BlackHole) 설치 → Audio MIDI 설정에서 스피커 + BlackHole **다중 출력 장치**를 만들어 출력으로 지정 → 설정의 자막 소리 출처를 `BlackHole`로.

### Linux
- 붙여넣기: X11 `sudo apt install xdotool xclip` / Wayland `wl-clipboard` + `wtype`(wlroots) 또는 `ydotool`(GNOME/KDE).
- 단축키: X11 은 `pip install pynput` 후 사용. Wayland 는 전역 단축키를 잡을 수 없으니 OS 사용자 지정 단축키에 `curl -s -X POST http://localhost:8765/toggle` 등록.
- 트레이: GNOME 은 AppIndicator 확장이 있어야 아이콘이 보인다.
- 자막 창: `sudo apt install python3-tk` (venv 를 시스템 Python 으로 만든 경우).

## 알려진 제약

- **Chrome 내장 번역은 숨긴 엔진에서 모델을 처음 받을 수 없다** (모델 다운로드에 사용자 클릭이 필요). 지금은 자동 모드에서 Groq 로 넘어간다. Groq 키가 없으면 자막은 원문만 나온다.
- Groq 무료 한도(gpt-oss 기준 하루 1,000회·분당 30회). 자막은 문장 단위로 묶어 호출 수를 줄인다.
- 보안: 로컬 서버는 127.0.0.1 에만 열리고, 다른 웹사이트의 접속(Origin/Host 검사)을 거부한다. Groq 키는 설정 파일에 평문 저장(권한 600).
