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

# Copy Claude CLI binary to project directory
cp ~/.local/bin/claude ./
# Or if installed via npm:
# cp ~/.npm-global/bin/claude ./

# Authenticate with Claude CLI on host
claude login

# Update docker-compose.yml credentials path
# Comment out line 14 and uncomment line 16, updating 'azureuser' with your username

# Run with docker-compose
sudo docker compose up -d

# Test the API
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "haiku", "messages": [{"role": "user", "content": "Hello"}]}'
```

**Note**: The Docker setup mounts your Claude credentials from `~/.claude/.credentials.json`. Make sure you've run `claude login` on the host machine before starting the container.

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

```bash
# On your Azure VM
git clone <your-repo-url>
cd nakle

# Set up Docker
sudo apt update
sudo apt install docker.io docker-compose -y
sudo systemctl start docker
sudo systemctl enable docker

# Install Claude CLI (if not already installed)
# Follow instructions at https://code.claude.com

# Copy Claude CLI binary to project directory
cp ~/.local/bin/claude ./
# Or if installed via npm:
cp ~/.npm-global/bin/claude ./

# Authenticate Claude CLI
claude login

# Update docker-compose.yml credentials path
# Comment out line 14 (/home/luka) and uncomment line 16
# Update 'azureuser' with your VM username if different
nano docker-compose.yml

# Deploy
sudo docker compose up -d

# Verify it's working
curl -X POST http://localhost:8000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "haiku", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Architecture

- `src/main.py` - FastAPI application with `/chat/completions` and `/health` endpoints
- `src/claude_runner.py` - Subprocess wrapper that runs `claude -p` with session management
- `src/models.py` - Pydantic models for request/response