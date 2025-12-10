import subprocess
from typing import List
from .models import ChatMessage

CLAUDE_TIMEOUT = 60


class ClaudeError(Exception):
    """Raised when Claude Code returns an error."""
    pass


class ClaudeTimeoutError(ClaudeError):
    """Raised when Claude Code times out."""
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


def run_claude(messages: List[ChatMessage], model: str = "sonnet") -> str:
    """
    Run Claude Code in headless mode with no context.

    Args:
        messages: List of chat messages
        model: Model to use (sonnet, opus, haiku)

    Returns:
        Claude's response as plain text

    Raises:
        ClaudeError: If Claude returns an error
        ClaudeTimeoutError: If the request times out
    """
    prompt = format_messages(messages)

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "text",
        "--model", model,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            cwd="/tmp",  # Run from /tmp to avoid directory context
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            raise ClaudeError(f"Claude returned error: {error_msg}")

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        raise ClaudeTimeoutError(f"Request timed out after {CLAUDE_TIMEOUT}s")
