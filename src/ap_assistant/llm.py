"""The model abstraction. The grounding loop knows only ModelClient; the provider and model come from the environment.

AP_LLM_MODEL      model name; unset or "offline" selects OfflineModel
AP_LLM_BASE_URL   optional endpoint; default: the OpenAI API
OPENAI_API_KEY    read by the openai SDK
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ModelReply:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_message(self) -> dict:
        """The reply as an assistant message in the chat-completions format, for the next call."""
        message: dict = {"role": "assistant", "content": self.text}
        if self.tool_calls:
            message["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return message


class ModelClient(Protocol):
    name: str

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply: ...


class OpenAIModel:
    def __init__(self, name: str, base_url: str | None = None):
        self.name = name
        self.base_url = base_url
        self._client = None

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        # The client is created on the first call, so a missing API key fails the grounding, not the import.
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self.base_url, timeout=30, max_retries=2)
        response = self._client.chat.completions.create(model=self.name, messages=messages, tools=tools)
        message = response.choices[0].message
        return ModelReply(
            text=message.content,
            tool_calls=[ToolCall(c.id, c.function.name, c.function.arguments) for c in message.tool_calls or []],
        )


DOCUMENT_BLOCK = re.compile(r'<document chunk_id="([^"]+)"[^>]*>\n(.*?)\n</document>', re.DOTALL)
WORD = re.compile(r"[a-z0-9]+")


class OfflineModel:
    """A deterministic stand-in for the LLM, so the project runs without an API key.

    Call 1 asks for one retrieval per required citation. Call 2 cites, for each, the expected section if it was
    retrieved (else the top chunk of that document), quoting the line or sentence that shares most words with the
    finding. It passes validation by construction, so it proves the plumbing, not model quality.
    """

    name = "offline"

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        payload = json.loads(messages[1]["content"])
        required = payload["required_citations"]
        tool_results = [m["content"] for m in messages if m["role"] == "tool"]
        if not tool_results:
            details = {f["check"]: f["detail"] for f in payload["findings"]}
            return ModelReply(
                text=None,
                tool_calls=[
                    ToolCall(
                        id=f"call_{i}",
                        name="retrieve_finance_documents",
                        arguments=json.dumps(
                            {"query": f"{r['document_id']} {r['finding']} {details.get(r['finding'], '')}".strip(), "top_k": 10}
                        ),
                    )
                    for i, r in enumerate(required)
                ],
            )

        retrieved: dict[str, str] = {}
        for content in tool_results:
            for chunk_id, text in DOCUMENT_BLOCK.findall(content):
                retrieved.setdefault(chunk_id, text)

        citations = []
        for r in required:
            expected = f"{r['document_id']}#{r['section']}"
            chunk_id = expected if expected in retrieved else next(
                (c for c in retrieved if c.startswith(f"{r['document_id']}#")), None
            )
            if chunk_id is not None:
                citations.append({"chunk_id": chunk_id, "quote": _best_segment(retrieved[chunk_id], r["finding"]), "finding": r["finding"]})

        parts = [f"Recommended outcome: {payload['outcome']}."]
        parts += [f"{c['finding']}: see {c['chunk_id'].replace('#', ' §')}." for c in citations]
        return ModelReply(text=json.dumps({"explanation": " ".join(parts), "citations": citations}))


def _best_segment(text: str, finding: str) -> str:
    """The line or sentence of the text that shares most words with the finding; verbatim."""
    segments = [s.strip() for line in text.splitlines() for s in re.split(r"(?<=\.)\s+", line) if s.strip()]
    finding_words = set(WORD.findall(finding.lower()))
    return max(segments, key=lambda s: len(finding_words & set(WORD.findall(s.lower()))))


def model_from_env() -> ModelClient:
    name = os.environ.get("AP_LLM_MODEL", "").strip()
    if name in ("", "offline"):
        return OfflineModel()
    return OpenAIModel(name, os.environ.get("AP_LLM_BASE_URL") or None)
