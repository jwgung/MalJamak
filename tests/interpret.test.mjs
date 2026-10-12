// 순차통역 모드의 결과 합치기(engine.html) 단위 테스트: node tests/interpret.test.mjs
// 사례는 순차통역 설교 실험에서 실제로 나온 결과들이다.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";

const html = readFileSync(new URL("../voicekb/web/engine.html", import.meta.url), "utf8");
const body = html.slice(html.indexOf("// ── 순차통역 합치기 시작"), html.indexOf("// ── 순차통역 합치기 끝"));
const file = join(mkdtempSync(join(tmpdir(), "interp-")), "merger.mjs");
writeFileSync(file, body + "\nexport { InterpretMerger };\n");
const { InterpretMerger } = await import(pathToFileURL(file).href);

let fail = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${ok ? "" : ` → got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) fail++;
};
const run = (texts) => { const m = new InterpretMerger(); return texts.map((t) => m.add(t).join(" ")); };

check("짧게 끊긴 결과 뒤에 온 전체 문장은 늘어난 부분만",
  run(["출애굽 15장에 보면 성경 전체에서 처음으로 등장하는 두 단어들이", "출애굽 15장에 보면 성경 전체에서 처음으로 등장하는 두 단어들이 있습니다"]),
  ["출애굽 15장에 보면 성경 전체에서 처음으로 등장하는 두 단어들이", "있습니다"]);
check("앞부분 반복 떼기 (…바로 + 바로 노래라는)",
  run(["바로", "바로 노래라는 단어와"]), ["바로", "노래라는 단어와"]);
check("조금 다르게 받아 적은 중복은 버림 (불평/불편)",
  run(["그 찬양하던 백성이 불평하기 시작합니다", "그 찬양하던 백성이 불편하기 시작합니다"]), ["그 찬양하던 백성이 불평하기 시작합니다", ""]);
check("한국어 결과 속 영어 단어 제거", run(["사실 저였습니다 I"]), ["사실 저였습니다"]);
check("영어만 받아 적은 결과는 버림", run(["I can't to Korea am vitation my friend"]), [""]);
check("겹쳐 돈 세션의 같은 문장 세 번",
  run(["그리고 그 백성은 동일한 백성이었습니다", "그리고 그 백성은 동일한 백성이었습니다", "그리고 그 백성은 동일한 백성이었습니다"]),
  ["그리고 그 백성은 동일한 백성이었습니다", "", ""]);
check("앞부분만 같은 다른 문장은 중복이 아님 (실제 사례)",
  run(["그리고 그 백성은 동일한 백성이었습니다 그리고", "그리고 그 백성은 사실 저였습니다"]),
  ["그리고 그 백성은 동일한 백성이었습니다 그리고", "그 백성은 사실 저였습니다"]);
check("새 문장은 그대로 이어 붙임",
  run(["아 제가 초청을 받아서 한국에 왔는데요", "우리 김상아 목사님 초청해 주셨습니다"]),
  ["아 제가 초청을 받아서 한국에 왔는데요", "우리 김상아 목사님 초청해 주셨습니다"]);
// 통역 언어가 한국어가 아닐 때: 그 언어의 문자 기준으로 거른다
const runLang = (lang, texts) => { const m = new InterpretMerger(lang); return texts.map((t) => m.add(t).join(" ")); };
check("영어 통역(한국어 강사): 섞여 든 한국어 단어는 빼고 영어만",
  runLang("en-US", ["저는 Welcome to Korea everyone", "Welcome to Korea everyone today"]),
  ["Welcome to Korea everyone", "today"]);
check("영어 통역: 대소문자만 다른 중복은 버림",
  runLang("en-US", ["God's grace is the same for everyone", "god's grace is the same for everyone"]),
  ["God's grace is the same for everyone", ""]);
check("일본어 통역: 한자·가나는 남기고 영어는 뺌",
  runLang("ja-JP", ["今日は ローマ書 8章を 見ます hello"]), ["今日は ローマ書 8章を 見ます"]);
process.exit(fail ? 1 : 0);
