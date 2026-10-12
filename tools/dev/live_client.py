"""현장 자막 테스트: 조작자·자막 화면 역할로 붙어 자동/승인 흐름을 돌린다."""
import asyncio, json, sys, time, aiohttp
AUTO_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 180
BASE = "http://localhost:8765"

async def main():
    async with aiohttp.ClientSession() as s:
        op = await s.ws_connect(f"{BASE}/ws?role=operator")
        disp = await s.ws_connect(f"{BASE}/ws?role=display")
        state = {"items": [], "display": [], "drafts": {}}
        t0 = time.time()

        async def read_op():
            async for m in op:
                d = json.loads(m.data)
                if d.get("type") == "queue":
                    state["items"] = d["items"]
                    for it in d["items"]:
                        if it["id"] not in state["drafts"]:
                            state["drafts"][it["id"]] = (round(time.time() - t0, 1), it["text"])
        async def read_disp():
            async for m in disp:
                d = json.loads(m.data)
                if d.get("type") == "display":
                    state["display"] = d["items"]
        tasks = [asyncio.create_task(read_op()), asyncio.create_task(read_disp())]
        await s.post(f"{BASE}/api/settings", json={"live": {"review": "auto", "countdown": 3}})
        await op.send_json({"cmd": "start"})
        await asyncio.sleep(AUTO_SECONDS)

        drafts = sorted(state["drafts"].items())
        times = [t for _, (t, _) in drafts]
        gaps = [round(b - a, 1) for a, b in zip(times, times[1:])]
        lens = [len(txt) for _, (_, txt) in drafts]
        print(f"[auto] 조각 {len(drafts)}개 · 간격 평균 {sum(gaps)/max(len(gaps),1):.1f}초 최대 {max(gaps or [0])}초 · 길이 평균 {sum(lens)/max(len(lens),1):.0f}자")
        for _, (t, txt) in drafts[:8]:
            print(f"   {t:6.1f}s  {txt}")
        sent = [i for i in state["items"] if i["status"] == "sent"]
        print(f"[auto] 자동으로 나간 조각 {len(sent)}개 · 자막 화면 조각 {len(state['display'])}개")

        # 승인 모드: 새 조각은 저절로 나가지 않아야 한다
        await s.post(f"{BASE}/api/settings", json={"live": {"review": "manual"}})
        await asyncio.sleep(12)
        pending = [i for i in state["items"] if i["status"] == "pending"]
        print(f"[manual] 12초 후 대기 중 {len(pending)}개 (자동으로 안 나가야 함)")
        if len(pending) >= 3:
            a, b, c = pending[:3]
            await op.send_json({"cmd": "editing", "id": a["id"], "on": True})
            await op.send_json({"cmd": "send", "id": a["id"], "text": "[수정] " + a["text"]})
            await op.send_json({"cmd": "discard", "id": b["id"]})
            await op.send_json({"cmd": "update", "id": c["id"], "text": "[저장만] " + c["text"]})
            await asyncio.sleep(1)
            ids = {i["id"]: i for i in state["items"]}
            print(f"[manual] 수정후 내보냄: {ids[a['id']]['status']} '{ids[a['id']]['text'][:30]}'")
            print(f"[manual] 버림: {ids[b['id']]['status']} · 저장만: {ids[c['id']]['status']} '{ids[c['id']]['text'][:30]}'")
            print(f"[display] 마지막 조각: {state['display'][-1]['text'][:40] if state['display'] else None}")
            # 이미 나간 조각 고치기
            first_sent = next(i for i in state["items"] if i["status"] == "sent")
            await op.send_json({"cmd": "send", "id": first_sent["id"], "text": "[나간뒤 수정] " + first_sent["text"]})
            await asyncio.sleep(1)
            print(f"[display] 첫 조각: {state['display'][0]['text'][:40]}")
        await op.send_json({"cmd": "send_all"})
        await asyncio.sleep(1)
        await op.send_json({"cmd": "stop"})
        await asyncio.sleep(1)
        for t in tasks: t.cancel()
        st = (await (await s.get(f"{BASE}/api/settings")).json())["status"]
        print("[status] live", st["live"])

asyncio.run(main())
