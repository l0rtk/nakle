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


def format_messages(messages: List[ChatMessage], extract_system: bool = False) -> Tuple[str, List[str], Optional[str]]:
    """Convert messages list to a single prompt string and collect image paths.

    If extract_system is True, system-role messages are pulled out of the
    inline prompt and returned as the third tuple element (joined with
    double-newlines if multiple). Otherwise they're kept inline as
    "System: ..." for backward compatibility.
    """
    parts = []
    all_image_paths = []
    system_parts = []

    for msg in messages:
        text_content, image_paths = extract_content_and_images(msg.content)
        all_image_paths.extend(image_paths)

        # Add image references to the text
        if image_paths:
            image_refs = " ".join([f"[See image: {p}]" for p in image_paths])
            text_content = f"{text_content}\n{image_refs}"

        if msg.role == "system":
            if extract_system:
                system_parts.append(text_content)
            else:
                parts.append(f"System: {text_content}")
        elif msg.role == "user":
            parts.append(f"User: {text_content}")
        elif msg.role == "assistant":
            parts.append(f"Assistant: {text_content}")

    parts.append("Assistant:")
    system_prompt = "\n\n".join(system_parts) if system_parts else None
    return "\n\n".join(parts), all_image_paths, system_prompt


DEFAULT_ALLOWED_TOOLS = ["Read", "Grep", "Glob", "WebSearch"]


def _tools_args(allowed_tools: Optional[List[str]], have_images: bool = False) -> List[str]:
    """Build CLI args for tool restriction.

    None  -> current default (Read,Grep,Glob,WebSearch)
    []    -> no tools (uses --tools "" to disable everything)
    list  -> exactly those tools

    have_images: the request carries image attachments, which the CLI can
    only view through its Read tool. A client that disables tools (or allows
    a set without Read) would otherwise have its images ACCEPTED by the
    schema, saved to /tmp, referenced in the prompt — and silently invisible
    to the model ("NO IMAGE RECEIVED"). Images are an explicit ask, so Read
    is force-included for exactly those requests.
    """
    if have_images and allowed_tools is not None and "Read" not in allowed_tools:
        allowed_tools = [*allowed_tools, "Read"]
    if allowed_tools is None:
        return ["--allowedTools", ",".join(DEFAULT_ALLOWED_TOOLS)]
    if len(allowed_tools) == 0:
        return ["--tools", ""]
    return ["--allowedTools", ",".join(allowed_tools)]


def run_claude(messages: List[ChatMessage], model: str = "sonnet", conversation_id: Optional[str] = None, timeout: Optional[int] = None, json_schema: Optional[Dict[str, Any]] = None, allowed_tools: Optional[List[str]] = None, system: Optional[str] = None) -> Dict[str, Any]:
    """
    Run Claude Code in headless mode with no context.

    Args:
        messages: List of chat messages
        model: Model to use (sonnet, opus, haiku)
        conversation_id: Optional conversation ID for multi-turn support
        timeout: Request timeout in seconds (default: DEFAULT_TIMEOUT, max: MAX_TIMEOUT)
        json_schema: Optional JSON schema for structured output
        allowed_tools: Tool restriction (None=default, []=none, list=exact set)
        system: Top-level system prompt. Wins over role:"system" messages.

    Returns:
        Dict with keys: result (str), session_id (str), usage (dict), structured_output (optional)

    Raises:
        ClaudeError: If Claude returns an error
        ClaudeTimeoutError: If the request times out
    """
    prompt, image_paths, extracted_system = format_messages(messages, extract_system=system is not None)
    effective_system = system if system is not None else extracted_system
    effective_timeout = min(timeout or DEFAULT_TIMEOUT, MAX_TIMEOUT)

    cmd = [
        "claude",
        "-p", "-",  # Read from stdin instead of argument
        "--output-format", "json",
        "--model", model,
        *_tools_args(allowed_tools, have_images=bool(image_paths)),
    ]
    if effective_system:
        cmd.extend(["--system-prompt", effective_system])

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


TOOL_RESULT_SUMMARY_CHARS = 240


def _summarize_tool_result(content) -> str:
    """Flatten a tool_result content payload into a short string for UI display."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
                else:
                    parts.append(f"[{part.get('type', 'block')}]")
        text = " ".join(parts)
    else:
        text = str(content)
    text = text.strip().replace("\n", " ")
    if len(text) > TOOL_RESULT_SUMMARY_CHARS:
        text = text[:TOOL_RESULT_SUMMARY_CHARS] + "..."
    return text


def run_claude_stream(messages: List[ChatMessage], model: str = "sonnet", conversation_id: Optional[str] = None, allowed_tools: Optional[List[str]] = None, system: Optional[str] = None, extended_events: bool = False, source: str = "unknown") -> Generator[str, None, None]:
    """
    Run Claude Code in headless mode with streaming output.

    Yields SSE-formatted events. When extended_events is True, additionally
    emits thinking / tool_use / tool_result event types alongside the
    OpenAI-shaped text deltas.

    Usage IS tracked here: the CLI's final `result` event carries the same
    usage/cost block the non-streaming path records — streaming clients
    (every agent) used to be invisible in the /usage ledger.
    """
    prompt, image_paths, extracted_system = format_messages(messages, extract_system=system is not None)
    effective_system = system if system is not None else extracted_system

    cmd = [
        "claude",
        "-p", "-",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",  # Enable real token streaming
        "--model", model,
        *_tools_args(allowed_tools, have_images=bool(image_paths)),
    ]
    if effective_system:
        cmd.extend(["--system-prompt", effective_system])

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
                        delta_type = delta.get("type")
                        if delta_type == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                sse_data = json.dumps({
                                    "choices": [{
                                        "delta": {"content": text},
                                        "index": 0
                                    }]
                                })
                                yield f"data: {sse_data}\n\n"
                        elif extended_events and delta_type == "thinking_delta":
                            text = delta.get("thinking", "")
                            if text:
                                yield f"data: {json.dumps({'type': 'thinking', 'content': text})}\n\n"

                # Assembled assistant turn — has complete tool_use blocks
                elif extended_events and event_type == "assistant":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            payload = {
                                "type": "tool_use",
                                "id": block.get("id", ""),
                                "tool": block.get("name", ""),
                                "input": block.get("input", {}),
                            }
                            yield f"data: {json.dumps(payload)}\n\n"

                # Tool results come back as user-role messages
                elif extended_events and event_type == "user":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_result":
                            payload = {
                                "type": "tool_result",
                                "tool_use_id": block.get("tool_use_id", ""),
                                "is_error": block.get("is_error", False),
                                "summary": _summarize_tool_result(block.get("content", "")),
                            }
                            yield f"data: {json.dumps(payload)}\n\n"

                # Handle result event (final)
                elif event_type == "result":
                    session_id = event.get("session_id", "")
                    if conversation_id and session_id:
                        SESSION_STORE[conversation_id] = session_id
                    # Record usage — recording failure must never kill a
                    # stream that already delivered its answer.
                    try:
                        import uuid as _uuid
                        from .usage_store import record_usage
                        usage = event.get("usage") or {}
                        record_usage(
                            source=source,
                            model=model,
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            request_id=f"chatcmpl-{_uuid.uuid4().hex[:12]}",
                            conversation_id=conversation_id,
                            cost_usd=event.get("total_cost_usd", 0.0),
                            cache_creation_tokens=usage.get(
                                "cache_creation_input_tokens", 0),
                            cache_read_tokens=usage.get(
                                "cache_read_input_tokens", 0),
                        )
                    except Exception:
                        pass

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
