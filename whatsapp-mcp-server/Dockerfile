# Python WhatsApp MCP Server
FROM python:3.11-slim

WORKDIR /app

# Install uv for fast package management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen

# Copy source code
COPY *.py ./

# Environment variables
ENV BRIDGE_URL=http://localhost:8080
ENV DATABASE_PATH=/data/messages.db

# Expose MCP port (if using stdio, this may not be needed)
EXPOSE 8082

# Run the MCP server
CMD ["uv", "run", "python", "main.py"]
