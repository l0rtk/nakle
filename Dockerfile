FROM python:3.11-slim

# Install dependencies and Claude CLI
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && curl -fsSL https://raw.githubusercontent.com/anthropics/claude-code/main/install.sh | sh \
    && mv /root/.local/bin/claude /usr/local/bin/claude \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy application code
COPY src/ ./src/

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
