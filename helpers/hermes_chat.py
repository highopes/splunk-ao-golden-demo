"""OpenAI-compatible chat model for vLLM servers that return Hermes-style tool calls as text.

A vLLM server started without ``--enable-auto-tool-choice`` / ``--tool-call-parser``
still renders the request's tools into the prompt (Qwen3's chat template uses the
Hermes format), but returns the model's calls as plain text::

    <tool_call>
    {"name": "get_patient_info", "arguments": {"patient_id": "P001"}}
    </tool_call>

with ``finish_reason=stop`` and no structured ``tool_calls``. ``HermesToolCallChatOpenAI``
parses those blocks into ``AIMessage.tool_calls`` inside ``_generate``/``_agenerate``,
i.e. before LangChain callbacks (and therefore Galileo's LLM span) see the result.
Requests disable Qwen3 "thinking" and any leftover ``<think>`` text is removed.
Streaming is disabled so every call goes through the parsing path.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
NO_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


def strip_thinking(text: str) -> str:
    """Remove ``<think>`` blocks, including a dangling closing tag from the prompt template."""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1]
    return cleaned.replace("<think>", "").strip()


def _parse_call(body: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    args = payload.get("arguments", payload.get("parameters", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            return None
    if not isinstance(name, str) or not name.strip() or not isinstance(args, dict):
        return None
    return {
        "name": name.strip(),
        "args": args,
        "id": f"call_{uuid.uuid4().hex[:24]}",
        "type": "tool_call",
    }


def parse_hermes_tool_calls(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Return ``(remaining_text, tool_calls)`` for Hermes ``<tool_call>`` blocks.

    Valid blocks are removed from the text; a block whose JSON cannot be parsed
    is left in the text verbatim and produces no tool call (never raises).
    """
    text = strip_thinking(text or "")
    calls: List[Dict[str, Any]] = []

    def _replace(match: "re.Match[str]") -> str:
        call = _parse_call(match.group(1))
        if call is None:
            return match.group(0)
        calls.append(call)
        return ""

    remaining = _TOOL_CALL_RE.sub(_replace, text)
    return remaining.strip(), calls


def _convert_message(message: Any) -> Any:
    if not isinstance(message, AIMessage) or message.tool_calls or not isinstance(message.content, str):
        return message
    content, calls = parse_hermes_tool_calls(message.content)
    if not calls and content == message.content:
        return message
    response_metadata = dict(message.response_metadata or {})
    if calls:
        response_metadata["finish_reason"] = "tool_calls"
        response_metadata["tool_call_format"] = "hermes_text"
    return AIMessage(
        content=content,
        tool_calls=calls,
        additional_kwargs=dict(message.additional_kwargs or {}),
        response_metadata=response_metadata,
        id=message.id,
        name=message.name,
        usage_metadata=message.usage_metadata,
    )


def convert_chat_result(result: ChatResult) -> ChatResult:
    """Apply Hermes parsing and ``<think>`` cleanup to every generation."""
    generations = []
    for generation in result.generations:
        message = _convert_message(generation.message)
        if message is generation.message:
            generations.append(generation)
        else:
            generations.append(ChatGeneration(message=message, generation_info=generation.generation_info))
    return ChatResult(generations=generations, llm_output=result.llm_output)


class HermesToolCallChatOpenAI(ChatOpenAI):
    """``ChatOpenAI`` for vLLM endpoints without a server-side tool-call parser."""

    def __init__(self, **kwargs: Any) -> None:
        extra_body = dict(kwargs.pop("extra_body", None) or {})
        template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
        template_kwargs.setdefault("enable_thinking", False)
        extra_body["chat_template_kwargs"] = template_kwargs
        kwargs.setdefault("disable_streaming", True)
        super().__init__(extra_body=extra_body, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        return convert_chat_result(super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs))

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        return convert_chat_result(result)
