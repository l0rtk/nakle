import logging
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, HTMLResponse
from .models import (
    ChatCompletionRequest, ChatCompletionResponse,
    UsageResponse, UsageStatsResponse, UsageSummary, UsageRecord
)
from .claude_runner import run_claude, run_claude_stream, ClaudeError, ClaudeTimeoutError, ClaudeAuthError
from .usage_store import init_db, record_usage, get_usage_records, get_usage_stats

CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize usage database on startup."""
    init_db()
    logger.info("Usage database initialized")
    yield


app = FastAPI(
    title="Nakle",
    description="API wrapper for Claude Code as a pure LLM",
    version="0.1.0",
    lifespan=lifespan,
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


@app.post("/chat/completions")
def chat_completions(request: ChatCompletionRequest):
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    # Get prompt preview (handle multimodal content)
    last_content = request.messages[-1].content
    if isinstance(last_content, str):
        prompt_preview = last_content[:50] + "..." if len(last_content) > 50 else last_content
    else:
        # Multimodal: extract text parts
        text_parts = [p.text for p in last_content if hasattr(p, "text")]
        prompt_text = " ".join(text_parts) if text_parts else "[image]"
        prompt_preview = prompt_text[:50] + "..." if len(prompt_text) > 50 else prompt_text
    logger.info(f"Request | model={request.model} | source={request.source} | stream={request.stream} | prompt=\"{prompt_preview}\"")

    # Handle streaming request
    if request.stream:
        logger.warning(f"Usage tracking not available for streaming requests (source={request.source})")
        try:
            return StreamingResponse(
                run_claude_stream(request.messages, request.model, request.conversation_id),
                media_type="text/event-stream"
            )
        except ClaudeError as e:
            logger.error(f"Stream Error | {e}")
            raise HTTPException(status_code=502, detail=str(e))

    # Extract json_schema if response_format is json_schema
    json_schema = None
    if request.response_format and request.response_format.type == "json_schema":
        json_schema = request.response_format.json_schema

    try:
        claude_response = run_claude(
            request.messages,
            request.model,
            request.conversation_id,
            request.timeout,
            json_schema
        )

        response = ChatCompletionResponse.create(
            model=request.model,
            content=claude_response["result"],
            session_id=claude_response["session_id"],
            usage_data=claude_response["usage"],
            structured_output=claude_response.get("structured_output")
        )

        # Echo back conversation_id if provided
        if request.conversation_id:
            response.conversation_id = request.conversation_id

        usage = claude_response["usage"]
        cost_usd = claude_response.get("cost_usd", 0.0)
        logger.info(f"Success | source={request.source} | tokens={usage.get('input_tokens', 0)}+{usage.get('output_tokens', 0)} | cost=${cost_usd:.4f}")

        # Record usage for tracking
        record_usage(
            source=request.source,
            model=request.model,
            input_tokens=usage.get('input_tokens', 0),
            output_tokens=usage.get('output_tokens', 0),
            request_id=response.id,
            conversation_id=request.conversation_id,
            cost_usd=cost_usd
        )

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


@app.get("/usage", response_model=UsageResponse)
def get_usage(
    source: str = Query(None, description="Filter by source"),
    start: str = Query(None, description="Start time (ISO 8601)"),
    end: str = Query(None, description="End time (ISO 8601)"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip")
):
    """Get usage records with optional filters."""
    records, total_count = get_usage_records(
        source=source,
        start_time=start,
        end_time=end,
        limit=limit,
        offset=offset
    )
    return UsageResponse(
        records=[UsageRecord(**r) for r in records],
        total_count=total_count
    )


@app.get("/usage/stats", response_model=UsageStatsResponse)
def get_usage_statistics(
    source: str = Query(None, description="Filter by source"),
    start: str = Query(None, description="Start time (ISO 8601)"),
    end: str = Query(None, description="End time (ISO 8601)")
):
    """Get aggregated usage statistics grouped by source."""
    stats = get_usage_stats(source=source, start_time=start, end_time=end)

    summaries = [UsageSummary(**s) for s in stats]

    # Calculate grand total
    grand_total = UsageSummary(
        source="all",
        total_requests=sum(s.total_requests for s in summaries),
        total_input_tokens=sum(s.total_input_tokens for s in summaries),
        total_output_tokens=sum(s.total_output_tokens for s in summaries),
        total_tokens=sum(s.total_tokens for s in summaries),
        total_cost_usd=sum(s.total_cost_usd for s in summaries)
    )

    return UsageStatsResponse(
        summaries=summaries,
        grand_total=grand_total,
        period_start=start,
        period_end=end
    )


@app.get("/usage/dashboard", response_class=HTMLResponse)
def usage_dashboard():
    """Visual HTML dashboard for usage statistics."""
    stats = get_usage_stats()
    records, total_count = get_usage_records(limit=20)

    # Calculate totals
    total_requests = sum(s["total_requests"] for s in stats)
    total_tokens = sum(s["total_tokens"] for s in stats)
    total_cost = sum(s["total_cost_usd"] or 0 for s in stats)

    # Build source rows
    source_rows = ""
    for s in stats:
        cost = s["total_cost_usd"] or 0
        source_rows += f"""
        <tr>
            <td><strong>{s['source']}</strong></td>
            <td>{s['total_requests']:,}</td>
            <td>{s['total_input_tokens']:,}</td>
            <td>{s['total_output_tokens']:,}</td>
            <td>{s['total_tokens']:,}</td>
            <td>${cost:.4f}</td>
        </tr>"""

    # Build recent records rows
    record_rows = ""
    for r in records:
        cost = r["cost_usd"] or 0
        ts = r["timestamp"][:19].replace("T", " ")
        record_rows += f"""
        <tr>
            <td>{ts}</td>
            <td>{r['source']}</td>
            <td>{r['model']}</td>
            <td>{r['input_tokens']:,}+{r['output_tokens']:,}</td>
            <td>${cost:.4f}</td>
        </tr>"""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nakle Usage Dashboard</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #0f172a;
                color: #e2e8f0;
                padding: 2rem;
                min-height: 100vh;
            }}
            h1 {{
                font-size: 1.8rem;
                margin-bottom: 1.5rem;
                color: #f8fafc;
            }}
            h2 {{
                font-size: 1.2rem;
                margin: 2rem 0 1rem;
                color: #94a3b8;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1rem;
                margin-bottom: 2rem;
            }}
            .card {{
                background: #1e293b;
                border-radius: 12px;
                padding: 1.5rem;
                border: 1px solid #334155;
            }}
            .card-label {{
                font-size: 0.85rem;
                color: #94a3b8;
                margin-bottom: 0.5rem;
            }}
            .card-value {{
                font-size: 2rem;
                font-weight: 600;
                color: #f8fafc;
            }}
            .card-value.cost {{
                color: #4ade80;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: #1e293b;
                border-radius: 12px;
                overflow: hidden;
                border: 1px solid #334155;
            }}
            th, td {{
                padding: 0.75rem 1rem;
                text-align: left;
                border-bottom: 1px solid #334155;
            }}
            th {{
                background: #334155;
                font-weight: 600;
                color: #f8fafc;
                font-size: 0.85rem;
            }}
            tr:last-child td {{
                border-bottom: none;
            }}
            tr:hover {{
                background: #334155;
            }}
            .refresh {{
                display: inline-block;
                margin-bottom: 1rem;
                padding: 0.5rem 1rem;
                background: #3b82f6;
                color: white;
                text-decoration: none;
                border-radius: 6px;
                font-size: 0.9rem;
            }}
            .refresh:hover {{
                background: #2563eb;
            }}
            .footer {{
                margin-top: 2rem;
                color: #64748b;
                font-size: 0.85rem;
            }}
        </style>
    </head>
    <body>
        <h1>Nakle Usage Dashboard</h1>
        <a href="/usage/dashboard" class="refresh">Refresh</a>

        <div class="cards">
            <div class="card">
                <div class="card-label">Total Requests</div>
                <div class="card-value">{total_requests:,}</div>
            </div>
            <div class="card">
                <div class="card-label">Total Tokens</div>
                <div class="card-value">{total_tokens:,}</div>
            </div>
            <div class="card">
                <div class="card-label">Total Cost</div>
                <div class="card-value cost">${total_cost:.2f}</div>
            </div>
            <div class="card">
                <div class="card-label">Sources</div>
                <div class="card-value">{len(stats)}</div>
            </div>
        </div>

        <h2>Usage by Source</h2>
        <table>
            <thead>
                <tr>
                    <th>Source</th>
                    <th>Requests</th>
                    <th>Input Tokens</th>
                    <th>Output Tokens</th>
                    <th>Total Tokens</th>
                    <th>Cost</th>
                </tr>
            </thead>
            <tbody>
                {source_rows if source_rows else '<tr><td colspan="6" style="text-align:center;color:#64748b;">No data yet</td></tr>'}
            </tbody>
        </table>

        <h2>Recent Requests ({total_count} total)</h2>
        <table>
            <thead>
                <tr>
                    <th>Time (UTC)</th>
                    <th>Source</th>
                    <th>Model</th>
                    <th>Tokens</th>
                    <th>Cost</th>
                </tr>
            </thead>
            <tbody>
                {record_rows if record_rows else '<tr><td colspan="5" style="text-align:center;color:#64748b;">No requests yet</td></tr>'}
            </tbody>
        </table>

        <div class="footer">
            API: <a href="/usage" style="color:#3b82f6">/usage</a> |
            <a href="/usage/stats" style="color:#3b82f6">/usage/stats</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
