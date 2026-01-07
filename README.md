# Nakle

REST API wrapper for Claude Code headless mode as a pure LLM API (no codebase context).

## Features

- ✅ Auto-approved search tools (Read, Grep, Glob, WebSearch)
- ✅ Real token usage tracking
- ✅ Multi-turn conversation support with session management
- ✅ OpenAI-compatible API format
- ✅ Docker support

## Quick Start

### Docker (Recommended)

```bash
# Clone the repo
git clone <your-repo-url>
cd nakle

# Set up environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run with docker-compose
docker-compose up -d

# Test the API
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "sonnet", "messages": [{"role": "user", "content": "Hello"}]}'
```

### Local Development

```bash
# Install dependencies
pip install -e .

# Install Claude CLI (if not already installed)
# Follow instructions at https://code.claude.com

# Run the server
uvicorn src.main:app --reload
```

## API Usage

### Basic Request

```bash
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "sonnet",
    "messages": [{"role": "user", "content": "What is 2+2?"}]
  }'
```

### Multi-Turn Conversation

```bash
# First message
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "sonnet",
    "messages": [{"role": "user", "content": "My name is Alice"}],
    "conversation_id": "conv-123"
  }'

# Follow-up (remembers context)
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "sonnet",
    "messages": [{"role": "user", "content": "What is my name?"}],
    "conversation_id": "conv-123"
  }'
```

## Deployment

### Azure VM

Minimum recommended: **B1ms** (1 vCPU, 2GB RAM, ~$15-20/month)

#### Option 1: Using API Key

```bash
# On your Azure VM
git clone <your-repo-url>
cd nakle

# Set up Docker
sudo apt update
sudo apt install docker.io docker-compose -y
sudo systemctl start docker
sudo systemctl enable docker

# Deploy
cp .env.example .env
# Edit .env with your API key
sudo docker-compose up -d
```

#### Option 2: Using Host Authentication (No API Key Needed)

```bash
# On your Azure VM
git clone <your-repo-url>
cd nakle

# Set up Docker
sudo apt update
sudo apt install docker.io docker-compose -y
sudo systemctl start docker
sudo systemctl enable docker

# Authenticate Claude CLI on host
claude login

# Edit docker-compose.yml and uncomment the volume line:
# - ${HOME}/.claude:/root/.claude:ro

# Deploy (no .env needed)
sudo docker-compose up -d
```

## Architecture

- `src/main.py` - FastAPI application with `/chat/completions` and `/health` endpoints
- `src/claude_runner.py` - Subprocess wrapper that runs `claude -p` with session management
- `src/models.py` - Pydantic models for request/response