"""Entrypoint for the WhatsApp stdio MCP server and local connection status."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "whatsapp-mcp-server"))

if __name__ == "__main__":
    if "--status" in sys.argv:
        import json
        from bridge_runtime import connection_status
        print(json.dumps(connection_status()))
    else:
        from main import mcp
        mcp.run(transport="stdio")
