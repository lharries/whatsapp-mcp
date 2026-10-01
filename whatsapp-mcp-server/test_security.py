import asyncio
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import io
from pathlib import Path
import sqlite3
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import main
import whatsapp
import bridge_runtime


class ClientBoundaryTests(unittest.TestCase):
    def test_token_proxy_redirect_and_loopback_policy(self):
        session = MagicMock()
        session.__enter__.return_value = session
        with patch.object(bridge_runtime, "configure", return_value="a" * 64), patch.object(bridge_runtime, "ensure_bridge"), patch.object(bridge_runtime, "wait_for_connection"), patch.object(bridge_runtime.requests, "Session", return_value=session):
            bridge_runtime.request("POST", "send", payload={"message": "hello"})
        self.assertFalse(session.trust_env)
        args, kwargs = session.request.call_args
        self.assertEqual(args, ("POST", "https://127.0.0.1:18765/api/send"))
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer " + "a" * 64})
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (3, 120))
        self.assertEqual(kwargs["verify"], str(bridge_runtime.STATE / "bridge-cert.pem"))

    def test_wrong_server_identity_fails_without_starting_another_bridge(self):
        with patch.object(bridge_runtime, "request", side_effect=bridge_runtime.requests.exceptions.SSLError("wrong identity")), patch.object(bridge_runtime, "state_lock", return_value=nullcontext()), patch.object(bridge_runtime.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "identity"):
                bridge_runtime.ensure_bridge("synthetic")
            spawn.assert_not_called()

    def test_platform_binary_names(self):
        with patch.object(bridge_runtime.os, "name", "nt"):
            self.assertEqual(bridge_runtime.bridge_binary().name, "whatsapp-bridge.exe")
        with patch.object(bridge_runtime.os, "name", "posix"):
            self.assertEqual(bridge_runtime.bridge_binary().name, "whatsapp-bridge")

    def test_missing_binary_has_actionable_error_without_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "runtime"
            with patch.object(bridge_runtime, "STATE", state), patch.object(bridge_runtime, "bridge_binary", return_value=Path(directory) / "missing"):
                with self.assertRaisesRegex(RuntimeError, "build the whatsapp-bridge package"):
                    bridge_runtime.configure()
            self.assertFalse(state.exists())

    @unittest.skipUnless(bridge_runtime.bridge_binary().is_file(), "build bridge to test TLS initialization")
    def test_concurrent_first_configuration_preserves_one_identity(self):
        # Isolated private state, initialization-only binary invocation; no bridge or network.
        script = "import sys, hashlib; from pathlib import Path; import bridge_runtime; bridge_runtime.STATE=Path(sys.argv[1]); print(hashlib.sha256(bridge_runtime.configure().encode()).hexdigest())"
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "runtime"
            def initialize(_):
                return subprocess.check_output([sys.executable, "-c", script, str(state)], cwd=bridge_runtime.ROOT, text=True).strip()
            with ThreadPoolExecutor(max_workers=3) as executor:
                digests = list(executor.map(initialize, range(3)))
            self.assertEqual(len(set(digests)), 1)
            before = (state / "bridge-cert.pem").read_bytes()
            self.assertEqual(initialize(0), digests[0])
            self.assertEqual((state / "bridge-cert.pem").read_bytes(), before)

    def test_sending_waits_for_paired_connection(self):
        response = MagicMock()
        response.json.side_effect = [{"paired": True, "connected": False}, {"paired": True, "connected": True}]
        with patch.object(bridge_runtime, "request", return_value=response) as request, patch.object(bridge_runtime.time, "sleep"):
            bridge_runtime.wait_for_connection()
            self.assertEqual(request.call_count, 2)
        response.json.side_effect = [{"paired": False, "connected": True}]
        with patch.object(bridge_runtime, "request", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "pairing"):
                bridge_runtime.wait_for_connection()

    def test_all_sending_and_download_paths_use_shared_client(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"success": True, "message": "ok", "path": "safe-path"}
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "normal audio.ogg"
            file.write_bytes(b"test fixture")
            with patch.object(whatsapp, "bridge_request", return_value=response) as request:
                self.assertTrue(whatsapp.send_message("123", "hello")[0])
                self.assertTrue(whatsapp.send_file("123", str(file))[0])
                self.assertTrue(whatsapp.send_audio_message("123", str(file))[0])
                self.assertEqual(whatsapp.download_media("id", "chat"), "safe-path")
                self.assertEqual([call.args for call in request.call_args_list], [("POST", "send")] * 3 + [("POST", "download")])

    def test_unknown_endpoint_rejected_before_side_effects(self):
        with patch.object(bridge_runtime, "configure") as configure:
            with self.assertRaises(ValueError):
                bridge_runtime.request("GET", "../steal")
            configure.assert_not_called()


class MessageCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "messages.db"
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE chats(jid TEXT PRIMARY KEY, name TEXT, last_message_time TEXT);
            CREATE TABLE messages(id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TEXT, is_from_me BOOLEAN, media_type TEXT);
            INSERT INTO chats VALUES('123@s.whatsapp.net','Test Contact','2026-10-01T12:00:00');
            INSERT INTO messages VALUES('fixture-message','123@s.whatsapp.net','123','hello fixture','2026-10-01T12:00:00',0,'');
        """)
        connection.close()
        self.patcher = patch.object(whatsapp, "MESSAGES_DB_PATH", str(path))
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_normal_reads_and_optional_last_message(self):
        self.assertIn("hello fixture", whatsapp.list_messages(include_context=False))
        self.assertEqual(whatsapp.list_chats()[0].last_message, "hello fixture")
        self.assertIsNone(whatsapp.list_chats(include_last_message=False)[0].last_message)
        self.assertEqual(whatsapp.get_chat("123@s.whatsapp.net").name, "Test Contact")
        self.assertIsNone(whatsapp.get_chat("123@s.whatsapp.net", False).last_message)

    def test_mcp_tools_validate_real_results(self):
        async def run():
            for name, arguments in [
                ("search_contacts", {"query": "Test"}),
                ("list_chats", {"include_last_message": False}),
                ("list_messages", {"include_context": False}),
                ("get_chat", {"chat_jid": "123@s.whatsapp.net"}),
                ("get_chat", {"chat_jid": "missing"}),
                ("get_direct_chat_by_contact", {"sender_phone_number": "123"}),
                ("get_contact_chats", {"jid": "123"}),
                ("get_last_interaction", {"jid": "123"}),
                ("get_message_context", {"message_id": "fixture-message"}),
            ]:
                result = await main.mcp.call_tool(name, arguments)
                self.assertTrue(result, name)
        asyncio.run(run())

    def test_database_error_does_not_corrupt_stdio(self):
        with patch.object(whatsapp, "MESSAGES_DB_PATH", str(Path(self.tmp.name) / "absent" / "db")), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            whatsapp.search_contacts("fixture")
            self.assertEqual(stdout.getvalue(), "")


class TransportTests(unittest.TestCase):
    def test_installed_entrypoint_initialize_and_list_tools(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def run():
            params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve().parent.parent / "launch_mcp.py")])
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    result = await session.initialize()
                    self.assertEqual(result.serverInfo.name, "whatsapp")
                    tools = await session.list_tools()
                    self.assertEqual(len(tools.tools), 13)
                    self.assertIn("check_connection", {tool.name for tool in tools.tools})
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
