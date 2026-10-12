"""엔진 페이지에 붙어: 합치기에 들어오는 한국어 결과와 걸러진 이유를 기록한다."""
import asyncio, json, sys, time, aiohttp
SECONDS, OUT = float(sys.argv[1]), sys.argv[2]
PATCH = r"""
(() => {
  const orig = InterpretMerger.prototype.add;
  InterpretMerger.prototype.add = function (text) { const r = orig.call(this, text); console.log("MERGE\t" + text + "\t=>\t" + r.join(" ")); return r; };
  const origReport = report; window.report = (w, e) => { console.log("REPORT\t" + w + "\t" + e); origReport(w, e); };
  window.VK_DEBUG = true;
  return "patched";
})()
"""
async def main():
    async with aiohttp.ClientSession() as s:
        pages = await (await s.get("http://localhost:" + __import__("os").environ.get("VK_ENGINE_DEVTOOLS", "9335") + "/json/list")).json()
        url = next(p for p in pages if p["type"] == "page" and "/engine" in p["url"])["webSocketDebuggerUrl"]
        async with s.ws_connect(url, max_msg_size=0) as ws:
            n = 0
            async def call(method, params={}):
                nonlocal n; n += 1; await ws.send_json({"id": n, "method": method, "params": params})
            await call("Runtime.enable"); await call("Runtime.evaluate", {"expression": PATCH})
            t0 = time.time(); out = open(OUT, "w", encoding="utf-8")
            while time.time() - t0 < SECONDS:
                try: m = await asyncio.wait_for(ws.receive(), 1)
                except asyncio.TimeoutError: continue
                d = json.loads(m.data)
                if d.get("method") == "Runtime.consoleAPICalled":
                    out.write(f"{time.time()-t0:.1f}\t" + " ".join(str(a.get("value", a.get("description"))) for a in d["params"]["args"]) + "\n"); out.flush()
                elif d.get("method") == "Runtime.exceptionThrown":
                    out.write(f"{time.time()-t0:.1f}\tEXC\t{d['params']['exceptionDetails'].get('text')} {d['params']['exceptionDetails'].get('exception',{}).get('description','')[:200]}\n")
asyncio.run(main())
