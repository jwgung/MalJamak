"""dual 모드 e2e 시험: 유튜브 테스트 소리(3:00부터) → 이중 STT 자막 → 번역/통역 조각 수집.
조작자 선택 시뮬레이션: 각 pair에서 번역 쪽을 내보내고 통역 쪽을 버린다 (번역 우선 시나리오).

용법: .venv/bin/python -I tools/dev/dual_run.py <유튜브 URL> <초> <out.json> [port]
"""
import asyncio, json, sys, aiohttp

URL, SECONDS, OUT = sys.argv[1], float(sys.argv[2]), sys.argv[3]
PORT = int(sys.argv[4]) if len(sys.argv) > 4 else 8765

async def main():
    async with aiohttp.ClientSession() as s:
        # dual 모드로 설정
        await s.post(f"http://localhost:{PORT}/api/settings",
                     json={"live": {"mode": "dual", "other_lang": "en-US", "review": "manual"}})
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

        # 각 pair 를 한 번만 처리 (번역 우선 시나리오)
        handled = set()
        sent, discarded = 0, 0
        try:
            for _ in range(int(SECONDS * 5)):
                await asyncio.sleep(0.2)
                # pending pair 를 찾는다
                pending = {}
                for it in state["items"]:
                    if it["status"] == "pending" and it.get("pair_id") is not None and it["side"]:
                        pending.setdefault(it["pair_id"], {})[it["side"]] = it
                for pair_id, sides in pending.items():
                    if pair_id in handled:
                        continue
                    # 두 쪽이 모두 모였으면 처리 (번역 우선: 번역 send, 통역 discard)
                    if "translate" in sides and "interpret" in sides:
                        handled.add(pair_id)
                        await op.send_json({"cmd": "discard", "id": sides["interpret"]["id"]})
                        await op.send_json({"cmd": "send", "id": sides["translate"]["id"]})
                        sent += 1; discarded += 1
        finally:
            await op.send_json({"cmd": "stop"})
            await asyncio.sleep(1)
            task.cancel()

        # 결과 정리
        items = state["items"]
        pairs = {}
        for it in items:
            if it.get("pair_id") is None:
                continue
            pairs.setdefault(it["pair_id"], {})[it["side"]] = it
        out = {
            "sent": sent, "discarded": discarded,
            "pairs": [
                {
                    "pair_id": pid,
                    "translate": v.get("translate", {}).get("text", ""),
                    "translate_source": v.get("translate", {}).get("source", ""),
                    "interpret": v.get("interpret", {}).get("text", ""),
                    "translate_status": v.get("translate", {}).get("status", ""),
                    "interpret_status": v.get("interpret", {}).get("status", ""),
                }
                for pid, v in sorted(pairs.items())
            ],
        }
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print(f"done: {sent} sent (translate), {discarded} discarded (interpret), {len(pairs)} pairs total")
        print("saved", OUT)

asyncio.run(main())
