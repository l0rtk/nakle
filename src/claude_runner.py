import subprocess
import json
from typing import List, Dict, Any, Optional
from .models import ChatMessage

# In-memory session store: conversation_id -> session_id
SESSION_STORE: Dict[str, str] = {}

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 600


class ClaudeError(Exception):
    """Raised when Claude Code returns an error."""
    pass


class ClaudeTimeoutError(ClaudeError):
    """Raised when Claude Code times out."""
    pass


class ClaudeAuthError(ClaudeError):
    """Raised when Claude authentication fails (token expired)."""
    pass


def format_messages(messages: List[ChatMessage]) -> str:
    """Convert messages list to a single prompt string."""
    parts = []

    for msg in messages:
        if msg.role == "system":
            parts.append(f"System: {msg.content}")
        elif msg.role == "user":
            parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            parts.append(f"Assistant: {msg.content}")

    parts.append("Assistant:")
    return "\n\n".join(parts)


def run_claude(messages: List[ChatMessage], model: str = "sonnet", conversation_id: Optional[str] = None, timeout: Optional[int] = None, json_schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Run Claude Code in headless mode with no context.

    Args:
        messages: List of chat messages
        model: Model to use (sonnet, opus, haiku)
        conversation_id: Optional conversation ID for multi-turn support
        timeout: Request timeout in seconds (default: DEFAULT_TIMEOUT, max: MAX_TIMEOUT)
        json_schema: Optional JSON schema for structured output

    Returns:
        Dict with keys: result (str), session_id (str), usage (dict), structured_output (optional)

    Raises:
        ClaudeError: If Claude returns an error
        ClaudeTimeoutError: If the request times out
    """
    prompt = format_messages(messages)
    effective_timeout = min(timeout or DEFAULT_TIMEOUT, MAX_TIMEOUT)

    cmd = [
        "claude",
        "-p", "-",  # Read from stdin instead of argument
        "--output-format", "json",
        "--model", model,
        "--allowedTools", "Read,Grep,Glob,WebSearch",
    ]

    # Add JSON schema if provided
    if json_schema:
        cmd.extend(["--json-schema", json.dumps(json_schema)])

    # Resume existing session if conversation_id exists
    if conversation_id and conversation_id in SESSION_STORE:
        session_id = SESSION_STORE[conversation_id]
        cmd.extend(["--resume", session_id])

    try:
        result = subprocess.run(
            cmd,
            input=prompt,  # Pass prompt via stdin
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            cwd="/tmp",  # Run from /tmp to avoid directory context
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"

            # Check for authentication errors
            if "authentication_error" in error_msg or "token has expired" in error_msg.lower() or "Please run /login" in error_msg:
                raise ClaudeAuthError("Claude token expired. Call GET /login for re-authentication instructions.")

            raise ClaudeError(f"Claude returned error (code {result.returncode}): {error_msg}")

        # Parse JSON response
        try:
            response_data = json.loads(result.stdout.strip())
            session_id = response_data.get("session_id", "")

            # Store session_id for future requests
            if conversation_id and session_id:
                SESSION_STORE[conversation_id] = session_id

            response = {
                "result": response_data.get("result", ""),
                "session_id": session_id,
                "usage": response_data.get("usage", {
                    "input_tokens": 0,
                    "output_tokens": 0
                })
            }

            # Include structured_output if present
            if "structured_output" in response_data:
                response["structured_output"] = response_data["structured_output"]

            return response
        except json.JSONDecodeError as e:
            raise ClaudeError(f"Failed to parse JSON response: {e}")

    except subprocess.TimeoutExpired:
        raise ClaudeTimeoutError(f"Request timed out after {effective_timeout}s")
