"""Claude API 래퍼.

- 프롬프트는 app/llm/prompts/*.md 파일에서 읽는다(버전 관리 대상).
- 공고문·양식·평가표처럼 반복 참조하는 긴 텍스트는 system 블록에 두고 prompt caching을 건다.
- 긴 출력은 스트리밍 후 get_final_message()로 받는다.
- API 키는 .env의 ANTHROPIC_API_KEY로만 읽고 로그에 남기지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.config import PROMPT_DIR, env, load_settings

log = logging.getLogger(__name__)

COMMON_RULES_FILE = "_common.md"


class LLMUnavailable(RuntimeError):
    """API 키 미설정 등으로 LLM을 쓸 수 없을 때."""


class LLMRefused(RuntimeError):
    """모델이 요청을 거절했을 때."""


def load_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if not path.suffix:
        path = path.with_suffix(".md")
    return path.read_text(encoding="utf-8")


def is_available() -> bool:
    return bool(env("ANTHROPIC_API_KEY"))


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


class ClaudeClient:
    def __init__(self, model: str | None = None, effort: str | None = None):
        if not is_available():
            raise LLMUnavailable("ANTHROPIC_API_KEY가 설정되지 않았습니다 (.env 확인)")
        import anthropic

        settings = load_settings()["llm"]
        self.model = model or settings.get("model", "claude-opus-5-5")
        self.effort = effort or settings.get("effort", "high")
        self.use_fallbacks = bool(settings.get("use_fallbacks", True))
        self._client = anthropic.Anthropic()

    def complete(
        self,
        prompt_file: str,
        user_content: str,
        *,
        reference: str | None = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        """prompt_file(.md) + 공통규칙을 system으로, reference(공고문·양식 등 긴 자료)는 캐시 블록으로 보낸다."""
        system = [{"type": "text", "text": load_prompt(COMMON_RULES_FILE) + "\n\n" + load_prompt(prompt_file)}]
        if reference:
            system.append(
                {
                    "type": "text",
                    "text": "<참고자료>\n" + reference + "\n</참고자료>",
                    "cache_control": {"type": "ephemeral"},
                }
            )
        else:
            system[0]["cache_control"] = {"type": "ephemeral"}

        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
        )
        if self.use_fallbacks:
            stream_ctx = self._client.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            stream_ctx = self._client.messages.stream(**kwargs)
        with stream_ctx as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise LLMRefused("모델이 요청을 처리하지 않았습니다. 입력 자료를 확인해 주세요.")
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        usage = message.usage
        log.info(
            "LLM %s in=%s out=%s cache_read=%s",
            prompt_file,
            usage.input_tokens,
            usage.output_tokens,
            getattr(usage, "cache_read_input_tokens", 0),
        )
        return LLMResult(
            text=text,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

    def complete_json(self, prompt_file: str, user_content: str, **kwargs):
        result = self.complete(prompt_file, user_content, **kwargs)
        return parse_json_block(result.text)


def parse_json_block(text: str):
    """응답에서 JSON(```json 블록 우선)을 꺼낸다."""
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidate = match.group(1) if match else text
    candidate = candidate.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = candidate.find(opener), candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("LLM 응답에서 JSON을 찾지 못했습니다")
