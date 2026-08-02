"""main.py must build a FastMCP server configured for long-lived streamable-http,
without ever starting a real server during import/tests.
"""
import importlib
from unittest.mock import MagicMock


def _reload_main():
    import main
    return importlib.reload(main)


def test_fastmcp_defaults_to_stateless_streamable_http(clean_env):
    mod = _reload_main()
    try:
        assert mod.mcp.settings.host == "0.0.0.0"
        assert mod.mcp.settings.port == 8081
        assert mod.mcp.settings.stateless_http is True
        assert mod.mcp.settings.json_response is True
    finally:
        _reload_main()


def test_fastmcp_respects_mcp_host_and_port_env(clean_env):
    clean_env.setenv("MCP_HOST", "127.0.0.1")
    clean_env.setenv("MCP_PORT", "9000")
    mod = _reload_main()
    try:
        assert mod.mcp.settings.host == "127.0.0.1"
        assert mod.mcp.settings.port == 9000
    finally:
        _reload_main()


def test_transport_security_restricts_allowed_hosts(clean_env):
    mod = _reload_main()
    try:
        allowed = mod.mcp.settings.transport_security.allowed_hosts
        assert "127.0.0.1:*" in allowed
        assert "localhost:*" in allowed
    finally:
        _reload_main()


def test_importing_main_does_not_start_a_real_server(clean_env, monkeypatch):
    """Importing/reloading main.py must never call mcp.run() itself -
    that only happens behind `if __name__ == "__main__"`."""
    from mcp.server.fastmcp import FastMCP

    run_mock = MagicMock()
    monkeypatch.setattr(FastMCP, "run", run_mock)

    _reload_main()

    run_mock.assert_not_called()
