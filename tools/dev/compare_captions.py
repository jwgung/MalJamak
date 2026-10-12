"""Chrome 인식 결과와 유튜브 자동 자막을 비교한다: 문자 일치율 + 서로 다른 구간 목록."""
import difflib, json, re, sys

chrome_log, subs_json, start_s, end_s = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])

chrome = " ".join(re.sub(r"^\[ *[0-9.]+s\] FINAL *", "", l).strip()
                  for l in open(chrome_log, encoding="utf-8") if "FINAL" in l)
finals = [float(m.group(1)) for l in open(chrome_log, encoding="utf-8")
          if (m := re.match(r"^\[ *([0-9.]+)s\] FINAL", l))]

d = json.load(open(subs_json, encoding="utf-8"))
segs = []
for ev in d.get("events", []):
    t = ev.get("tStartMs", 0)
    for seg in ev.get("segs") or []:
        st = t + seg.get("tOffsetMs", 0)
        if start_s * 1000 <= st < end_s * 1000:
            segs.append(seg.get("utf8", ""))
youtube = "".join(segs)

def norm(s):
    s = s.replace(">>", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())

a, b = norm(chrome), norm(youtube)
ratio = difflib.SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", ""), autojunk=False).ratio()
print(f"Chrome {len(a.replace(' ', ''))}자 / 유튜브 {len(b.replace(' ', ''))}자 · 문자 일치율 {ratio * 100:.1f}%")
gaps = [round(y - x, 1) for x, y in zip([0] + finals, finals)]
print(f"Chrome 확정 {len(finals)}회 · 확정 간격 평균 {sum(gaps) / max(len(gaps), 1):.1f}초 · 최대 {max(gaps or [0])}초")

wa, wb = a.split(), b.split()
sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
diffs = []
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag == "equal":
        continue
    ctx = " ".join(wa[max(0, i1 - 2):i1])
    diffs.append((ctx, " ".join(wa[i1:i2]) or "∅", " ".join(wb[j1:j2]) or "∅"))
# 띄어쓰기만 다른 것은 뺀다
diffs = [x for x in diffs if x[1].replace(" ", "") != x[2].replace(" ", "")]
print(f"서로 다른 구간 {len(diffs)}곳 (띄어쓰기 차이 제외)")
for ctx, ca, yb in diffs:
    print(f"  …{ctx} | Chrome: {ca} | 유튜브: {yb}")
