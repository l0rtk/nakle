FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install Node.js (required for npm-installed Claude CLI)
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Claude CLI binary from build context
COPY claude /usr/local/bin/claude
RUN chmod 755 /usr/local/bin/claude

# Copy dependency files
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy application code
COPY src/ ./src/

# Create .claude directory with empty credentials file for mounting
RUN mkdir -p /root/.claude && touch /root/.claude/.credentials.json

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
