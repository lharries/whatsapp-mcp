# --- Stage 1: build the Go WhatsApp bridge (needs CGO for go-sqlite3) ---
FROM golang:1.25-bookworm AS bridge-build
WORKDIR /src
COPY whatsapp-bridge/go.mod whatsapp-bridge/go.sum ./
RUN go mod download
COPY whatsapp-bridge/ ./
RUN CGO_ENABLED=1 GOOS=linux go build -o /out/whatsapp-bridge .

# --- Stage 2: runtime image with the bridge binary + the Python MCP server ---
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Fixed-id, non-root runtime user. Both services (bridge and mcp) run as this
# user - see entrypoint.sh. The uid/gid are pinned so a pre-existing
# "whatsapp-store" volume from an older root-only deployment can be
# re-owned with a matching `chown -R 10001:10001` (documented in README.md,
# section "Migrando o volume existente para o usuario nao-root").
RUN groupadd -g 10001 appuser \
    && useradd -u 10001 -g appuser -M -s /usr/sbin/nologin appuser

WORKDIR /app/whatsapp-bridge
COPY --from=bridge-build /out/whatsapp-bridge ./whatsapp-bridge

WORKDIR /app/whatsapp-mcp-server
COPY whatsapp-mcp-server/pyproject.toml whatsapp-mcp-server/uv.lock ./
RUN uv sync --frozen
COPY whatsapp-mcp-server/ ./

WORKDIR /app
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Pre-create the store dir owned by appuser: when compose creates a brand-new
# named volume and mounts it here, Docker seeds it from this image path,
# copying this ownership into the volume. This does NOT retroactively fix an
# already-populated volume - see the migration note in README.md.
RUN mkdir -p /app/whatsapp-bridge/store \
    && chown -R appuser:appuser /app/whatsapp-bridge/store

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

VOLUME ["/app/whatsapp-bridge/store"]
EXPOSE 8080 8081

USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]
