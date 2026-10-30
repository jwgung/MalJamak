"""Groq 호출: 확정 문장 교정·자막 번역(LLM)과 현장 자막 대체 인식 엔진(Whisper)."""

import asyncio
import os
import re

import aiohttp

# VK_GROQ_URL 로 다른 OpenAI 호환 엔드포인트(또는 테스트 서버)를 쓸 수 있다.
GROQ_URL = os.environ.get("VK_GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_STT_URL = os.environ.get("VK_GROQ_STT_URL", "https://api.groq.com/openai/v1/audio/transcriptions")

# Whisper 는 말소리가 없거나 음악만 있는 구간에서 방송 끝인사 같은 글을 지어낸다. 결과가 통째로 이런 글이면 버린다.
# 실제로도 하는 말("감사합니다")은 넣지 않는다 — 문장이 빠지는 것이 잘못 나오는 것보다 나쁘다.
_HALLUCINATION = re.compile(
    r"^\s*(시청해\s*주셔서\s*감사합니다|구독과\s*좋아요|(MBC|KBS|SBS)\s*뉴스\s*\S*\s*(입니다)?|Thanks? for watching)[\s.!。]*$",
    re.IGNORECASE)


def whisper_text(data: dict, no_speech: float = 0.6, min_logprob: float = -1.0) -> str:
    """verbose_json 응답에서 말소리가 아닐 가능성이 높거나 확신이 아주 낮은 구간을 빼고 글을 잇는다."""
    if not isinstance(data, dict):
        return ""
    segments = data.get("segments")
    if not isinstance(segments, list):
        text = str(data.get("text") or "")
    else:
        def keep(s) -> bool:
            try:
                return float(s.get("no_speech_prob", 0)) <= no_speech and float(s.get("avg_logprob", 0)) >= min_logprob
            except (TypeError, ValueError):
                return False
        text = " ".join(str(s.get("text") or "").strip() for s in segments if isinstance(s, dict) and keep(s))
    text = " ".join(text.split())
    return "" if _HALLUCINATION.match(text) else text


# 프롬프트 안에서 쓸 언어 이름 (언어 코드 앞부분 → 이름). 목록에 없는 언어는 코드를 그대로 쓴다.
LANG_NAMES = {
    "ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어", "es": "스페인어", "fr": "프랑스어", "de": "독일어",
    "pt": "포르투갈어", "it": "이탈리아어", "ru": "러시아어", "uk": "우크라이나어", "mn": "몽골어", "vi": "베트남어",
    "th": "태국어", "id": "인도네시아어", "ms": "말레이어", "fil": "필리핀어", "tl": "필리핀어", "hi": "힌디어",
    "ar": "아랍어", "tr": "튀르키예어", "ne": "네팔어",
}


def lang_name(code: str) -> str:
    base = str(code or "").split("-")[0].lower()
    if code == "zh-TW":
        return "중국어(번체)"
    return LANG_NAMES.get(base, code or "원어")


def correct_prompt(strength: str, lang: str = "ko-KR") -> str:
    """교정 지시문. 말하는 언어에 맞춰 만들고, 한국어 받아쓰기 전용 지시는 한국어일 때만 넣는다.
    실제 PC 테스트에서 적극적 + 단어장이 고유명사("크로키는" → "Groq")를 더 잘 고쳤다."""
    name = lang_name(lang)
    korean = str(lang).startswith("ko")
    lines = [f"너는 음성 인식(STT) 결과 교정기다. 입력은 사용자가 {name}로 말한 내용을 받아쓴 텍스트다. 출력도 {name}로 쓴다."]
    if strength == "aggressive":
        lines[0] += "\n발음이 비슷한 다른 단어로 잘못 들린 부분이 자주 섞여 있다."
        lines.append("- 문맥상 어색한 단어는 발음이 비슷하면서 문맥에 맞는 단어로 바꾼다."
                     + (' (예: 앞뒤가 다운로드 이야기인데 "다시 봤습니다" → "다시 받습니다")' if korean else ""))
    else:
        lines.append("- 잘못 들린 단어를 문맥에 맞게 고친다.")
    if korean:
        lines.append("- 한글로 적힌 영어 기술 용어·고유명사는 원래 영어 표기로 바꾼다. (예: 리액트 → React, 깃허브 → GitHub)")
        lines.append('- 띄어쓰기, 맞춤법, 문장부호를 고친다. "음", "어", "그러니까" 같은 군말은 지운다.')
    else:
        lines.append("- 띄어쓰기, 맞춤법, 대소문자, 문장부호를 고친다. 뜻 없는 군말(um, uh 같은 말)은 지운다.")
    lines.append("- 의미를 바꾸거나 내용을 덧붙이지 않는다. 질문이어도 답하지 않는다."
                 + (" 어떻게 고쳐야 할지 확신이 없는 부분은 원문 그대로 둔다." if strength == "aggressive" else ""))
    lines.append("- 교정된 텍스트만 출력한다.")
    return "\n".join(lines)


def translate_prompt(source: str, target: str = "ko-KR") -> str:
    return (f"너는 실시간 자막 번역가다. 입력 문장({lang_name(source)})을 자연스러운 {lang_name(target)} 자막으로 번역한다.\n"
            "- 음성 인식 결과라 오타나 끊긴 문장이 있을 수 있으니 문맥으로 보정한다.\n"
            "- 번역문만 출력한다. 설명, 따옴표, 원문을 붙이지 않는다.")


class Groq:
    """Groq 호출: 확정 문장 교정·번역과 Whisper 받아쓰기. 실패하면 None 을 돌려 호출부가 원문/기본 경로를 쓰게 한다."""

    def __init__(self, api_key: str, model: str, timeout: float):
        self.api_key = api_key
        self.model = model
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _chat(self, system: str, user: str) -> str | None:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,  # 같은 입력에 같은 교정 결과
        }
        if self.model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        try:
            async with self._session.post(
                GROQ_URL, json=body, headers={"Authorization": f"Bearer {self.api_key}"}
            ) as resp:
                if resp.status != 200:
                    print(f"[groq] HTTP {resp.status}: {(await resp.text())[:200]}", flush=True)
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            print(f"[groq] {type(err).__name__}: {err}", flush=True)
            return None
        text = (data["choices"][0]["message"].get("content") or "").strip()
        return text or None

    async def correct(self, text: str, strength: str = "aggressive", lang: str = "ko-KR") -> str | None:
        return await self._chat(correct_prompt(strength, lang), text)

    async def translate(self, text: str, source: str, context: list[str],
                        target: str = "ko-KR") -> str | None:
        user = text
        if context:
            user = "직전 자막(참고용, 번역하지 말 것):\n" + "\n".join(context) + "\n\n번역할 문장:\n" + text
        return await self._chat(translate_prompt(source, target), user)

    async def transcribe(self, wav: bytes, lang: str, prompt: str, model: str) -> str | None:
        """현장 자막 대체 엔진: 말 한 토막(WAV)을 Whisper 로 받아쓴다. prompt 는 직전 자막(이어지는 말투·고유명사 표기).
        한도(429)에 걸리면 알려 준 시간(최대 10초)만큼 기다렸다가 한 번 더 보낸다 — 문장이 통째로 빠지지 않게."""
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        for attempt in range(2):
            form = aiohttp.FormData()
            form.add_field("file", wav, filename="speech.wav", content_type="audio/wav")
            form.add_field("model", model)
            form.add_field("language", str(lang or "ko").split("-")[0].lower())
            form.add_field("response_format", "verbose_json")
            form.add_field("temperature", "0")
            if prompt:
                form.add_field("prompt", prompt)
            try:
                async with self._session.post(GROQ_STT_URL, data=form, timeout=aiohttp.ClientTimeout(total=20),
                                              headers={"Authorization": f"Bearer {self.api_key}"}) as resp:
                    if resp.status == 429 and attempt == 0:
                        wait = min(10.0, float(resp.headers.get("retry-after") or 2))
                        print(f"[groq] 음성 인식 한도, {wait:.0f}초 뒤 다시 보냄", flush=True)
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        print(f"[groq] STT HTTP {resp.status}: {(await resp.text())[:200]}", flush=True)
                        return None
                    return whisper_text(await resp.json())
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                print(f"[groq] STT {type(err).__name__}: {err}", flush=True)
                return None
        return None

    async def close(self) -> None:
        if self._session:
            await self._session.close()
