from fastapi import FastAPI, HTTPException
from .models import ChatCompletionRequest, ChatCompletionResponse
from .claude_runner import run_claude, ClaudeError, ClaudeTimeoutError

app = FastAPI(
    title="Nakle",
    description="API wrapper for Claude Code as a pure LLM",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat/completions", response_model=ChatCompletionResponse)
def chat_completions(request: ChatCompletionRequest):
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    try:
        claude_response = run_claude(
            request.messages,
            request.model,
            request.conversation_id
        )

        response = ChatCompletionResponse.create(
            model=request.model,
            content=claude_response["result"],
            session_id=claude_response["session_id"],
            usage_data=claude_response["usage"]
        )

        # Echo back conversation_id if provided
        if request.conversation_id:
            response.conversation_id = request.conversation_id

        return response

    except ClaudeTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))

    except ClaudeError as e:
        raise HTTPException(status_code=502, detail=str(e))
