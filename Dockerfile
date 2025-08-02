# Stage 1: Build Go bridge
FROM golang:1.24-bookworm AS builder-go
WORKDIR /src/whatsapp-bridge
COPY whatsapp-bridge/go.mod whatsapp-bridge/go.sum ./
RUN go mod download
COPY whatsapp-bridge/ ./
RUN CGO_ENABLED=1 go build -o /app/whatsapp-bridge main.go

# Stage 2: Install Python and tools
FROM python:3.11-slim-bookworm AS builder-py
WORKDIR /src/whatsapp-mcp-server
COPY whatsapp-mcp-server/pyproject.toml *.lock ./
RUN python -m venv /app/venv \
    && /app/venv/bin/pip install --upgrade pip \
    && /app/venv/bin/pip install "mcp[cli]>=1.6.0" httpx requests
COPY whatsapp-mcp-server/*.py /app/whatsapp-mcp-server/

# Stage 3: Final image
FROM python:3.11-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends tini ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1001 appgroup && useradd --uid 1001 --gid appgroup --create-home appuser
RUN mkdir /app /data && chown -R appuser:appgroup /app /data
WORKDIR /app
COPY --from=builder-go /app/whatsapp-bridge ./whatsapp-bridge
COPY --from=builder-py /app/venv ./venv
COPY --from=builder-py /app/whatsapp-mcp-server ./whatsapp-mcp-server
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x entrypoint.sh && chown appuser:appgroup entrypoint.sh
USER appuser
VOLUME /data
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
