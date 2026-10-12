"""현장 자막 결과(interp_run.py 출력 JSON)를 유튜브 자동 자막(json3)과 비교해 일치율을 낸다.

사용법: python score_live.py <결과.json> <자막.json3> <시작초> <끝초> [-v]
한글만 비교한다 (순차통역 한국어 시험용).
"""
import difflib, json, re, sys, textwrap

result, subs, start, end = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
r = json.load(open(result, encoding="utf-8"))
d = json.load(open(subs, encoding="utf-8"))
yt = " ".join("".join(s.get("utf8", "") for s in ev.get("segs") or [])
              for ev in d["events"] if start * 1000 <= ev.get("tStartMs", 0) < end * 1000).replace(">>", "")
norm = lambda s: re.sub(r"[^가-힣0-9]", "", s)
ours = " ".join(i["text"] for i in r["items"])
a, b = norm(ours), norm(yt)
print(f"조각 {len(r['items'])}개 · 한국어 {len(a)}자 / 유튜브 {len(b)}자 · "
      f"일치율 {difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() * 100:.1f}% · 원어 참고 {len(r.get('other', []))}줄")
if "-v" in sys.argv:
    print(textwrap.fill(ours, 120))
