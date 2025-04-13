# Stage 1: Build the Go application
FROM golang:1.24-bookworm AS builder-go

WORKDIR /src/whatsapp-bridge

# Copy Go module files and download dependencies
COPY whatsapp-bridge/go.mod whatsapp-bridge/go.sum ./
RUN go mod download

# Copy the Go source code
COPY whatsapp-bridge/ ./

# Build the Go application
RUN go build -o /app/whatsapp-bridge main.go

# Stage 2: Prepare Python environment
FROM python:3.11-slim-bookworm AS builder-python

WORKDIR /src/whatsapp-mcp-server

# Copy Python project files
COPY whatsapp-mcp-server/pyproject.toml ./

# Create and activate virtual environment, then install dependencies directly from pyproject.toml
RUN python -m venv /app/venv && \
    . /app/venv/bin/activate && \
    pip install --upgrade pip && \
    pip install httpx>=0.28.1 mcp[cli]>=1.6.0 requests>=2.32.3

# Copy Python code files (after dependency installation to leverage Docker caching)
COPY whatsapp-mcp-server/*.py /app/whatsapp-mcp-server/


# Stage 3: Final image
FROM python:3.11-slim-bookworm

# Set non-interactive frontend
ENV DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies (ffmpeg for audio, ca-certificates for HTTPS in Go/Python)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg ca-certificates tini && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user and group
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --shell /bin/bash --create-home appuser

# Create application directory and data directory
RUN mkdir /app && mkdir /data && chown -R appuser:appgroup /app /data

WORKDIR /app

# Copy built Go binary from builder stage
COPY --from=builder-go /app/whatsapp-bridge /app/whatsapp-bridge

# Copy Python code and virtual environment from builder stage
COPY --from=builder-python /app/venv /app/venv
COPY --from=builder-python /app/whatsapp-mcp-server /app/whatsapp-mcp-server

# Copy the entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && chown appuser:appgroup /app/entrypoint.sh

# Ensure the app directory is owned by appuser
RUN chown -R appuser:appgroup /app

# Define the mount point for persistent data (SQLite DBs, downloaded media)
VOLUME /data

# Switch to the non-root user
USER appuser

# Use Tini as the init system to handle signals properly
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]