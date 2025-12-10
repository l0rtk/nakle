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


class Choice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage

    @classmethod
    def create(cls, model: str, content: str) -> "ChatCompletionResponse":
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
            usage=Usage(),
        )
