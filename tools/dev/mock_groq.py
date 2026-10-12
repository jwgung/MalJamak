import asyncio
from aiohttp import web
async def chat(req):
    body = await req.json()
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    tag = "KO" if "자막" in system else "FIX"
    text = user.splitlines()[-1]
    if tag == "FIX":
        text = text.replace("리액트", "React").replace("깃허브", "GitHub")
    print("PROMPT1", system.splitlines()[0][:80], flush=True)
    print(f"[mock] {tag}: {user.splitlines()[-1]!r} temp={body.get('temperature')} model={body['model']} "
          f"aggressive={'발음이 비슷한' in system} glossary={system.split('용어 사전')[-1].strip()[:80] if '용어 사전' in system else None}", flush=True)
    return web.json_response({"choices": [{"message": {"content": f"[{tag}] {text}"}}]})
app = web.Application(); app.router.add_post("/v1/chat/completions", chat)
web.run_app(app, host="127.0.0.1", port=8797, print=None)
