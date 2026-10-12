(async () => {
  const out = [];
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (id) => document.getElementById(id);
  const count = (cls) => document.querySelectorAll(`.item.${cls}`).length;
  try {
    $("btnLive").click(); await wait(10000);
    out.push(`시작 10초: 대기 ${count("pending")} · 나감 ${count("sent")} · 멈춤버튼 보임=${!$("btnPause").hidden}`);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: " ", code: "Space", ctrlKey: true, bubbles: true }));
    await wait(500);
    const sentAtPause = count("sent");
    out.push(`Ctrl+Space 후: 상태="${$("stateText").textContent}" 버튼="${$("btnPause").textContent}" paused=${status.paused}`);
    await wait(9000);
    out.push(`멈춘 9초 동안: 나감 ${sentAtPause} → ${count("sent")} (같아야 함) · 대기 ${count("pending")} · 첫 대기 표시="${document.querySelector(".item.pending .meta")?.textContent}"`);
    const pend = [...document.querySelectorAll(".item.pending:not(.suggest) input")];
    if (pend.length) {
      const before = count("sent");
      const idx = Math.min(2, pend.length - 1);
      const target = pend[idx];
      target.focus(); target.value = target.value + " (고침)"; target.dispatchEvent(new Event("input", { bubbles: true }));
      target.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, bubbles: true }));
      await wait(800);
      const sentTexts = [...document.querySelectorAll(".item.sent input")].map((i) => i.value);
      out.push(`Ctrl+Enter(대기 ${idx + 1}번째에서): 나감 ${before} → ${count("sent")} (+${idx + 1} 이어야 함) · 마지막 나간 조각="…${sentTexts[sentTexts.length - 1]?.slice(-20)}" · 남은 대기 ${count("pending")}`);
    }
    $("btnPause").click(); await wait(500);
    out.push(`다시 흐르기: 상태="${$("stateText").textContent}"`);
    const s1 = count("sent"); await wait(5000);
    out.push(`다시 흐른 5초 뒤: 나감 ${s1} → ${count("sent")} (늘어야 함)`);
    $("btnLive").click();
  } catch (err) {
    out.push(`오류: ${err.message} · paused=${status.paused} review=${status.review}`);
  }
  return out.join("\n");
})()
