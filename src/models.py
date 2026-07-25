from typing import List, Literal, Optional, Dict, Any, Union
from pydantic import BaseModel, field_validator
import re
import uuid
import time


class ImageUrl(BaseModel):
    url: str  # Can be base64 data URL or file URL


class ContentPartText(BaseModel):
    type: Literal["text"]
    text: str


class ContentPartImage(BaseModel):
    type: Literal["image_url"]
    image_url: ImageUrl


ContentPart = Union[ContentPartText, ContentPartImage]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: Union[str, List[ContentPart]]  # String or multimodal content


class ResponseFormat(BaseModel):
    type: Literal["text", "json_schema"] = "text"
    json_schema: Optional[Dict[str, Any]] = None


# CLI tier aliases (resolved by the Claude CLI itself) — plus any FULL model
# id ("claude-sonnet-5", "claude-opus-4-8", "claude-fable-5",
# "claude-haiku-4-5-20251001", ...) passes straight through to `--model`, so
# picking a new model never needs a gateway redeploy. Anything else 422s.
MODEL_ALIASES = {"sonnet", "opus", "haiku", "fable"}
_FULL_MODEL_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.-]*$")


class ChatCompletionRequest(BaseModel):
    model: str = "sonnet"
    messages: List[ChatMessage]

    @field_validator("model")
    @classmethod
    def _model_alias_or_full_id(cls, v: str) -> str:
        if v in MODEL_ALIASES or _FULL_MODEL_RE.match(v):
            return v
        raise ValueError(
            f"model {v!r} is neither a tier alias "
            f"({', '.join(sorted(MODEL_ALIASES))}) nor a full claude-* "
            f"model id")
    conversation_id: Optional[str] = None
    timeout: Optional[int] = 300  # seconds, max 300
    response_format: Optional[ResponseFormat] = None
    stream: bool = False
    source: str = "unknown"  # Track request origin for usage monitoring
    # None = current default (Read,Grep,Glob,WebSearch). [] = no tools. List = exact set.
    allowed_tools: Optional[List[str]] = None
    # Top-level system prompt (Anthropic/OpenAI convention). When set, fully
    # replaces Claude Code's default agent system prompt. Wins over any
    # role:"system" entries in messages.
    system: Optional[str] = None
    # When true (streaming only), emits extra SSE event types alongside the
    # OpenAI-shaped text deltas: {"type": "thinking"|"tool_use"|"tool_result"}.
    # Lets clients show "AI is searching the web for X" instead of a spinner.
    # Off by default — OpenAI SDK clients may not tolerate unknown event shapes.
    extended_events: bool = False


class Choice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_claude_usage(cls, usage: dict) -> "Usage":
        """Create Usage from Claude's JSON response."""
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        return cls(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens
        )


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage
    conversation_id: Optional[str] = None
    structured_output: Optional[Any] = None

    @classmethod
    def create(cls, model: str, content: str, session_id: str = "", usage_data: dict = None, structured_output: Any = None) -> "ChatCompletionResponse":
        usage = Usage.from_claude_usage(usage_data) if usage_data else Usage()

        return cls(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model=model,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                )
            ],
            usage=usage,
            structured_output=structured_output,
        )


# Usage tracking models
class UsageRecord(BaseModel):
    timestamp: str
    source: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    conversation_id: Optional[str]
    request_id: str


class UsageSummary(BaseModel):
    source: str
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cost_usd: float = 0.0


class UsageResponse(BaseModel):
    records: List[UsageRecord]
    total_count: int


class UsageStatsResponse(BaseModel):
    summaries: List[UsageSummary]
    grand_total: UsageSummary
    period_start: Optional[str] = None
    period_end: Optional[str] = None
