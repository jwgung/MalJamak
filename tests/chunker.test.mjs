// 현장 자막 조각 나누기(engine.html) 단위 테스트: node tests/chunker.test.mjs
// engine.html 의 조각 나누기 함수만 떼어 와서 send·시계를 가짜로 바꿔 끼운다.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";

const html = readFileSync(new URL("../maljamak/web/engine.html", import.meta.url), "utf8");
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];
const body = js.slice(js.indexOf("const MIN_CHUNK_WORDS"), js.indexOf("async function startLive"))
  + js.slice(js.indexOf("// ── 공통 구간 시작"), js.indexOf("// ── 공통 구간 끝"));
const file = join(mkdtempSync(join(tmpdir(), "chunker-")), "chunker.mjs");
writeFileSync(file, body + "\nexport { resetLiveSession, onLiveResult, evaluateLive, emitLive };\n");

globalThis.sent = [];
globalThis.revised = [];
globalThis.send = (m) => { if (m.type === "draft") sent.push(m.text); if (m.type === "revise") revised.push(m); };
let clock = 0;
globalThis.performance = { now: () => clock };
const { resetLiveSession, onLiveResult, evaluateLive, emitLive } = await import(pathToFileURL(file).href);

const ev = (finals, interims) => ({ results: [
  ...finals.map((t) => Object.assign([{ transcript: t }], { isFinal: true })),
  ...interims.map((t) => Object.assign([{ transcript: t }], { isFinal: false })),
] });
const fresh = () => {
  const L = { maxMs: 4000, pauseMs: 700, stableMs: 800, lastEmit: 0, lastChange: 0 };
  resetLiveSession(L); sent.length = 0; revised.length = 0; clock = 0; return L;
};
let fail = 0;
const check = (name, cond) => { console.log(`${cond ? "PASS" : "FAIL"} ${name}${cond ? "" : " → " + JSON.stringify(sent)}`); if (!cond) fail++; };

// 내보낸 뒤 Chrome 이 두 단어를 하나로 합쳐 확정해도 "주세요"가 두 번 나가지 않는다 (실제 발생 사례)
let L = fresh();
onLiveResult(L, ev([], ["리액트 컴포넌트를 깃허브에 올려 주세요"]));
emitLive(L, 4);
clock = 1200; onLiveResult(L, ev(["리액트 컴포넌트를 깃허브에 올려주세요"], []));
clock = 2500; evaluateLive(L);
check("합쳐진 단어 중복 없음", (sent.join(" ").match(/주세요/g) || []).length === 1
  && sent.join("").replace(/ /g, "") === "리액트컴포넌트를깃허브에올려주세요");

// 한 단어를 둘로 나눠 확정해도 유실·중복이 없다
L = fresh();
onLiveResult(L, ev([], ["오늘 회의는 오후3시에 시작합니다"]));
emitLive(L, 3);
clock = 500; onLiveResult(L, ev(["오늘 회의는 오후 3시에 시작합니다"], []));
clock = 2000; evaluateLive(L);
check("나뉜 단어 유실·중복 없음", sent.join("").replace(/ /g, "") === "오늘회의는오후3시에시작합니다");

// 말이 이어지는 중에는 의미 단위가 끝나는 어미("~요") 뒤에서 자른다
L = fresh();
onLiveResult(L, ev([], ["땀도 흘리고 올라갈 때 쉽지가 않아요"]));
clock = 900; onLiveResult(L, ev([], ["땀도 흘리고 올라갈 때 쉽지가 않아요 근데"]));
clock = 1100; onLiveResult(L, ev([], ["땀도 흘리고 올라갈 때 쉽지가 않아요 근데 높은"]));
check("어미에서 자름", sent[0] === "땀도 흘리고 올라갈 때 쉽지가 않아요");

// 말이 멈추면 남은 말을 모두 내보낸다
clock = 1900; evaluateLive(L);
check("쉼에서 나머지 내보냄", sent.join(" ").endsWith("근데 높은"));

// 한국어가 아니면 어미 규칙으로 자르지 않는다 (말 멈춤·최대 대기로만)
L = fresh();
L.korean = false;
onLiveResult(L, ev([], ["they started singing and then"]));
clock = 900; onLiveResult(L, ev([], ["they started singing and then they started to"]));
clock = 1100; onLiveResult(L, ev([], ["they started singing and then they started to complain"]));
check("한국어가 아니면 말이 이어지는 동안 자르지 않음", sent.length === 0);
clock = 1900; evaluateLive(L);
check("한국어가 아니어도 말이 멈추면 내보냄", sent.join(" ") === "they started singing and then they started to complain");

// 조각 크기 "문장 단위": "~고" 같은 이어지는 어미에서는 자르지 않고 문장 끝 어미에서 자른다
L = fresh();
L.sentence = true;
onLiveResult(L, ev([], ["땀도 흘리고 산에 올라가고"]));
clock = 1200; onLiveResult(L, ev([], ["땀도 흘리고 산에 올라가고 쉽지가"]));
clock = 1400; onLiveResult(L, ev([], ["땀도 흘리고 산에 올라가고 쉽지가 않아요"]));
check("문장 단위: 이어지는 어미에서 자르지 않음", sent.length === 0);
clock = 2400; onLiveResult(L, ev([], ["땀도 흘리고 산에 올라가고 쉽지가 않아요 근데"]));
clock = 2500; onLiveResult(L, ev([], ["땀도 흘리고 산에 올라가고 쉽지가 않아요 근데 높은"]));
check("문장 단위: 문장 끝 어미에서 자름", sent[0] === "땀도 흘리고 산에 올라가고 쉽지가 않아요");

// 이미 내보낸 말을 Chrome 이 고쳐 확정하면 그 조각에 "인식이 바뀜"을 알리고, 뒤 조각은 겹치거나 빠지지 않는다
L = fresh();
onLiveResult(L, ev([], ["오늘 로마서 활성화 말씀을"]));
emitLive(L, 4);
clock = 600; onLiveResult(L, ev([], ["오늘 로마서 8장 말씀을 보겠습니다"]));
check("확정 전에는 알리지 않음", revised.length === 0);
clock = 900; onLiveResult(L, ev(["오늘 로마서 8장 말씀을 보겠습니다"], []));
check("확정되면 바뀐 글을 알림", revised.length === 1 && revised[0].text === "오늘 로마서 8장 말씀을" && revised[0].eid > 0);
check("뒤 조각은 빠짐없이", sent[1] === "보겠습니다");
clock = 1500; onLiveResult(L, ev(["오늘 로마서 8장 말씀을 보겠습니다"], []));
check("같은 수정은 한 번만", revised.length === 1);

// 단어를 합치거나 나누기만 한 확정은 수정이 아니다
L = fresh();
onLiveResult(L, ev([], ["깃허브에 올려 주세요"]));
emitLive(L, 3);
clock = 900; onLiveResult(L, ev(["깃허브에 올려주세요"], []));
check("합치기만 한 확정은 알리지 않음", revised.length === 0);

process.exit(fail ? 1 : 0);
