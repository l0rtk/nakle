from typing import List, Literal, Optional, Dict, Any, Union
from pydantic import BaseModel
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


class ChatCompletionRequest(BaseModel):
    model: Literal["sonnet", "opus", "haiku"] = "sonnet"
    messages: List[ChatMessage]
    conversation_id: Optional[str] = None
    timeout: Optional[int] = 300  # seconds, max 300
    response_format: Optional[ResponseFormat] = None
    stream: bool = False
    source: str = "unknown"  # Track request origin for usage monitoring


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
    cost_usd: float = 0.0
    conversation_id: Optional[str]
    request_id: str


class UsageSummary(BaseModel):
    source: str
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float = 0.0


class UsageResponse(BaseModel):
    records: List[UsageRecord]
    total_count: int


class UsageStatsResponse(BaseModel):
    summaries: List[UsageSummary]
    grand_total: UsageSummary
    period_start: Optional[str] = None
    period_end: Optional[str] = None
