# 개발용 시험 도구

화면·사운드카드가 없는 Linux 서버(SSH)에서 앱을 검증할 때 쓴 스크립트들. 앱의 일부가 아니며 설치 파일에 들어가지 않는다.
실행은 저장소의 venv 로: `.venv/bin/python -I tools/dev/<스크립트>`.
테스트 소리·자막 비교에 쓰는 yt-dlp 는 앱 의존성에서 뺐으므로 venv 에 따로 설치한다: `pip install yt-dlp`
(설치돼 있으면 소스 실행 앱도 그것을 쓰고, 없으면 설정 폴더 `bin/` 에 실행 파일을 받는다).

## 준비물

- **Chrome**: 설치 권한이 없으면 공식 .deb 를 풀어 쓴다.
  `curl -sSLo chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && dpkg-deb -x chrome.deb chrome/`
  → `chrome/opt/google/chrome/google-chrome --no-sandbox …` (압축만 풀면 샌드박스 도우미 권한이 없어 `--no-sandbox` 필요)
- **가짜 마이크**: Chrome 인자 `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>`
  (기본 마이크 방식은 사운드카드가 없으면 `audio-capture` 오류 — 트랙 방식만 시험된다)
- **가상 스피커** (PC 소리 자막 시험):
  `pw-cli create-node adapter '{ factory.name=support.null-audio-sink node.name=vk-test-sink media.class=Audio/Sink object.linger=true audio.position=[FL FR] }'`
  → `pw-play --target vk-test-sink <wav>` 로 재생. 끝나면 `pw-cli ls Node` 로 id 를 찾아 `pw-cli destroy <id>`.

## 앱을 시험 모드로 띄우기

```sh
XDG_CONFIG_HOME=/tmp/vk-xdg \
VK_CHROME=<chrome 경로> \
VK_CHROME_ARGS="--no-sandbox --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>" \
VK_GROQ_URL=http://127.0.0.1:8797/v1/chat/completions \
.venv/bin/python main.py --no-tray --dry-run [--port 8765]
```

- `XDG_CONFIG_HOME`: 사용자 설정을 건드리지 않도록 임시 설정 폴더 (설정 파일·기록·테스트 소리 캐시가 여기 생긴다)
- `--dry-run`: 붙여넣지 않고 `[paste] …` 로 출력
- `VK_CHROME=/bin/true` 로 주면 엔진 없이 서버만 뜬다 (화면 캡처용)
- 엔진 Chrome 에 디버거를 붙이려면 `VK_CHROME_ARGS` 에 `--remote-debugging-port=9335` 추가

## 스크립트

| 파일 | 하는 일 |
|---|---|
| `mock_groq.py` | 가짜 Groq 서버(127.0.0.1:8797). 교정은 `[FIX] …`, 번역은 `[KO] …` 로 돌려주고 받은 지시문 첫 줄을 `PROMPT1` 로 찍는다. Whisper 받아쓰기(`/v1/audio/transcriptions`)는 받은 토막 길이를 `[STT n] 6.2초 ko` 로 돌려준다 (`VK_GROQ_STT_URL=http://127.0.0.1:8797/v1/audio/transcriptions`) |
| `cdp_eval.py` | `cdp_eval.py <devtools 포트> <언어> <대기초> <js 파일>` — 열린 페이지에서 JS 를 실행하고 console 을 시간과 함께 출력 (userGesture 포함) |
| `cdp_screenshot.py` | `cdp_screenshot.py <devtools 포트> <URL> <out.png> <폭> <높이> [js 파일]` — 페이지를 열고(선택: JS 주입) 캡처. `DARK=1` 이면 어두운 테마 |
| `engine_watch.py` | `engine_watch.py <초> <out.tsv>` — 엔진 페이지에 붙어 `window.VK_DEBUG = true` 를 켜고 순차통역 진단 로그(세션 열림·원본 결과·소리 크기)를 모은다. 포트는 `VK_ENGINE_DEVTOOLS`(기본 9335) |
| `interp_run.py` | `interp_run.py <유튜브 URL> <초> <out.json> [포트]` — 교정 화면 역할로 붙어 테스트 소리를 불러와 3:00 부터 순차통역 자막을 돌리고 조각·원어 줄을 저장 |
| `dual_run.py` | `dual_run.py <유튜브 URL> <초> <out.json> [포트]` — 이중 STT(dual) 시험: 번역/통역 조각을 차례별로 모은다(조작자 선택 없음). `items` 는 통역 쪽이라 `score_live.py` 로 채점된다 |
| `score_live.py` | `score_live.py <out.json> <자막.json3> <시작초> <끝초> [-v]` — 결과를 유튜브 자동 자막과 비교(한글 일치율) |
| `live_client.py` | 현장 자막 자동/승인 흐름 시험(조각 크기·간격, 수정·버리기·나간 뒤 수정) |
| `op_pace.js` | 교정 화면에 `cdp_eval.py` 로 주입 — 시작 → `Ctrl+Space` 멈춤(나간 수가 그대로인지) → 대기 3번째에서 `Ctrl+Enter`(+3 나가는지) → 다시 흐르기 확인 |
| `compare_captions.py` | Chrome 인식 로그(FINAL 줄)와 유튜브 자막의 일치율·다른 구간 목록 |

유튜브 자동 자막(비교 기준)은 yt-dlp 로 받는다:
`yt-dlp --skip-download --write-auto-subs --sub-langs ko-orig --sub-format json3 -o subs <URL>`

## 함정

- 이 서버에서는 **127.0.0.1:9333 을 adb 가 쓰고 있다**. 그 포트로 Chrome 디버깅을 열면 Chrome 은 `::1` 에만 열린다 → `localhost`/`[::1]` 로 붙거나 다른 포트를 쓴다.
- `pkill -f <패턴>` 은 그 패턴이 들어 있는 셸 명령 자신도 죽인다. 띄운 프로세스의 PID 를 기록해 `kill` 할 것.
- 헤드리스 Chrome 의 첫 페이지가 about:blank 로 남는 경우가 있다. 페이지를 연 뒤 `location.href = …` 로 한 번 더 연다.
- 엔진·교정 화면 시험을 동시에 여러 개 돌릴 때는 앱 포트(`--port`)·devtools 포트·`XDG_CONFIG_HOME`·Chrome 프로필을 모두 따로 쓴다.
