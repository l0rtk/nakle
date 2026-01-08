import logging
from fastapi import FastAPI, HTTPException
from .models import ChatCompletionRequest, ChatCompletionResponse
from .claude_runner import run_claude, ClaudeError, ClaudeTimeoutError, ClaudeAuthError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

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

    # Get prompt preview
    last_msg = request.messages[-1].content
    prompt_preview = last_msg[:50] + "..." if len(last_msg) > 50 else last_msg
    logger.info(f"Request | model={request.model} | prompt=\"{prompt_preview}\"")

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

        usage = claude_response["usage"]
        logger.info(f"Success | tokens={usage.get('input_tokens', 0)}+{usage.get('output_tokens', 0)}")

        return response

    except ClaudeAuthError as e:
        logger.error(f"Auth | {e}")
        raise HTTPException(status_code=401, detail=str(e))

    except ClaudeTimeoutError as e:
        logger.error(f"Timeout | {e}")
        raise HTTPException(status_code=504, detail=str(e))

    except ClaudeError as e:
        logger.error(f"Error | {e}")
        raise HTTPException(status_code=502, detail=str(e))
