import subprocess
import json
import base64
import tempfile
import os
from typing import List, Dict, Any, Optional, Tuple, Generator
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


def extract_content_and_images(content) -> Tuple[str, List[str]]:
    """
    Extract text content and save images to temp files.
    Returns (text_content, list_of_image_paths).
    """
    if isinstance(content, str):
        return content, []

    text_parts = []
    image_paths = []

    for part in content:
        if isinstance(part, dict):
            part_type = part.get("type")
            if part_type == "text":
                text_parts.append(part.get("text", ""))
            elif part_type == "image_url":
                image_url = part.get("image_url", {}).get("url", "")
                if image_url.startswith("data:"):
                    # Parse base64 data URL
                    # Format: data:image/png;base64,<data>
                    try:
                        header, b64data = image_url.split(",", 1)
                        # Extract mime type for extension
                        mime = header.split(";")[0].split(":")[1]
                        ext = mime.split("/")[1] if "/" in mime else "png"
                        # Save to temp file
                        fd, path = tempfile.mkstemp(suffix=f".{ext}", dir="/tmp")
                        with os.fdopen(fd, "wb") as f:
                            f.write(base64.b64decode(b64data))
                        image_paths.append(path)
                    except Exception:
                        pass  # Skip invalid images
        else:
            # Handle Pydantic models
            if hasattr(part, "type"):
                if part.type == "text":
                    text_parts.append(part.text)
                elif part.type == "image_url":
                    image_url = part.image_url.url
                    if image_url.startswith("data:"):
                        try:
                            header, b64data = image_url.split(",", 1)
                            mime = header.split(";")[0].split(":")[1]
                            ext = mime.split("/")[1] if "/" in mime else "png"
                            fd, path = tempfile.mkstemp(suffix=f".{ext}", dir="/tmp")
                            with os.fdopen(fd, "wb") as f:
                                f.write(base64.b64decode(b64data))
                            image_paths.append(path)
                        except Exception:
                            pass

    return " ".join(text_parts), image_paths


def format_messages(messages: List[ChatMessage]) -> Tuple[str, List[str]]:
    """Convert messages list to a single prompt string and collect image paths."""
    parts = []
    all_image_paths = []

    for msg in messages:
        text_content, image_paths = extract_content_and_images(msg.content)
        all_image_paths.extend(image_paths)

        # Add image references to the text
        if image_paths:
            image_refs = " ".join([f"[See image: {p}]" for p in image_paths])
            text_content = f"{text_content}\n{image_refs}"

        if msg.role == "system":
            parts.append(f"System: {text_content}")
        elif msg.role == "user":
            parts.append(f"User: {text_content}")
        elif msg.role == "assistant":
            parts.append(f"Assistant: {text_content}")

    parts.append("Assistant:")
    return "\n\n".join(parts), all_image_paths


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
    prompt, image_paths = format_messages(messages)
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

        # Clean up temp image files
        for path in image_paths:
            try:
                os.unlink(path)
            except Exception:
                pass

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

            usage = response_data.get("usage", {})
            response = {
                "result": response_data.get("result", ""),
                "session_id": session_id,
                "usage": {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                },
                "cost_usd": response_data.get("total_cost_usd", 0.0)
            }

            # Include structured_output if present
            if "structured_output" in response_data:
                response["structured_output"] = response_data["structured_output"]

            return response
        except json.JSONDecodeError as e:
            raise ClaudeError(f"Failed to parse JSON response: {e}")

    except subprocess.TimeoutExpired:
        # Clean up temp image files on timeout
        for path in image_paths:
            try:
                os.unlink(path)
            except Exception:
                pass
        raise ClaudeTimeoutError(f"Request timed out after {effective_timeout}s")


def run_claude_stream(messages: List[ChatMessage], model: str = "sonnet", conversation_id: Optional[str] = None) -> Generator[str, None, None]:
    """
    Run Claude Code in headless mode with streaming output.

    Yields SSE-formatted events.
    """
    prompt, image_paths = format_messages(messages)

    cmd = [
        "claude",
        "-p", "-",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",  # Enable real token streaming
        "--model", model,
        "--allowedTools", "Read,Grep,Glob,WebSearch",
    ]

    # Resume existing session if conversation_id exists
    if conversation_id and conversation_id in SESSION_STORE:
        session_id = SESSION_STORE[conversation_id]
        cmd.extend(["--resume", session_id])

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd="/tmp",
        )

        # Send prompt via stdin
        process.stdin.write(prompt)
        process.stdin.close()

        # Stream output line by line
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                # Handle streaming delta events (real-time tokens)
                if event_type == "stream_event":
                    inner_event = event.get("event", {})
                    inner_type = inner_event.get("type", "")

                    if inner_type == "content_block_delta":
                        delta = inner_event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                sse_data = json.dumps({
                                    "choices": [{
                                        "delta": {"content": text},
                                        "index": 0
                                    }]
                                })
                                yield f"data: {sse_data}\n\n"

                # Handle result event (final)
                elif event_type == "result":
                    session_id = event.get("session_id", "")
                    if conversation_id and session_id:
                        SESSION_STORE[conversation_id] = session_id

            except json.JSONDecodeError:
                continue

        process.wait()

        # Clean up temp image files
        for path in image_paths:
            try:
                os.unlink(path)
            except Exception:
                pass

        # Send done signal
        yield "data: [DONE]\n\n"

    except Exception as e:
        # Clean up on error
        for path in image_paths:
            try:
                os.unlink(path)
            except Exception:
                pass
        raise ClaudeError(f"Streaming error: {e}")
