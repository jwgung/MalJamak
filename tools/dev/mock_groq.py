import asyncio, sys
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
stt_count = 0
async def transcribe(req):
    # Whisper 받아쓰기 흉내: 받은 WAV 길이를 글로 돌려준다 ("[STT 3] 6.2초 ko")
    global stt_count
    form = await req.post()
    wav = form["file"].file.read()
    seconds = (len(wav) - 44) / 2 / 16000
    stt_count += 1
    text = f"[STT {stt_count}] {seconds:.1f}초 {form.get('language')}"
    print(f"[mock] STT: {text} model={form.get('model')} prompt={form.get('prompt', '')[-40:]!r}", flush=True)
    return web.json_response({"text": text, "segments": [{"text": text, "no_speech_prob": 0.01, "avg_logprob": -0.1}]})
app = web.Application(); app.router.add_post("/v1/chat/completions", chat)
app.router.add_post("/v1/audio/transcriptions", transcribe)
web.run_app(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8797, print=None)  # 포트: 첫 인자 (기본 8797)
