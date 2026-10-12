# 작업 기록 (2026-10-12)

다음 작업자가 이어받을 수 있게 하루 동안의 결정, 검증 결과, 남은 과제를 정리한다. 기능 설명과 사용법은 [README](../README.md)에 있다.

## 목적 (사용자 결정)

1. **PC용 범용 STT** — 단축키를 누르고 말하면 포커스된 입력창에 들어간다.
2. **청각장애인용 현장 자막** — 문자통역사가 하던 타이핑을 STT 가 초안으로 대신 쓰고, 조작자가 조각을 검토·수정해 내보내면 프로젝터에 큰 자막으로 뜬다. 교회 설교가 주 사용처.
   - 화면: 같은 PC 화면이나 프로젝터 · 교정: PC 조작자가 직접 · 소리: 현장 마이크(믹서 출력을 PC에 직접 넣을 수도 있음)
   - 자막은 틀릴 수 있지만 사람이 고칠 수 있어야 한다. 문장이 통째로 빠지는 것이 오인식보다 나쁘다.
   - 검토 방식은 자동 내보내기(카운트다운)와 승인 방식 둘 다 설정으로.

## 버전 흐름

| 버전 | 내용 |
|---|---|
| v0.1.1 | 트레이 앱 + 숨긴 Chrome 엔진 + Windows 설치 파일(Inno Setup) |
| v0.1.2 | 단어장, 교정 강도(적극/보수), 오프라인(기기 내) 인식 옵션, Groq 기본 120B·temperature 0 |
| v0.2.0 | 현장 자막 모드(조각 → 교정 화면 → 자막 화면, 기록 저장) |
| v0.2.1 | 2초 고정 간격 대신 자연스러운 지점에서 자르기 |
| v0.2.2 | 유튜브 링크를 테스트 소리로, 단어 합쳐짐 중복 버그 수정, 단위 테스트 |
| v0.2.3 | 번역 모델 받기 창, 테스트 소리 칸 정리 |
| v0.2.4 | 조작자 줄바꿈(Shift+Enter), 자동 줄바꿈(실험, 기본 끔), Python 단위 테스트 |

## 핵심 설계 결정과 근거

- **엔진 = 숨긴(headless) Chrome 의 Web Speech API.** 무료이고 구글 클라우드 품질. Linux 헤드리스 + 가짜 마이크로 동작 확인, Windows CI 에서 설치본 엔진 연결 확인.
- **오디오는 트랙으로 넣는다** (`SpeechRecognition.start(track)`, Chrome 135+). 마이크 선택, 시스템 소리(Python soundcard loopback → MediaStreamTrackGenerator), 테스트 영상(audio.captureStream) 모두 같은 경로.
- **Groq 은 확정 문장에만.** 교정은 적극적 프롬프트 + 단어장이 고유명사("크로키는" → Groq)를 더 잘 고침. 20B/120B 속도 차이 0.1~0.2초라 120B 기본.
- **조각 나누기**: 문장 확정 → 말 멈춤(0.7초) → 어미(~다, ~요, ~고, ~는데 …) → 최대 대기(4초). 내보낸 위치는 단어 수가 아니라 글자 수로 기억(Chrome 이 확정할 때 단어를 합치거나 나눈다).
- **세션이 끊기면 아직 확정 안 된 말까지 조각으로 넘긴다** (네트워크 오류 때 문장 유실 방지).

## 실험 수치 (같은 설교 영상, 유튜브 자동 자막 대비)

- Chrome 클라우드 인식 1분: 문자 일치율 93.9%, 10분: 90.3%(문장 확정만 쓸 때. 네트워크 오류 3회 동안 문장 유실)
- 같은 3분, 문장 확정만 676자(83.2%) → 조각 방식 825자(93.4%)
- 자르는 지점이 어미인 비율: 2초 고정 37% → 자연스러운 지점 71%, 평균 간격 2.1초 → 2.3초
- 오프라인(기기 내) 인식: 실제 PC 의 일반 Chrome 에서는 동작(기본 마이크·트랙 둘 다). 정확도는 클라우드보다 확실히 낮음. Linux 헤드리스·Windows CI 에서는 "Unable to find SODA files" 로 실패 → **우리 앱(헤드리스)에서 PC 동작 미확인**
- 참고 기준: Ofcom 라이브 자막 지연 권고 최대 3초(2023 제안 평균 4.5초), 실제 방송 평균 5.6초, 정확도 98%. 지금 기본값(조각 ~2.3초 + 카운트다운 3초)은 약 5초.

## PC에서 아직 확인 안 된 것

- 트레이 아이콘·전역 단축키·실제 붙여넣기는 사용자가 동작 확인함. 그 외:
- 현장 자막을 실제 마이크·믹서 입력으로, 자막 화면을 프로젝터 전체 화면으로
- 번역 모델 받기 창에서 끝까지 받아지는지, 받은 뒤 내장 번역으로 자막이 나오는지
- 오프라인 인식이 헤드리스 엔진에서 되는지 (안 되면 이유를 띄우고 멈추게 해 둠)
- macOS·Linux 데스크톱 전반 (코드상 지원, 실기 미검증)

## 남은 과제 (사용자와 이야기했지만 아직 안 함)

1. **조작자가 속도를 따라가기 힘듦** (사용자 피드백). 제안해 둔 것:
   - "여기까지 한 번에 내보내기"(Enter 한 번에 위쪽 대기 조각까지)
   - 자동 내보내기 + 전체 일시정지 키(틀린 것만 잡는 방식)
   - 밀린 정도 표시(대기 n개 · 약 n초 지연)
   - 조각 크기 선택(짧게 / 문장 단위)
   - 추천 기본값: 자동, 카운트다운 2초, 최대 대기 3초, 쉼 0.6초 → 약 4초
2. ~~자막 화면 줄바꿈~~ → v0.2.4: 기계적 판단은 오류가 많다는 사용자 판단에 따라 **조작자가 `Shift+Enter`로 줄바꿈**(관례상 가장 익숙한 키). 조작자가 찍은 문장부호 뒤에서도 바뀜. 앞뒤 문맥 추측(`sentence_break`)은 "자동 줄바꿈(실험)" 설정으로만 남김(기본 끔). 자막 줄 수 기본 2.
3. 단축키를 키 눌러서 지정하는 방식(지금은 `<ctrl>+<alt>+<space>` 형식 직접 입력)
4. Chrome 이 이미 내보낸 단어를 나중에 고치면 반영 안 됨 → 조작자가 고쳐야 함
5. 프로젝터 모니터 자동 배치(지금은 창을 옮겨 더블클릭)
6. 코드 서명 없음(SmartScreen 경고), GitHub Actions Node 20 액션 지원 종료 예정 경고

## 개발·검증 방법 (이 서버 기준)

이 서버는 SSH 전용이라 화면·사운드카드가 없다. 그래도 다음으로 대부분을 검증했다.

- **Chrome**: `dl.google.com` 의 공식 .deb 를 `dpkg-deb -x` 로 풀어 `--no-sandbox` 로 실행(설치 권한 없음).
- **가짜 마이크**: `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>` (기본 마이크 방식은 사운드카드가 없어 `audio-capture` 오류 → 트랙 방식만 시험 가능).
- **앱 실행**: `XDG_CONFIG_HOME=<임시> VK_CHROME=<chrome> VK_CHROME_ARGS="--no-sandbox --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>" python main.py --no-tray --dry-run`. `VK_GROQ_URL` 로 가짜 Groq 서버를 붙일 수 있다.
- **시스템 소리**: `pw-cli create-node adapter '{ factory.name=support.null-audio-sink node.name=vk-test-sink media.class=Audio/Sink object.linger=true audio.position=[FL FR] }'` 로 가상 스피커를 만들고 `pw-play --target vk-test-sink` 로 재생. 끝나면 `pw-cli destroy <id>` 로 지운다.
- **페이지 조작**: Chrome `--remote-debugging-port` + CDP `Runtime.evaluate`(userGesture). **127.0.0.1:9333 은 adb 가 쓰고 있어** Chrome 은 `::1` 에만 열린다 → `localhost`/`[::1]` 로 접속.
- **함정**: `pkill -f <패턴>` 은 그 패턴이 들어 있는 셸 명령 자신도 죽인다. PID 를 기록해 `kill` 할 것. 헤드리스 첫 페이지가 about:blank 로 남는 경우가 있어 `location.href` 로 다시 연다.
- **단위 테스트**: `node tests/chunker.test.mjs`, `python -m unittest discover tests` (CI 에서도 실행).
- **릴리스**: `main` 푸시 → Windows 빌드·설치 스모크 테스트, `v*` 태그 → 설치 파일 릴리스.
- 실험 브랜치 `exp/on-device-speech`: 오프라인 인식·Groq 교정 비교용 테스트 페이지(`experiments/ondevice/test.html`).
