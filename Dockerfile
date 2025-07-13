# Use a base image with both Go and Python
FROM golang:1.21-bullseye

# Install Python and other dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Set up Python environment
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install uv

# Set up Go environment
ENV CGO_ENABLED=1
ENV GO111MODULE=on

# Create working directory
WORKDIR /app

# Copy the project files
COPY . .

# Build the Go WhatsApp bridge
WORKDIR /app/whatsapp-bridge
RUN go mod download
RUN go build -o whatsapp-bridge

# Set up Python MCP server
WORKDIR /app/whatsapp-mcp-server
RUN uv pip install -r requirements.txt

# Create directories for persistent storage
RUN mkdir -p /app/whatsapp-bridge/store

# Expose ports
EXPOSE 8080 8081

# Set up entrypoint script
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]