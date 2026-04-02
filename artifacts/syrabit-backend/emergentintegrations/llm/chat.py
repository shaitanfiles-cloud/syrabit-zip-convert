"""
Universal LLM adapter — supports Groq and OpenAI providers.
Automatically selects the right client based on provider setting.
"""
import asyncio
import logging

_log = logging.getLogger(__name__)

# Suppress verbose httpx / openai request logs — they can echo auth headers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


class _MaskedKey:
    """Wraps an API key so it is never printed or repr'd in plain text."""
    __slots__ = ("_key",)

    def __init__(self, key: str):
        self._key = key

    def __str__(self) -> str:
        k = self._key
        return f"{k[:6]}…{k[-4:]}" if len(k) > 12 else "***"

    def __repr__(self) -> str:
        return f"<MaskedKey {self!s}>"

    def reveal(self) -> str:
        return self._key


class UserMessage:
    def __init__(self, text: str):
        self.text = text


class LlmChat:
    def __init__(self, api_key: str, session_id: str = "", system_message: str = ""):
        self._masked = _MaskedKey(api_key)
        self.session_id = session_id
        self.system_message = system_message
        self._provider = "groq"
        self._model = "llama-3.1-8b-instant"

    @property
    def api_key(self) -> str:
        return self._masked.reveal()

    def __repr__(self) -> str:
        return (f"LlmChat(provider={self._provider!r}, model={self._model!r}, "
                f"key={self._masked!s})")

    def with_model(self, provider: str, model: str) -> "LlmChat":
        self._provider = provider or "groq"
        self._model = model or "llama-3.1-8b-instant"
        return self

    async def send_message(self, message: UserMessage) -> str:
        messages = []
        if self.system_message:
            messages.append({"role": "system", "content": self.system_message})
        messages.append({"role": "user", "content": message.text})

        if self._provider == "emergent":
            return await self._call_emergent(messages)
        elif self._provider == "openai":
            return await self._call_openai(messages)
        elif self._provider == "fireworksai":
            return await self._call_fireworks(messages)
        elif self._provider == "cerebras":
            return await self._call_cerebras(messages)
        else:
            return await self._call_groq(messages)

    async def send_messages(self, messages: list) -> str:
        if self._provider == "emergent":
            return await self._call_emergent(messages)
        elif self._provider == "openai":
            return await self._call_openai(messages)
        elif self._provider == "fireworksai":
            return await self._call_fireworks(messages)
        elif self._provider == "cerebras":
            return await self._call_cerebras(messages)
        else:
            return await self._call_groq(messages)

    async def stream_messages(self, messages: list, max_tokens: int = 2048):
        if self._provider == "emergent":
            async for token in self._stream_emergent(messages, max_tokens):
                yield token
        elif self._provider == "openai":
            async for token in self._stream_openai(messages, max_tokens):
                yield token
        elif self._provider == "fireworksai":
            async for token in self._stream_fireworks(messages, max_tokens):
                yield token
        elif self._provider == "cerebras":
            async for token in self._stream_cerebras(messages, max_tokens):
                yield token
        else:
            async for token in self._stream_groq(messages, max_tokens):
                yield token

    async def _call_groq(self, messages: list) -> str:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=self.api_key, max_retries=0, timeout=8.0)
        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=2048,
        )
        return response.choices[0].message.content or ""

    async def _stream_groq(self, messages: list, max_tokens: int = 2048):
        from groq import AsyncGroq
        client = AsyncGroq(api_key=self.api_key, max_retries=0, timeout=8.0)
        stream = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            temperature=0.1,
            top_p=0.95,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def _call_openai(self, messages: list) -> str:
        import openai
        client = openai.AsyncOpenAI(api_key=self.api_key)
        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    async def _stream_openai(self, messages: list, max_tokens: int = 1024):
        import openai
        client = openai.AsyncOpenAI(api_key=self.api_key)
        stream = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            temperature=0.1,
            top_p=0.95,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def _call_fireworks(self, messages: list) -> str:
        import openai
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.fireworks.ai/inference/v1"
        )
        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    async def _stream_fireworks(self, messages: list, max_tokens: int = 1024):
        import openai
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.fireworks.ai/inference/v1"
        )
        stream = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            temperature=0.1,
            top_p=0.95,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def _call_cerebras(self, messages: list) -> str:
        import openai
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.cerebras.ai/v1"
        )
        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    async def _stream_cerebras(self, messages: list, max_tokens: int = 2048):
        import openai
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.cerebras.ai/v1"
        )
        stream = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            temperature=0.1,
            top_p=0.95,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def _call_emergent(self, messages: list) -> str:
        import openai, os
        base_url = os.environ.get('EMERGENT_BASE_URL', 'https://api.emergent.sh/v1').strip()
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_url,
        )
        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    async def _stream_emergent(self, messages: list, max_tokens: int = 1024):
        import openai, os
        base_url = os.environ.get('EMERGENT_BASE_URL', 'https://api.emergent.sh/v1').strip()
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_url,
        )
        stream = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            temperature=0.1,
            top_p=0.95,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content
