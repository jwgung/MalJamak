# 사용법: python run.py <devtools-port> <lang> <waitSec> <expression-file> [gesture=1]
# Chrome DevTools 로 페이지에서 식을 실행하고 console 출력을 보여준다 (기기 내 음성 인식 실험용).
import asyncio, json, sys, time, aiohttp
port, lang, wait, expr_file = sys.argv[1:5]
gesture = (sys.argv[5] if len(sys.argv) > 5 else "1") == "1"
async def main():
    async with aiohttp.ClientSession() as s:
        pages = await (await s.get(f"http://127.0.0.1:{port}/json/list")).json()
        url = next(p for p in pages if p["type"] == "page")["webSocketDebuggerUrl"]
        async with s.ws_connect(url, max_msg_size=0) as ws:
            t0 = time.time(); n = 0; waiters = {}
            async def reader():
                async for m in ws:
                    msg = json.loads(m.data)
                    if "id" in msg and msg["id"] in waiters: waiters.pop(msg["id"]).set_result(msg)
                    elif msg.get("method") == "Runtime.consoleAPICalled":
                        print(f"[{time.time()-t0:5.1f}s]", " ".join(str(a.get("value", a.get("description"))) for a in msg["params"]["args"]), flush=True)
            task = asyncio.create_task(reader())
            async def call(method, params={}):
                nonlocal n; n += 1; f = asyncio.get_running_loop().create_future(); waiters[n] = f
                await ws.send_json({"id": n, "method": method, "params": params}); return await f
            await call("Runtime.enable")
            expr = open(expr_file).read().replace("__LANG__", lang)
            r = await call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True, "userGesture": gesture})
            res = r.get("result", {})
            print("evaluate:", res.get("result", {}).get("value") or res.get("exceptionDetails", {}).get("exception", {}).get("description") or r, flush=True)
            await asyncio.sleep(float(wait)); task.cancel()
asyncio.run(main())
