# Combined WhatsApp MCP Server Dockerfile
# Includes both Go (for bridge) and Python (for MCP server) runtimes
FROM golang:1.24-bookworm AS go-builder

# Install necessary packages for CGO
RUN apt-get update && apt-get install -y \
    gcc \
    libc6-dev \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy go mod files first for better caching
COPY whatsapp-bridge/go.mod whatsapp-bridge/go.sum ./
RUN go mod download

# Copy bridge source code
COPY whatsapp-bridge/ ./

# Enable CGO for sqlite3 and build the application
ENV CGO_ENABLED=1
RUN go build -o whatsapp-bridge main.go

# Final stage - Python with Go runtime
FROM python:3.11-slim-bookworm

# Install system dependencies including Go runtime, ffmpeg, and sqlite
RUN apt-get update && apt-get install -y \
    golang-go \
    ffmpeg \
    sqlite3 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the compiled bridge binary from builder stage
COPY --from=go-builder /build/whatsapp-bridge ./whatsapp-bridge/whatsapp-bridge

# Copy bridge source code for the automatic management system
COPY whatsapp-bridge/ ./whatsapp-bridge/

# Install uv for fast Python package management
RUN pip install uv

# Copy Python requirements and install dependencies
COPY whatsapp-mcp-server/pyproject.toml whatsapp-mcp-server/uv.lock ./whatsapp-mcp-server/
WORKDIR /app/whatsapp-mcp-server
RUN uv sync --frozen

# Copy the MCP server source code
COPY whatsapp-mcp-server/ ./

# Create directories for data storage
RUN mkdir -p ../whatsapp-bridge/store
RUN mkdir -p ../qr-codes

# Create a non-root user for security but ensure proper permissions
RUN useradd -m -u 1000 mcpuser && \
    chown -R mcpuser:mcpuser /app
USER mcpuser

# Expose both MCP server port and bridge API port
EXPOSE 3000 8080

# Set environment variables for proper paths
ENV WHATSAPP_DB_PATH=/app/whatsapp-bridge/store
ENV GOPATH=/tmp/go
ENV GOROOT=/usr/lib/go-1.24

# Run the MCP server - it will automatically manage the bridge process
CMD ["uv", "run", "main.py"]