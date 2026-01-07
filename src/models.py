from typing import List, Literal, Optional
from pydantic import BaseModel
import uuid
import time


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: Literal["sonnet", "opus", "haiku"] = "sonnet"
    messages: List[ChatMessage]
    conversation_id: Optional[str] = None


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

    @classmethod
    def create(cls, model: str, content: str, session_id: str = "", usage_data: dict = None) -> "ChatCompletionResponse":
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
        )
