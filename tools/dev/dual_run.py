"""이중 STT(dual) 모드 시험: 유튜브 테스트 소리(3:00부터)로 번역/통역 조각을 모은다. 조작자 선택은 하지 않는다.

용법: .venv/bin/python -I tools/dev/dual_run.py <유튜브 URL> <초> <out.json> [port]
출력: items = 통역(한글 STT) 조각 (score_live.py 로 유튜브 한국어 자막과 비교), translate = 번역 조각,
      pairs = 차례(pair_id)별 두 쪽 글
"""
import asyncio, json, sys, aiohttp

URL, SECONDS, OUT = sys.argv[1], float(sys.argv[2]), sys.argv[3]
PORT = int(sys.argv[4]) if len(sys.argv) > 4 else 8765


async def main():
    async with aiohttp.ClientSession() as s:
        await s.post(f"http://localhost:{PORT}/api/settings",
                     json={"live": {"mode": "dual", "engine": "cloud", "lang": "ko-KR", "other_lang": "en-US", "review": "manual"}})
        op = await s.ws_connect(f"http://localhost:{PORT}/ws?role=operator")
        state = {"items": [], "test": {}}

        async def read():
            async for m in op:
                d = json.loads(m.data)
                if d.get("type") == "queue":
                    state["items"], state["test"] = d["items"], d["status"].get("test", {})
        task = asyncio.create_task(read())

        await op.send_json({"cmd": "test_load", "url": URL})
        for _ in range(240):
            await asyncio.sleep(0.5)
            if state["test"].get("status") in ("ready", "error"):
                break
        print("test:", state["test"].get("status"), state["test"].get("error", "")[:200], flush=True)
        if state["test"].get("status") != "ready":
            return
        await op.send_json({"cmd": "start", "test": True, "offset": 180})
        try:
            await asyncio.sleep(SECONDS)
        finally:
            await op.send_json({"cmd": "stop"})
            await asyncio.sleep(1.5)
            task.cancel()

        items = state["items"]
        pairs: dict[int, dict] = {}
        for it in items:
            if it.get("pair_id") is not None:
                side = pairs.setdefault(it["pair_id"], {"translate": [], "source": [], "interpret": []})
                side[it["side"]].append(it["text"])
                if it["side"] == "translate":
                    side["source"].append(it.get("source", ""))
        out = {
            "items": [i for i in items if i.get("side") == "interpret"],
            "translate": [i for i in items if i.get("side") == "translate"],
            "pairs": [{"pair_id": k, **{n: " ".join(v) for n, v in p.items()}} for k, p in sorted(pairs.items())],
        }
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        both = sum(1 for p in out["pairs"] if p["translate"] and p["interpret"])
        print(f"done: 통역 {len(out['items'])}조각 · 번역 {len(out['translate'])}조각 · 차례 {len(pairs)}개 (두 쪽 다 있음 {both})")
        print("saved", OUT)

asyncio.run(main())
