import logging
import json
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from .models import ChatCompletionRequest, ChatCompletionResponse
from .claude_runner import run_claude, ClaudeError, ClaudeTimeoutError, ClaudeAuthError

CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")

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


@app.get("/status")
def status():
    """
    Check authentication status and token expiration.
    """
    try:
        with open(CREDENTIALS_PATH, "r") as f:
            creds = json.load(f)

        oauth = creds.get("claudeAiOauth", {})
        expires_at_ms = oauth.get("expiresAt", 0)

        if expires_at_ms:
            expires_at = datetime.fromtimestamp(expires_at_ms / 1000)
            now = datetime.now()
            remaining = expires_at - now
            remaining_minutes = remaining.total_seconds() / 60
            is_expired = now >= expires_at

            return {
                "authenticated": not is_expired,
                "expires_at": expires_at.isoformat(),
                "expires_in_minutes": round(remaining_minutes) if not is_expired else 0,
                "subscription": oauth.get("subscriptionType", "unknown"),
                "status": "expired" if is_expired else "valid"
            }

        return {"authenticated": False, "status": "no_token"}

    except FileNotFoundError:
        return {"authenticated": False, "status": "no_credentials_file"}
    except Exception as e:
        return {"authenticated": False, "status": "error", "error": str(e)}


@app.get("/login")
def login():
    """
    Return instructions for re-authenticating Claude.
    """
    logger.info("Login | Instructions requested")
    return {
        "status": "auth_required",
        "instructions": [
            "SSH to the server: ssh azureuser@20.64.149.209",
            "Run: claude setup-token",
            "Follow the prompts to authenticate",
            "Restart container: sudo docker-compose restart"
        ],
        "ssh_command": "ssh azureuser@20.64.149.209",
        "login_command": "claude setup-token"
    }


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
            request.conversation_id,
            request.timeout
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
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Claude token expired",
                "instructions": [
                    "SSH to the server: ssh azureuser@20.64.149.209",
                    "Run: claude setup-token",
                    "Follow the prompts to authenticate",
                    "Restart container: sudo docker-compose restart"
                ]
            }
        )

    except ClaudeTimeoutError as e:
        logger.error(f"Timeout | {e}")
        raise HTTPException(status_code=504, detail=str(e))

    except ClaudeError as e:
        logger.error(f"Error | {e}")
        raise HTTPException(status_code=502, detail=str(e))
