# Python MCP server
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install UV (Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy project files
COPY pyproject.toml uv.lock ./
COPY whatsapp.py audio.py main.py ./

# Install dependencies using UV
RUN uv sync

# Expose no ports (uses stdio for MCP)
CMD ["uv", "run", "python", "main.py"]
