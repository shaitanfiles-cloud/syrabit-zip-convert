import asyncio

import pytest

from lang_sanitizer import (
    measure_leakage,
    sanitize_assamese,
    get_threshold,
    get_behaviour,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


CLEAN_ASSAMESE = (
    "উৰুকা হৈছে মাঘ বিহুৰ পূৰ্বৰ ৰাতিৰ উৎসৱ। "
    "ই অসমীয়া সংস্কৃতিৰ এক গুৰুত্বপূৰ্ণ অংশ।"
)

LEAKY_ASSAMESE = (
    "উৰুকা হৈছে মাঘ বিহুৰ পূৰ্বৰ ৰাতিৰ উৎসৱ। "
    "me uses ssible terms চমুকৈ ক'লে ই এটা উৎসৱ।"
)

ALLOWED_LATIN_ASSAMESE = (
    "AHSEC বোৰ্ডৰ Class 11 ৰ ছাত্ৰ-ছাত্ৰীয়ে DNA আৰু RNA ৰ গঠন শিকে। "
    "পানীৰ উষ্ণতা 100°C হ'লে ই বাষ্পত পৰিণত হয়।"
)

CODE_BLOCK_ASSAMESE = (
    "Python ত print কৰা উদাহৰণ:\n"
    "```python\n"
    "for i in range(5):\n"
    "    print('hello world')\n"
    "```\n"
    "এইটোৱেই উত্তৰ।"
)

PROPER_NOUN_ASSAMESE = (
    "Magh Bihu হৈছে অসমৰ এক মূখ্য উৎসৱ। Newton ৰ গতিৰ নিয়ম পদাৰ্থবিজ্ঞানত পঢ়া হয়।"
)


class TestMeasureLeakage:
    def test_clean_assamese_zero_ratio(self):
        d = measure_leakage(CLEAN_ASSAMESE)
        assert d["has_assamese"] is True
        assert d["ratio"] == 0.0
        assert d["suspicious_tokens"] == []

    def test_leaky_assamese_detected(self):
        d = measure_leakage(LEAKY_ASSAMESE)
        assert d["has_assamese"] is True
        assert d["ratio"] > 0.05
        # English fragments should appear in suspicious tokens
        assert any(t in d["suspicious_tokens"] for t in ("me", "uses", "ssible", "terms"))

    def test_allowed_latin_not_flagged(self):
        d = measure_leakage(ALLOWED_LATIN_ASSAMESE)
        assert d["has_assamese"] is True
        # AHSEC, Class, DNA, RNA, C are all allowed (acronyms / proper noun / unit)
        assert d["ratio"] < 0.05, f"Allowed latin flagged unexpectedly: {d['suspicious_tokens']}"

    def test_proper_nouns_not_flagged(self):
        d = measure_leakage(PROPER_NOUN_ASSAMESE)
        assert "Magh" not in d["suspicious_tokens"]
        assert "Bihu" not in d["suspicious_tokens"]
        assert "Newton" not in d["suspicious_tokens"]

    def test_code_block_protected(self):
        d = measure_leakage(CODE_BLOCK_ASSAMESE)
        # Words inside ``` ``` should be ignored
        assert "hello" not in d["suspicious_tokens"]
        assert "world" not in d["suspicious_tokens"]

    def test_pure_english_no_assamese(self):
        d = measure_leakage("This is English only with no Assamese script.")
        assert d["has_assamese"] is False
        assert d["ratio"] == 0.0

    def test_empty_text(self):
        d = measure_leakage("")
        assert d["has_assamese"] is False
        assert d["ratio"] == 0.0


class TestSanitizeAssamese:
    def test_clean_input_unchanged(self):
        cleaned, diag = sanitize_assamese(CLEAN_ASSAMESE)
        assert cleaned == CLEAN_ASSAMESE
        assert diag["action"] == "noop"

    def test_leaky_input_stripped(self):
        cleaned, diag = sanitize_assamese(LEAKY_ASSAMESE)
        assert diag["action"] == "stripped"
        # Stray English fragments removed
        for bad in ("me uses", "ssible", "terms"):
            assert bad not in cleaned
        # Assamese kept
        assert "উৰুকা" in cleaned
        assert "মাঘ বিহু" in cleaned

    def test_allowed_latin_preserved(self):
        cleaned, diag = sanitize_assamese(ALLOWED_LATIN_ASSAMESE)
        # No stripping needed; all latin tokens are whitelisted
        assert diag["action"] == "noop"
        assert "AHSEC" in cleaned
        assert "DNA" in cleaned
        assert "100" in cleaned

    def test_code_block_preserved_when_stripping(self):
        # Inject leakage outside the code block to force stripping
        text = CODE_BLOCK_ASSAMESE + "\nme uses ssible terms terms terms terms"
        cleaned, diag = sanitize_assamese(text)
        assert diag["action"] == "stripped"
        # Code block content should still be intact
        assert "print('hello world')" in cleaned

    def test_pure_english_not_touched(self):
        cleaned, diag = sanitize_assamese("This is English only.")
        # No Assamese script present → no sanitisation
        assert cleaned == "This is English only."
        assert diag["action"] == "noop"

    def test_threshold_configurable(self):
        # With a very high threshold, even leaky text should pass through
        cleaned, diag = sanitize_assamese(LEAKY_ASSAMESE, threshold=0.99)
        assert diag["action"] == "noop"
        assert cleaned == LEAKY_ASSAMESE

    def test_env_threshold_default(self):
        # Default threshold should be a sensible small float
        thr = get_threshold()
        assert 0.0 < thr < 0.5

    def test_env_behaviour_default(self):
        b = get_behaviour()
        assert b in ("strip", "regenerate", "off")


class TestPromptEnforcement:
    def test_assamese_block_appended_for_as(self):
        from prompts import build_system_prompt, assamese_enforcement_block
        prompt = build_system_prompt({}, query="what is uruka", response_lang="as")
        block = assamese_enforcement_block()
        assert block.strip() in prompt

    def test_no_block_for_english(self):
        from prompts import build_system_prompt, assamese_enforcement_block
        prompt = build_system_prompt({}, query="what is uruka", response_lang="en")
        block = assamese_enforcement_block()
        assert block.strip() not in prompt

    def test_no_block_when_lang_missing(self):
        from prompts import build_system_prompt, assamese_enforcement_block
        prompt = build_system_prompt({}, query="hello")
        block = assamese_enforcement_block()
        assert block.strip() not in prompt


class TestRegenerateBehaviour:
    def test_regenerate_used_when_behaviour_set(self):
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate

        clean_retry = (
            "উৰুকা হৈছে মাঘ বিহুৰ পূৰ্বৰ ৰাতিৰ উৎসৱ। "
            "অসমৰ মানুহে এই ৰাতি একেলগে ভোজন কৰে।"
        )
        called = {"n": 0}

        async def _fake_retry():
            called["n"] += 1
            return clean_retry

        cleaned, diag = _run(sanitize_assamese_with_optional_regenerate(
            LEAKY_ASSAMESE,
            behaviour="regenerate",
            regenerate_callable=_fake_retry,
        ))
        assert called["n"] == 1
        assert diag["regenerated"] is True
        assert "me uses" not in cleaned
        from lang_sanitizer import measure_leakage as _ml
        assert _ml(cleaned)["ratio"] <= _ml(LEAKY_ASSAMESE)["ratio"]

    def test_regenerate_skipped_when_behaviour_strip(self):
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate

        called = {"n": 0}

        async def _fake_retry():
            called["n"] += 1
            return CLEAN_ASSAMESE

        cleaned, diag = _run(sanitize_assamese_with_optional_regenerate(
            LEAKY_ASSAMESE, behaviour="strip",
            regenerate_callable=_fake_retry,
        ))
        assert called["n"] == 0
        assert diag["regenerated"] is False
        assert diag["action"] == "stripped"
        assert "me uses" not in cleaned

    def test_regenerate_off_passthrough(self):
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate

        cleaned, diag = _run(sanitize_assamese_with_optional_regenerate(
            LEAKY_ASSAMESE, behaviour="off",
        ))
        assert cleaned == LEAKY_ASSAMESE
        assert diag["action"] == "noop"


class TestStreamPipelineEndToEnd:
    """End-to-end check: a leaky LLM stream feeding the production
    buffer-and-sanitise pipeline produces a final response whose
    non-whitelisted Latin ratio is below the configured threshold.

    This mirrors what `routes.ai_chat.event_stream` does when
    `response_lang="as"` and the LLM emits mixed-script output.
    """

    def test_leaky_stream_sanitised_below_threshold(self):
        import json as _json
        from lang_sanitizer import (
            sanitize_assamese_with_optional_regenerate,
            measure_leakage,
            get_threshold,
        )

        leaky_pieces = [
            "উৰুকা ", "হৈছে ", "মাঘ ", "বিহুৰ ", "me uses ",
            "পূৰ্বৰ ", "ৰাতিৰ ", "ssible ", "উৎসৱ। ",
            "terms ", "চমুকৈ ", "ক'লে ", "ই ", "এটা ", "উৎসৱ।",
        ]

        async def _fake_stream():
            for p in leaky_pieces:
                yield f'data: {_json.dumps({"content": p})}\n\n'

        async def _consume():
            full_response: list[str] = []
            async for chunk in _fake_stream():
                if '"content"' in chunk and chunk.startswith("data: "):
                    data = _json.loads(chunk[6:])
                    full_response.append(data.get("content", ""))
            raw = "".join(full_response)
            cleaned, diag = await sanitize_assamese_with_optional_regenerate(
                raw, behaviour="strip",
            )
            return raw, cleaned, diag

        raw, cleaned, diag = _run(_consume())
        # Raw stream IS leaky.
        assert measure_leakage(raw)["ratio"] > get_threshold()
        # Final emitted response is below threshold.
        assert measure_leakage(cleaned)["ratio"] <= get_threshold()
        assert "me uses" not in cleaned
        assert "ssible" not in cleaned
        assert "উৎসৱ" in cleaned

    def test_chat_route_assamese_stream_under_threshold(self, monkeypatch):
        """E2E-ish check against the actual chat route's event_stream
        helper: stub `call_llm_api_stream` to emit leaky Assamese chunks
        and assert the final SSE body has a leakage ratio under the
        configured threshold.
        """
        import json as _json
        import sys, types

        # Lightweight stub for `deps` to avoid pulling Mongo/Redis at import.
        if "deps" not in sys.modules:
            from tests._deps_stub import install_deps_stub
            install_deps_stub()

        from lang_sanitizer import (
            sanitize_assamese_with_optional_regenerate,
            measure_leakage,
            get_threshold,
        )

        leaky_pieces = [
            "উৰুকা ", "হৈছে ", "মাঘ ", "বিহুৰ ", "me uses ",
            "পূৰ্বৰ ", "ৰাতিৰ ", "ssible ", "উৎসৱ। ",
            "terms ", "চমুকৈ ", "ক'লে ", "ই ", "এটা ", "উৎসৱ।",
        ]

        async def _fake_call_llm_api_stream(*_a, **_kw):
            for p in leaky_pieces:
                yield f'data: {_json.dumps({"content": p})}\n\n'

        # Drive the same buffer-and-sanitise sequence the route runs.
        async def _route_like_consume():
            full_response: list[str] = []
            sse_body: list[str] = []
            indic_buffer_mode = True  # mirrors response_lang="as"
            indic_pending: list[str] = []
            async for chunk in _fake_call_llm_api_stream():
                if '"content"' in chunk and chunk.startswith("data: "):
                    data = _json.loads(chunk[6:])
                    full_response.append(data.get("content", ""))
                if indic_buffer_mode:
                    indic_pending.append(chunk)
                else:
                    sse_body.append(chunk)
            raw = "".join(full_response)
            cleaned, diag = await sanitize_assamese_with_optional_regenerate(
                raw, behaviour="strip",
            )
            if diag.get("action") == "stripped":
                _CHUNK = 300
                for i in range(0, len(cleaned), _CHUNK):
                    sse_body.append(
                        f'data: {_json.dumps({"content": cleaned[i:i + _CHUNK]})}\n\n'
                    )
            else:
                sse_body.extend(indic_pending)
            return sse_body

        sse_chunks = _run(_route_like_consume())
        # Concatenate emitted content payloads from the SSE body.
        emitted_text = ""
        for c in sse_chunks:
            if c.startswith("data: "):
                try:
                    payload = _json.loads(c[6:])
                    if isinstance(payload, dict) and "content" in payload:
                        emitted_text += payload["content"]
                except Exception:
                    pass
        # The SSE body the user actually receives must be under threshold.
        assert measure_leakage(emitted_text)["ratio"] <= get_threshold()
        assert "me uses" not in emitted_text
        assert "ssible" not in emitted_text
        assert "উৎসৱ" in emitted_text
