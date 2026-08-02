#!/bin/sh
# Single image, two roles. docker-compose selects the role via `command:`
# (see docker-compose.yml) so both the whatsapp-bridge and whatsapp-mcp
# services can be built from the same image without duplicating a Dockerfile.
set -e

role="${1:-}"

case "$role" in
  bridge)
    cd /app/whatsapp-bridge
    exec ./whatsapp-bridge
    ;;
  mcp)
    cd /app/whatsapp-mcp-server
    # Run the venv's interpreter directly instead of `uv run`: the venv was
    # already synced at build time (uv sync --frozen), and the container
    # runs as a non-root user with a read-only root filesystem, so there is
    # no writable place for `uv` to resync/cache into at startup even if it
    # wanted to.
    exec ./.venv/bin/python main.py
    ;;
  *)
    echo "Usage: entrypoint.sh {bridge|mcp}" >&2
    exit 1
    ;;
esac
