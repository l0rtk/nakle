# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Nakle is a REST API that wraps Claude Code headless mode as a pure LLM API (no codebase context).

## Commands

### Local Development
```bash
# Install
pip install -e .

# Run server
uvicorn src.main:app --reload

# Test endpoint
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "sonnet", "messages": [{"role": "user", "content": "Hello"}]}'
```

### Docker Deployment
```bash
# Build and run with docker-compose
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
docker-compose up -d

# Or build/run manually
docker build -t nakle .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=your_key nakle
```

## Architecture

- `src/main.py` - FastAPI application with `/chat/completions` and `/health` endpoints
- `src/claude_runner.py` - Subprocess wrapper that runs `claude -p` from `/tmp` with no context
- `src/models.py` - Pydantic models for request/response
