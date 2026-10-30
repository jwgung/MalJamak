// 설정 화면의 "키 눌러 지정" 변환(settings.html) 단위 테스트: node tests/hotkey.test.mjs
// 브라우저 키 이벤트 → pynput 단축키 형식
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";

const html = readFileSync(new URL("../maljamak/web/settings.html", import.meta.url), "utf8");
const body = html.slice(html.indexOf("// ── 단축키 변환 시작"), html.indexOf("// ── 단축키 변환 끝"));
const file = join(mkdtempSync(join(tmpdir(), "hotkey-")), "hotkey.mjs");
writeFileSync(file, body + "\nexport { comboFromEvent };\n");
const { comboFromEvent } = await import(pathToFileURL(file).href);

let fail = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${ok ? "" : ` → got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
  if (!ok) fail++;
};
const key = (code, mods = {}) => ({ code, ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, ...mods });

check("Ctrl+Alt+Space", comboFromEvent(key("Space", { ctrlKey: true, altKey: true })), { combo: "<ctrl>+<alt>+<space>" });
check("한글 입력 상태여도 e.code 기준 (Ctrl+Shift+ㅁ → a)", comboFromEvent(key("KeyA", { ctrlKey: true, shiftKey: true })), { combo: "<ctrl>+<shift>+a" });
check("F9 는 혼자 써도 됨", comboFromEvent(key("F9")), { combo: "<f9>" });
check("Win/Cmd 키", comboFromEvent(key("Digit1", { metaKey: true })), { combo: "<cmd>+1" });
check("수식키만 누르면 기다림", comboFromEvent(key("ControlLeft", { ctrlKey: true })), null);
check("글자 하나만은 거절", "error" in comboFromEvent(key("KeyA")), true);
check("스페이스 하나만은 거절", "error" in comboFromEvent(key("Space")), true);
check("한/영 키는 거절", "error" in comboFromEvent(key("Lang1", { ctrlKey: true })), true);
check("기호 키", comboFromEvent(key("Backslash", { altKey: true })), { combo: "<alt>+\\" });
check("Pause 는 혼자 써도 됨", comboFromEvent(key("Pause")), { combo: "<pause>" });
process.exit(fail ? 1 : 0);
