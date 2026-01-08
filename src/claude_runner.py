import subprocess
import json
import re
import threading
from typing import List, Dict, Any, Optional
from .models import ChatMessage

# In-memory session store: conversation_id -> session_id
SESSION_STORE: Dict[str, str] = {}

# Active login process
LOGIN_PROCESS: Optional[subprocess.Popen] = None

CLAUDE_TIMEOUT = 60
LOGIN_URL_TIMEOUT = 30  # Timeout for getting login URL


class ClaudeError(Exception):
    """Raised when Claude Code returns an error."""
    pass


class ClaudeTimeoutError(ClaudeError):
    """Raised when Claude Code times out."""
    pass


class ClaudeAuthError(ClaudeError):
    """Raised when Claude authentication fails (token expired)."""
    pass


class ClaudeLoginError(ClaudeError):
    """Raised when login process fails."""
    pass


def run_claude_login(public_host: str = "localhost") -> str:
    """
    Start Claude login process and return the login URL.

    Args:
        public_host: Public hostname/IP to replace localhost in the URL

    Returns:
        Login URL with public host

    Raises:
        ClaudeLoginError: If login process fails or URL not found
    """
    global LOGIN_PROCESS

    # Kill any existing login process
    if LOGIN_PROCESS is not None:
        try:
            LOGIN_PROCESS.terminate()
            LOGIN_PROCESS.wait(timeout=5)
        except Exception:
            pass
        LOGIN_PROCESS = None

    try:
        # Start claude login process
        LOGIN_PROCESS = subprocess.Popen(
            ["claude", "/login"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd="/tmp",
        )

        # Read output until we find the URL
        url_pattern = re.compile(r'(https?://localhost:\d+[^\s]*)')
        output_lines = []

        def read_output():
            for line in LOGIN_PROCESS.stdout:
                output_lines.append(line)

        reader_thread = threading.Thread(target=read_output)
        reader_thread.daemon = True
        reader_thread.start()

        # Wait for URL with timeout
        reader_thread.join(timeout=LOGIN_URL_TIMEOUT)

        # Search for URL in output
        full_output = "".join(output_lines)
        match = url_pattern.search(full_output)

        if match:
            url = match.group(1)
            # Replace localhost with public host
            public_url = url.replace("localhost", public_host)
            return public_url

        raise ClaudeLoginError(f"Could not find login URL in output: {full_output[:500]}")

    except Exception as e:
        if LOGIN_PROCESS:
            LOGIN_PROCESS.terminate()
            LOGIN_PROCESS = None
        if isinstance(e, ClaudeLoginError):
            raise
        raise ClaudeLoginError(f"Login failed: {e}")


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


def run_claude(messages: List[ChatMessage], model: str = "sonnet", conversation_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Run Claude Code in headless mode with no context.

    Args:
        messages: List of chat messages
        model: Model to use (sonnet, opus, haiku)
        conversation_id: Optional conversation ID for multi-turn support

    Returns:
        Dict with keys: result (str), session_id (str), usage (dict)

    Raises:
        ClaudeError: If Claude returns an error
        ClaudeTimeoutError: If the request times out
    """
    prompt = format_messages(messages)

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--allowedTools", "Read,Grep,Glob,WebSearch",
    ]

    # Resume existing session if conversation_id exists
    if conversation_id and conversation_id in SESSION_STORE:
        session_id = SESSION_STORE[conversation_id]
        cmd.extend(["--resume", session_id])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            cwd="/tmp",  # Run from /tmp to avoid directory context
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"

            # Check for authentication errors
            if "authentication_error" in error_msg or "token has expired" in error_msg.lower() or "Please run /login" in error_msg:
                raise ClaudeAuthError("Claude token expired. Call POST /login to re-authenticate.")

            raise ClaudeError(f"Claude returned error (code {result.returncode}): {error_msg}")

        # Parse JSON response
        try:
            response_data = json.loads(result.stdout.strip())
            session_id = response_data.get("session_id", "")

            # Store session_id for future requests
            if conversation_id and session_id:
                SESSION_STORE[conversation_id] = session_id

            return {
                "result": response_data.get("result", ""),
                "session_id": session_id,
                "usage": response_data.get("usage", {
                    "input_tokens": 0,
                    "output_tokens": 0
                })
            }
        except json.JSONDecodeError as e:
            raise ClaudeError(f"Failed to parse JSON response: {e}")

    except subprocess.TimeoutExpired:
        raise ClaudeTimeoutError(f"Request timed out after {CLAUDE_TIMEOUT}s")
