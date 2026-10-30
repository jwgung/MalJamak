# 현장 자막: 이중 STT 모드 (영어 STT+번역 vs 한글 STT)

> **v0.8.x 에서 바뀐 점** (이 문서의 처음 설계와 다름): 각 언어 연속 세션 하나로는 한글 쪽이 거의 비어 순차통역 모드와 같은
> 쉼마다 새 세션 + `InterpretMerger` 합치기를 쓴다(강사 말도 합친다). 짝(pair_id)은 2초 창이 아니라 바통 넘김 차례(`dualTurn`)다.
> 고르기는 서버 `choose`(고른 뒤 같은 차례의 다른 쪽은 버림, 고르기 전엔 자동으로 안 나감). LLM 기능은 하지 않기로 했다.
> 측정은 [handoff](handoff.md) "실험 수치 추가". **아래 본문은 처음 설계 그대로 두었다** — `InterpretMerger` 불필요·2초 짝짓기·Tab/←→ 전환·Esc 로 차례 버리기·dual 에서 자동 내보내기 무시는
> 구현과 다르다. 지금은 고르기 전 차례는 자동으로 안 나가고, 고르면 그 쪽이 바로 나간다. 같은 차례에 고른 뒤 오는 조각은 고른 쪽이면 검토 방식(자동·승인)을 따르고, 다른 쪽이면 버린다. 키는 `Enter`·`1`/`2`·`Alt+1`/`Alt+2`·클릭.

## 목표

순차통역 현장에서 **통역사 역량**에 의존하지 않고, 영어 STT(정확도 높음)로 자막을 만드는 경로와
현장 통역사 한글 STT 경로를 **병렬로** 만들어 조작자가 둘을 비교 후 고르게 한다.

```
강사 영어 ──→ 영어 STT ──→ Chrome 내장 번역 ──→ [번역 조각]  ─┐
                                                              ├→ 조작자 비교 → 고른 쪽만 자막
통역 한글 ──────────────────────────────────→ [통역 조각]  ─┘
```

- **LLM(Groq)은 추후**. 기본 구성은 Groq 없이 완전 동작.
- 번역은 **Chrome 내장 번역** (구글 번역, 무료, 오프라인 가능).
- 조작자가 고른 쪽만 자막 화면에 표시.

## 현재 구조와 차이

| | 현재 순차통역 (v0.4~0.7) | 이중 STT |
|---|---|---|
| 주(主) 경로 | 통역 한글 STT | 둘 동등 (조작자가 고름) |
| 영어 STT | 참고 줄만 (강사 원어) | **번역해서 자막 조각으로** |
| `InterpretMerger` | 쉼 감지·세션 겹침·중복 합치기 | **불필요** (각 언어가 자기 속도로 조각) |
| 조작자 워크플로 | 통역 조각 검토 + 빠진 통역 클릭→번역 제안 | **두 줄 나란히 보고 고르기** |
| Groq | 번역 제안에만 (선택) | **없음** (추후 교정·추천) |

## 설계

### 1. `engine.html` — 이중 STT 엔진 (새 함수 `startDual`)

`startInterpret`와 병행하는 새 함수. `startLive`에서 `msg.mode === "dual"` 이면 호출.

```js
async function startDual(msg, stream, testAudio) {
  const target = msg.lang || "ko-KR";     // 통역(한국어)
  const other  = msg.other_lang || "en-US"; // 강사(영어)

  // 두 개의 인식기: 각 언어가 자기 세션
  const rKo = newRecognition(target);  // continuous, interimResults
  const rEn = newRecognition(other);

  // Chrome 내장 번역기 (영어 → 한국어)
  const builtin = await createBuiltinTranslator("en", "ko");

  // 각 인식기는 일반 live 방식처럼 조각을 자른다
  // (문장 확정 → 말 멈춤 → 어미 → 최대 대기)
  // 단, 어미 자르기는 각 언어에 맞게:
  //   한국어: BOUNDARY (现有)
  //   영어:   문장부호 + pause + max (어미 규칙 없음)

  // 영어 확정 조각 → 내장 번역 → { type: "draft", side: "translate", pair_id, text }
  // 한국어 확정 조각 → { type: "draft", side: "interpret", pair_id, text }
}
```

**핵심: `InterpretMerger` 없음.** 각 인식기가 일반 `evaluateLive` 로 자기 속도로 조각을 만들고,
서로 독립적으로 `draft` 메시지를 보낸다.

**pair_id 부여**:
- 영어 확정 조각이 나면 `++dualSeq` 로 pair_id 생성, `draft { side: "translate", pair_id }`
- 한국어 확정 조각이 나면:
  - 최근 pair_id 내 영어 조각이 아직 pending 이면 → 같은 pair_id 사용
  - 없으면 새 pair_id
  - `draft { side: "interpret", pair_id }`
- pair_id를 정밀하게 매칭하지 않아도 됨 — 조작자 화면에서 **시간 순서로 나란히** 보이기 때문

**세션 관리**:
- 각 인식기는 `makeRestarter` 로 자동 재시작 (기존 방식)
- Chrome 세션 끊김(침묵·네트워크) 시 `onend` 에서 `emitLive` 로 남은 조각 유실 방지 (기존 방식)
- **쉼 감지·세션 재개 없음** — 각 언어가 연속적으로 말하지 않으니, 쉼마다 세션을 새로 열지 않아도 됨
  - 영어: 강사가 말할 때만 인식, 아닐 때 침묵 (기존 `restarter` 가 처리)
  - 한국어: 통역사가 말할 때만 인식, 아닐 때 침묵
- **다만**: Chrome SpeechRecognition 은 한 세션에 한 언어만 정확히 인식.
  강사(영어)가 말할 때 한국어 인식기는 무응답(또는 음차), 반대로도 동일.
  → **이것이 자연스럽게 언어 필터가 됨** (현재 interpret 모드의 원리와 동일)

### 2. `server.py` — draft 처리 변경

`on_draft`에 `side`와 `pair_id`를 추가 받음.

```python
async def on_draft(self, text: str, reason: str = "", side: str = "stt", pair_id: int | None = None):
    chunk, prev_changed = self.live.add_draft(
        text, cfg["review"], cfg["countdown"], reason, auto_break,
        side=side, pair_id=pair_id,
    )
```

`broadcast_live` 의 `queue` payload 에 변경 없음 — `items` 리스트에 각 조각의 `side`, `pair_id`가 포함되어 전송됨.

**`live_other` 참고 줄은 dual 모드에서 사용하지 않음.** 영어 원어는 번역 조각의 `source` 필드로 보관.

### 3. `live.py` — Chunk 확장

```python
@dataclass
class Chunk:
    # 기존 필드 그대로
    ...
    side: str = ""       # dual 모드: "translate" | "interpret" | "" (일반)
    pair_id: int | None = None  # dual 모드: 같은 문장의 두 버전 짝
```

`queue_view()` 에 `side`, `pair_id` 자동 포함 (asdict).

**`add_draft` 서명 변경**:
```python
def add_draft(self, text, review, countdown, reason="", auto_break=False,
              side: str = "", pair_id: int | None = None) -> tuple[Chunk | None, bool]:
```

**내보내기·기록·`display_view`** : 변경 없음. 조작자가 `send` 한 조각만 자막 화면·기록 파일에 감.
`side`/`pair_id`는 기록 파일에 안 남음 (자막 화면은 text만 표시).

### 4. `config.py` — 설정

```python
"live": {
    ...
    "mode": "normal",  # normal | interpret | dual
    ...
}
```

기존 `interpret` 모드와 병행. `dual` 선택 시 `lang`(통역 언어) + `other_lang`(강사 언어) 사용.

### 5. `operator.html` — 두 줄 나란히 레이아웃

**큐 목록 렌더링 변경** (dual 모드일 때):

```
┌─────────────────────────────────────────────────┐
│ [번역] 그러니까 이것이 바로 성령의 능력입니다    │  ← side: translate
│ [통역] 그러니까 이것이 바로                     │  ← side: interpret
│         (같은 pair_id → 한 단위로 묶음)          │
├─────────────────────────────────────────────────┤
│ [번역] 다음 문장 번역...                        │
│ [통역] 다음 문장 통역...                        │
└─────────────────────────────────────────────────┘
```

**구현**:
- `render()`에서 `pair_id`로 그룹핑 → 같은 pair_id 조각은 `.pair` 클래스의 래퍼 안에 두 줄로 배치
- 각 줄에 `side` 라벨 ("번역" / "통역") + 텍스트
- **포커스**: pair 단위 포커스 (두 줄 중 하나를 클릭하면 pair 전체가 포커스)
- **Enter**: 포커스된 pair에서 **마우스/키보드로 선택한 줄**을 `send`
  - `Tab` 또는 `←`/`→` : pair 내 줄 전환 (번역 ↔ 통역)
  - `Enter` : 선택한 줄 내보내기
  - 또는 마우스 클릭: 해당 줄을 선택+내보내기
- **Esc**: pair 전체 버리기 (두 줄 모두 `discard`)
- **Shift+Enter**: 내보내기 + 줄바꿈 (기존 동작)

**CSS**:
```css
.pair { display: flex; flex-direction: column; gap: 2px; }
.pair .item { padding: 6px 10px; font-size: 16px; }
.pair .item.side-translate { border-left: 3px solid var(--accent); }
.pair .item.side-interpret { border-left: 3px solid var(--ok); }
.pair .item.selected { background: var(--accent-soft); }
```

**기존 동작 유지**: `normal` / `interpret` 모드는 현재 레이아웃 그대로.

### 6. `display.html` — 변경 없음

조작자가 `send` 한 조각만 표시. `side`/`pair_id`에 무관.

### 7. `server.py` `set_live` — `dual` 모드 전달

```python
"mode": cfg["mode"],  # "dual" 전달
"other_lang": cfg["other_lang"],
```

기존 `interpret`와 동일하게 엔진에 전달.

## 조작자 워크플로 (dual 모드)

1. "자막 시작" 클릭
2. 강사가 영어로 말 → 영어 STT → 번역 조각 나타남
3. 통역사가 한글로 말 → 통역 조각 나타남
4. 조작자:
   - 두 줄이 거의 같으면 → 통역 쪽 클릭 (원래 말 그대로)
   - 번역이 더 충실하면 → 번역 쪽 클릭
   - 둘 다 이상하면 → 직접 입력으로 고침
5. 고른 쪽만 자막 화면에 표시

**자동 내보내기** (review=auto):
- dual 모드에서는 **자동 내보내기를 비활성화** (둘 중 고르는 것이 조작자의 일)
- 또는: 카운트다운 끝나면 **번역 쪽 기본**으로 내보내기, 조작자가 수정하면 통역 쪽으로 변경
- → **기본은 manual review** (dual 모드에서는 review=auto 무시, manual 적용)

## LLM 추후 추가 (이번 범위 아님)

1. **추천 하이라이트**: "둘 중 더 나은 쪽"을 Groq이 판단 → 하이라이트 표시
   - 조작자는 여전히 직접 선택, LLM은 제안만
2. **STT 교정**: 영어 STT 결과의 오타·문법 교정 → 번역 품질 향상
3. **중복 판정**: 둘이 거의 같으면 "같음" 표시 → 조작자가 한쪽만 보도록 축소

## 테스트

- `tests/test_live.py`: `side`, `pair_id` 필드 추가, dual 모드 `add_draft` 테스트
- `tools/dev/interp_run.py`: dual 모드 변형 — 같은 테스트 영상(74mKr5o2gyM 3:00~5:00)으로
  - 번역 조각 vs 통역 조각 비교
  - 조작자 선택 시나리오 시뮬레이션 (자동: 둘이 다르면 번역 우선)
- `score_live.py`: 기존 유튜브 자막 기준과 비교

## 변경 파일 요약

| 파일 | 변경 |
|---|---|
| `maljamak/web/engine.html` | `startDual()` 새 함수, `startLive`에서 `mode==="dual"` 분기 |
| `maljamak/live.py` | `Chunk.side`, `Chunk.pair_id`, `add_draft` 서명 확장 |
| `maljamak/server.py` | `on_draft` 파라미터 확장, `set_live`에서 dual 전달 |
| `maljamak/config.py` | `mode` 값에 `"dual"` 추가 (주석만) |
| `maljamak/web/operator.html` | dual 모드 레이아웃 (pair 그룹핑, 두 줄, 선택) |
| `tests/test_live.py` | dual 필드 테스트 |
| `docs/handoff.md` | 진행 상황 기록 |

## 리스크·미검증

1. **Chrome SpeechRecognition 동시 2세션**: 현재 interpret 모드가 이미 2세션(연속+단발)을 돌림.
   dual도 2세션(각 언어 하나)이므로 동일 수준. 다만 **각 세션이 continuous**라
   Chrome 리소스(메모리·CPU) 사용이 interpret보다 약간 높을 수 있음.
2. **번역 지연**: Chrome 내장 번역은 로컬(모델 다운로드 후)이라 0.2~0.5초.
   네트워크 번역이면 0.5~1.5초. 조작자 사이클(10~20초)에 영향 없음.
3. **통역이 안 하는 현장**: 통역 조각이 안 오면 번역 조각만 pending →
   조작자가 번역만 고르면 됨. (역량 약한 현장의 목적 달성)
4. **강사가 안 하는 구간**: 영어 조각이 안 오면 통역 조각만 pending →
   조작자가 통역만 고르면 됨.
