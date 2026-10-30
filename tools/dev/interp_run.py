"""앱 전체로 순차통역 모드 시험: 유튜브 테스트 소리(3:00부터) → 순차통역 자막 → 조각·원어 수집."""
import asyncio, json, sys, time, aiohttp
URL, SECONDS, OUT = sys.argv[1], float(sys.argv[2]), sys.argv[3]
PORT = int(sys.argv[4]) if len(sys.argv) > 4 else 8765
async def main():
    async with aiohttp.ClientSession() as s:
        await s.post(f"http://localhost:{PORT}/api/settings", json={"live": {"mode": "interpret", "engine": "cloud", "other_lang": "en-US", "review": "auto", "countdown": 1}})
        op = await s.ws_connect(f"http://localhost:{PORT}/ws?role=operator")
        state = {"items": [], "other": [], "test": {}}
        async def read():
            async for m in op:
                d = json.loads(m.data)
                if d.get("type") == "queue":
                    state["items"], state["other"], state["test"] = d["items"], d.get("other", []), d["status"].get("test", {})
        task = asyncio.create_task(read())
        await op.send_json({"cmd": "test_load", "url": URL})
        for _ in range(240):
            await asyncio.sleep(0.5)
            if state["test"].get("status") in ("ready", "error"): break
        print("test:", state["test"].get("status"), state["test"].get("error", "")[:120], flush=True)
        await op.send_json({"cmd": "start", "test": True, "offset": 180})
        await asyncio.sleep(SECONDS)
        await op.send_json({"cmd": "stop"}); await asyncio.sleep(1); task.cancel()
        json.dump({"items": state["items"], "other": state["other"]}, open(OUT, "w"), ensure_ascii=False)
asyncio.run(main())
