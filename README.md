# Voice Keyboard

트레이에 숨어서 도는 음성 입력기 겸 실시간 번역 자막.

- **음성 입력**: 단축키를 누르고 말하면 지금 커서가 있는 입력창(Discord, 게임 채팅, 메신저 …)에 글자가 들어간다.
- **번역 자막**: PC에서 나는 소리(영어·일본어·중국어)를 한국어 자막으로 화면 위에 띄운다.
- 음성 인식 엔진은 정식 Google Chrome 에 내장된 구글 음성 인식(무료). Chrome 은 창 없이(headless) 뒤에서 돈다.
- Groq API 키를 넣으면 확정된 문장만 Groq LLM 으로 교정(리액트 → React)하고 번역한다. 없어도 동작한다.

## 구조

```
트레이 앱 (main.py)
 ├─ 로컬 서버 localhost:8765 ─ 설정 화면(/settings), 엔진 페이지(/engine)
 ├─ 숨긴 Chrome ─ engine.html: 마이크/시스템 소리 → 구글 음성 인식 → 확정 문장
 ├─ 붙여넣기 ─ 확정 문장(→ Groq 교정) → 포커스된 창에 Ctrl/Cmd+V
 ├─ 시스템 소리 캡처 ─ 스피커 출력(loopback) → 엔진 (자막용)
 └─ 자막 창 ─ 항상 위의 반투명 창 (별도 프로세스)
```

## 실행

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
