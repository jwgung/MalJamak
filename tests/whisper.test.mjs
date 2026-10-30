// Whisper 엔진의 말 토막 나누기·WAV(engine.html) 단위 테스트: node tests/whisper.test.mjs
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";

const html = readFileSync(new URL("../maljamak/web/engine.html", import.meta.url), "utf8");
const body = html.slice(html.indexOf("// ── Whisper 토막 나누기 시작"), html.indexOf("// ── Whisper 토막 나누기 끝"));
const file = join(mkdtempSync(join(tmpdir(), "whisper-")), "whisper.mjs");
writeFileSync(file, body + "\nexport { WhisperSegmenter, encodeWav };\n");
const { WhisperSegmenter, encodeWav } = await import(pathToFileURL(file).href);

let fail = 0;
const check = (name, cond, detail = "") => { console.log(`${cond ? "PASS" : "FAIL"} ${name}${cond ? "" : " → " + detail}`); if (!cond) fail++; };

const RATE = 16000, FRAME = 1600;  // 0.1초 프레임
const loud = () => new Float32Array(FRAME).fill(0.2);
const quiet = () => new Float32Array(FRAME);
const run = (pattern) => {
  const out = [];
  const seg = new WhisperSegmenter(RATE, 600, (s) => out.push(s.length / RATE));
  for (const ch of pattern) seg.push(ch === "#" ? loud() : quiet());
  return { out, seg };
};

{  // 5초 넘게 말한 뒤 0.6초 쉬면 자른다
  const { out } = run("#".repeat(55) + ".".repeat(6));
  check("쉼에서 자름", out.length === 1 && Math.abs(out[0] - 6.1) < 0.01, JSON.stringify(out));
}
{  // 5초가 안 되면 쉬어도 기다린다 (무료 한도: 한 번에 최소 10초로 셈)
  const { out } = run("#".repeat(30) + ".".repeat(8) + "#".repeat(5));
  check("5초 전에는 쉼에서 자르지 않음", out.length === 0, JSON.stringify(out));
}
{  // 쉼 없이 10초가 되면 최근 2초 안의 가장 조용한 곳 뒤에서 자르고 나머지는 다음 토막으로
  const pattern = "#".repeat(90) + "." + "#".repeat(9);
  const { out, seg } = run(pattern);
  check("쉼 없이 길면 조용한 곳에서 자름", out.length === 1 && Math.abs(out[0] - 9.1) < 0.01, JSON.stringify(out));
  check("자른 뒤 나머지는 남김", seg.frames.length === 9, String(seg.frames.length));
}
{  // 말소리가 없으면 보내지 않는다
  const { out, seg } = run(".".repeat(40));
  check("침묵은 보내지 않음", out.length === 0 && seg.frames.length < 20, JSON.stringify(out));
}
{  // 멈출 때 남은 말을 보낸다
  const { out, seg } = run("#".repeat(12));
  seg.flush();
  check("멈출 때 남은 말", out.length === 1 && Math.abs(out[0] - 1.2) < 0.01, JSON.stringify(out));
}
{
  const wav = new DataView(encodeWav(new Float32Array([0, 1, -1]), RATE));
  const tag = String.fromCharCode(...[0, 1, 2, 3].map((i) => wav.getUint8(i)));
  check("WAV 머리", tag === "RIFF" && wav.getUint32(24, true) === RATE && wav.getUint32(40, true) === 6);
  check("WAV 샘플", wav.getInt16(44, true) === 0 && wav.getInt16(46, true) === 32767 && wav.getInt16(48, true) === -32767);
}
process.exit(fail ? 1 : 0);
