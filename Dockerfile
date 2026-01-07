FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy Claude CLI binary from build context
COPY --chmod=755 claude /usr/local/bin/claude

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
