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
            cost_usd=cost_usd,
            cache_creation_tokens=usage.get('cache_creation_tokens', 0),
            cache_read_tokens=usage.get('cache_read_tokens', 0)
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
    """Visual HTML dashboard for usage statistics - pixel aesthetic."""
    stats = get_usage_stats()
    records, total_count = get_usage_records(limit=20)

    # Calculate totals
    total_requests = sum(s["total_requests"] for s in stats)
    total_input = sum(s["total_input_tokens"] for s in stats)
    total_output = sum(s["total_output_tokens"] for s in stats)
    total_tokens = sum(s["total_tokens"] for s in stats)
    total_cache_create = sum(s.get("total_cache_creation_tokens") or 0 for s in stats)
    total_cache_read = sum(s.get("total_cache_read_tokens") or 0 for s in stats)
    total_cost = sum(s["total_cost_usd"] or 0 for s in stats)

    # Build pie chart SVG segments
    colors = ["#00ff00", "#ff00ff", "#00ffff", "#ffff00", "#ff6600", "#ff0066", "#66ff00", "#0066ff"]
    pie_segments = ""
    legend_items = ""
    if stats and total_tokens > 0:
        cumulative = 0
        for i, s in enumerate(stats):
            tokens = s["total_tokens"]
            percentage = (tokens / total_tokens) * 100
            start_angle = cumulative * 3.6  # 360 / 100
            end_angle = (cumulative + percentage) * 3.6
            cumulative += percentage
            color = colors[i % len(colors)]

            # SVG arc calculation
            large_arc = 1 if percentage > 50 else 0
            start_rad = (start_angle - 90) * 3.14159 / 180
            end_rad = (end_angle - 90) * 3.14159 / 180
            x1 = 100 + 80 * round(cos_approx(start_rad), 4)
            y1 = 100 + 80 * round(sin_approx(start_rad), 4)
            x2 = 100 + 80 * round(cos_approx(end_rad), 4)
            y2 = 100 + 80 * round(sin_approx(end_rad), 4)

            if percentage >= 100:
                pie_segments = f'<circle cx="100" cy="100" r="80" fill="{color}"><title>{s["source"]}: {tokens:,} tokens ({percentage:.1f}%)</title></circle>'
            elif percentage > 0:
                pie_segments += f'<path d="M100,100 L{x1},{y1} A80,80 0 {large_arc},1 {x2},{y2} Z" fill="{color}" style="cursor:pointer;"><title>{s["source"]}: {tokens:,} tokens ({percentage:.1f}%)</title></path>'

            legend_items += f'''
            <div class="legend-item">
                <span class="legend-color" style="background:{color}"></span>
                <span class="legend-text">{s['source']}: {percentage:.1f}%</span>
            </div>'''

    # Build source rows
    source_rows = ""
    for i, s in enumerate(stats):
        cost = s["total_cost_usd"] or 0
        color = colors[i % len(colors)]
        source_rows += f"""
        <tr>
            <td><span style="color:{color}">■</span> {s['source']}</td>
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
        cache_create = r.get('cache_creation_tokens') or 0
        cache_read = r.get('cache_read_tokens') or 0
        record_rows += f"""
        <tr>
            <td>{ts}</td>
            <td>{r['source']}</td>
            <td>{r['model']}</td>
            <td>{r['input_tokens']:,}+{r['output_tokens']:,}</td>
            <td>{cache_create:,}+{cache_read:,}</td>
            <td>${cost:.4f}</td>
        </tr>"""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>NAKLE // USAGE</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: 'Press Start 2P', monospace;
                background: #000;
                color: #ccc;
                padding: 20px;
                min-height: 100vh;
                font-size: 10px;
                line-height: 1.8;
                image-rendering: pixelated;
            }}
            h1 {{
                font-size: 16px;
                margin-bottom: 20px;
                color: #fff;
                text-shadow: 2px 2px #333;
            }}
            h2 {{
                font-size: 12px;
                margin: 30px 0 15px;
                color: #0ff;
                text-shadow: 1px 1px #033;
            }}
            .pixel-border {{
                border: 4px solid #555;
                box-shadow: 4px 4px 0 #222, inset 0 0 20px rgba(255,255,255,0.03);
            }}
            .dashboard-grid {{
                display: grid;
                grid-template-columns: 1fr 300px;
                gap: 20px;
                margin-bottom: 20px;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 15px;
            }}
            .card {{
                background: #000;
                padding: 15px;
            }}
            .card-label {{
                font-size: 8px;
                color: #888;
                margin-bottom: 8px;
            }}
            .card-value {{
                font-size: 20px;
                color: #fff;
            }}
            .card-value.cost {{
                color: #0ff;
            }}
            .pie-container {{
                background: #000;
                padding: 15px;
                text-align: center;
            }}
            .pie-chart {{
                margin-bottom: 10px;
            }}
            .legend {{
                text-align: left;
            }}
            .legend-item {{
                display: flex;
                align-items: center;
                gap: 8px;
                margin: 5px 0;
            }}
            .legend-color {{
                width: 12px;
                height: 12px;
                display: inline-block;
            }}
            .legend-text {{
                font-size: 8px;
                color: #ccc;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: #000;
            }}
            th, td {{
                padding: 10px 8px;
                text-align: left;
                border-bottom: 2px solid #222;
            }}
            th {{
                background: #111;
                color: #0ff;
                font-size: 8px;
            }}
            td {{
                font-size: 9px;
                color: #aaa;
            }}
            tr:hover td {{
                background: #111;
                color: #fff;
            }}
            .refresh {{
                display: inline-block;
                margin-bottom: 20px;
                padding: 10px 15px;
                background: #000;
                color: #fff;
                text-decoration: none;
                border: 3px solid #555;
                font-family: 'Press Start 2P', monospace;
                font-size: 10px;
            }}
            .refresh:hover {{
                background: #333;
                color: #fff;
            }}
            .footer {{
                margin-top: 30px;
                color: #555;
                font-size: 8px;
            }}
            .footer a {{
                color: #0ff;
            }}
            .blink {{
                animation: blink 1s step-start infinite;
            }}
            @keyframes blink {{
                50% {{ opacity: 0; }}
            }}
            .scanlines {{
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
                background: repeating-linear-gradient(
                    0deg,
                    rgba(0,0,0,0.1) 0px,
                    rgba(0,0,0,0.1) 1px,
                    transparent 1px,
                    transparent 2px
                );
                z-index: 9999;
            }}
        </style>
    </head>
    <body>
        <div class="scanlines"></div>
        <h1>> NAKLE USAGE_<span class="blink">█</span></h1>
        <a href="/usage/dashboard" class="refresh">[REFRESH]</a>

        <div class="dashboard-grid">
            <div class="cards">
                <div class="card pixel-border">
                    <div class="card-label">REQUESTS</div>
                    <div class="card-value">{total_requests:,}</div>
                </div>
                <div class="card pixel-border">
                    <div class="card-label">IN+OUT</div>
                    <div class="card-value">{total_input:,}+{total_output:,}</div>
                </div>
                <div class="card pixel-border">
                    <div class="card-label">CACHE CREATE</div>
                    <div class="card-value">{total_cache_create:,}</div>
                </div>
                <div class="card pixel-border">
                    <div class="card-label">CACHE READ</div>
                    <div class="card-value">{total_cache_read:,}</div>
                </div>
                <div class="card pixel-border">
                    <div class="card-label">COST USD</div>
                    <div class="card-value cost">${total_cost:.2f}</div>
                </div>
                <div class="card pixel-border">
                    <div class="card-label">SOURCES</div>
                    <div class="card-value">{len(stats)}</div>
                </div>
            </div>
            <div class="pie-container pixel-border">
                <div class="pie-chart">
                    <svg width="200" height="200" viewBox="0 0 200 200">
                        <circle cx="100" cy="100" r="80" fill="#111" stroke="#444" stroke-width="2"/>
                        {pie_segments if pie_segments else '<text x="100" y="105" text-anchor="middle" fill="#555" font-size="10">NO DATA</text>'}
                    </svg>
                </div>
                <div class="legend">
                    {legend_items if legend_items else '<div class="legend-text">No sources yet</div>'}
                </div>
            </div>
        </div>

        <h2>> USAGE BY SOURCE</h2>
        <div class="pixel-border" style="overflow:hidden;">
        <table>
            <thead>
                <tr>
                    <th>SOURCE</th>
                    <th>REQ</th>
                    <th>IN</th>
                    <th>OUT</th>
                    <th>TOTAL</th>
                    <th>$$$</th>
                </tr>
            </thead>
            <tbody>
                {source_rows if source_rows else '<tr><td colspan="6" style="text-align:center;color:#555;">AWAITING DATA...</td></tr>'}
            </tbody>
        </table>
        </div>

        <h2>> RECENT [{total_count} TOTAL]</h2>
        <div class="pixel-border" style="overflow:hidden;">
        <table>
            <thead>
                <tr>
                    <th>TIME</th>
                    <th>SOURCE</th>
                    <th>MODEL</th>
                    <th>IN+OUT</th>
                    <th>CACHE</th>
                    <th>$$$</th>
                </tr>
            </thead>
            <tbody>
                {record_rows if record_rows else '<tr><td colspan="6" style="text-align:center;color:#555;">NO REQUESTS YET...</td></tr>'}
            </tbody>
        </table>
        </div>

        <div class="footer">
            API: <a href="/usage">/usage</a> | <a href="/usage/stats">/usage/stats</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


def cos_approx(x):
    """Simple cosine approximation for SVG pie chart."""
    import math
    return math.cos(x)


def sin_approx(x):
    """Simple sine approximation for SVG pie chart."""
    import math
    return math.sin(x)
