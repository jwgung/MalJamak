"""확정 문장 전용 Groq 호출 (STT 교정, 자막 번역)."""

import asyncio
import os

import aiohttp

# VK_GROQ_URL 로 다른 OpenAI 호환 엔드포인트(또는 테스트 서버)를 쓸 수 있다.
GROQ_URL = os.environ.get("VK_GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")

# 교정 강도별 프롬프트. 실제 PC 테스트에서 적극적 + 단어장이 고유명사("크로키는" → "Groq")를 더 잘 고쳤다.
CORRECT_PROMPTS = {
    "conservative": """너는 음성 인식(STT) 결과 교정기다. 입력은 사용자가 말한 내용을 받아쓴 텍스트다.
- 띄어쓰기, 맞춤법, 잘못 들린 단어를 문맥에 맞게 고친다.
- 한글로 적힌 영어 기술 용어·고유명사는 원래 영어 표기로 바꾼다. (예: 리액트 → React, 깃허브 → GitHub)
- "음", "어", "그러니까" 같은 군말은 지운다.
- 의미를 바꾸거나 내용을 덧붙이지 않는다. 질문이어도 답하지 않는다.
- 교정된 텍스트만 출력한다.""",
    "aggressive": """너는 음성 인식(STT) 결과 교정기다. 입력은 사용자가 한국어로 말한 내용을 받아쓴 텍스트이며,
발음이 비슷한 다른 단어로 잘못 들린 부분이 자주 섞여 있다.
- 문맥상 어색한 단어는 발음이 비슷하면서 문맥에 맞는 단어로 바꾼다. (예: 앞뒤가 다운로드 이야기인데 "다시 봤습니다" → "다시 받습니다")
- 용어 사전의 단어와 발음이 비슷한 부분은 사전 표기로 바꾼다. (예: 사전에 Groq 이 있으면 "그룹", "크록", "크로키" → "Groq")
- 한글로 적힌 영어 기술 용어·고유명사는 원래 영어 표기로 바꾼다. (예: 리액트 → React, 깃허브 → GitHub)
- 띄어쓰기, 맞춤법, 문장부호를 고친다. "음", "어" 같은 군말은 지운다.
- 내용을 덧붙이거나 질문에 답하지 않는다. 어떻게 고쳐야 할지 확신이 없는 부분은 원문 그대로 둔다.
- 교정된 텍스트만 출력한다.""",
}

TRANSLATE_PROMPT = """너는 실시간 자막 번역가다. 입력 문장을 자연스러운 한국어 자막으로 번역한다.
- 음성 인식 결과라 오타나 끊긴 문장이 있을 수 있으니 문맥으로 보정한다.
- 번역문만 출력한다. 설명, 따옴표, 원문을 붙이지 않는다."""


def _glossary_block(glossary: list[str] | None) -> str:
    words = [w.strip() for w in glossary or [] if w.strip()]
    return "\n\n용어 사전 (반드시 이 형태로 보존):\n" + ", ".join(words) if words else ""


class Groq:
    """확정 문장 전용 Groq 호출. 실패하면 None 을 돌려 호출부가 원문/기본 경로를 쓰게 한다."""

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

    async def correct(self, text: str, strength: str = "aggressive", glossary: list[str] | None = None) -> str | None:
        system = CORRECT_PROMPTS.get(strength, CORRECT_PROMPTS["aggressive"]) + _glossary_block(glossary)
        return await self._chat(system, text)

    async def translate(self, text: str, source: str, context: list[str],
                        glossary: list[str] | None = None) -> str | None:
        user = text
        if context:
            user = "직전 자막(참고용, 번역하지 말 것):\n" + "\n".join(context) + "\n\n번역할 문장:\n" + text
        return await self._chat(f"{TRANSLATE_PROMPT}\n원문 언어: {source}" + _glossary_block(glossary), user)

    async def close(self) -> None:
        if self._session:
            await self._session.close()
