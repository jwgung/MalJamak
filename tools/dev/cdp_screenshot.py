"""CDP 로 지정 페이지를 열고 (선택) 스크립트를 실행한 뒤 스크린샷을 저장한다."""
import asyncio, base64, json, sys, aiohttp
port, url, out, width, height = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
script = open(sys.argv[6]).read() if len(sys.argv) > 6 else ""
async def main():
    async with aiohttp.ClientSession() as s:
        pages = await (await s.get(f"http://localhost:{port}/json/list")).json()
        ws_url = next(p for p in pages if p["type"] == "page")["webSocketDebuggerUrl"]
        async with s.ws_connect(ws_url, max_msg_size=0) as ws:
            n = 0
            async def call(method, params={}):
                nonlocal n; n += 1; i = n
                await ws.send_json({"id": i, "method": method, "params": params})
                while True:
                    d = json.loads((await ws.receive()).data)
                    if d.get("id") == i: return d
            await call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
            import os
            if os.environ.get("DARK"):
                await call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]})
            await call("Page.navigate", {"url": url}); await asyncio.sleep(3)
            if script:
                r = await call("Runtime.evaluate", {"expression": script, "awaitPromise": True, "returnByValue": True})
                print("script:", r.get("result", {}).get("result", {}).get("value"))
            await asyncio.sleep(1)
            r = await call("Page.captureScreenshot", {"format": "png"})
            open(out, "wb").write(base64.b64decode(r["result"]["data"]))
            print("saved", out)
asyncio.run(main())
