from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

import server
from aegis.core import AegisStore
from tools import _edit_grants


class AegisServerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aegis-server-")
        base = Path(self.temp.name)
        self.root = base / "project"
        self.root.mkdir()
        self._old_store = server._AEGIS
        server._AEGIS = AegisStore(base / "internal")
        _edit_grants._GRANTED.clear()
        _edit_grants._PENDING.clear()

    def tearDown(self) -> None:
        server._AEGIS = self._old_store
        _edit_grants._GRANTED.clear()
        _edit_grants._PENDING.clear()
        self.temp.cleanup()

    def _start(self, capabilities: list[str]) -> dict:
        result = server.aegis_start_session(
            root=str(self.root),
            capabilities_json=json.dumps(capabilities),
            ttl_minutes=30,
        )
        return json.loads(result)

    def test_effectful_tools_require_exact_pair_and_capability(self) -> None:
        denied = server.bash(command="pwd")
        self.assertIn("AEGIS:ENVELOPE_NOT_FOUND", denied)

        identity = self._start(["file_write"])
        denied = server.bash(
            command="pwd",
            session_id=identity["sessionId"],
            working_envelope_id=identity["workingEnvelopeId"],
        )
        self.assertIn("AEGIS:CAPABILITY_DENIED", denied)

        denied = server.write_file(
            path="x.txt",
            content="x",
            session_id="session_wrong",
            working_envelope_id=identity["workingEnvelopeId"],
        )
        self.assertIn("AEGIS:ENVELOPE_NOT_FOUND", denied)

    def test_mcp_schema_exposes_control_plane_and_identity_on_effects(self) -> None:
        tools = server.mcp._tool_manager._tools
        for name in ("aegis_start_session", "aegis_status", "aegis_file_state", "aegis_revoke"):
            self.assertIn(name, tools)
        for name in (
            "bash", "git", "bash_bg", "python_exec", "write_file", "edit",
            "computer", "mcp_list_tools", "mcp_call_tool", "mcp_add_server",
            "mcp_remove_server",
        ):
            properties = tools[name].parameters["properties"]
            self.assertIn("session_id", properties, name)
            self.assertIn("working_envelope_id", properties, name)
        self.assertIn("expected_hash", tools["edit"].parameters["properties"])
        self.assertIn("expected_hash", tools["write_file"].parameters["properties"])

    def test_file_write_hash_grant_and_revocation_flow(self) -> None:
        identity = self._start(["file_write"])
        args = {
            "session_id": identity["sessionId"],
            "working_envelope_id": identity["workingEnvelopeId"],
        }
        created = server.write_file(path="notes.txt", content="one", **args)
        self.assertIn("written", created)
        self.assertEqual((self.root / "notes.txt").read_text(encoding="utf-8"), "one")

        state = json.loads(server.aegis_file_state(path="notes.txt", **args))
        stale = server.write_file(
            path="notes.txt",
            content="two",
            overwrite=True,
            expected_hash="0" * 64,
            **args,
        )
        self.assertIn("CONCURRENT_MODIFICATION_DETECTED", stale)

        permission = server.write_file(
            path="notes.txt",
            content="two",
            overwrite=True,
            expected_hash=state["sha256"],
            **args,
        )
        self.assertIn("permission_required", permission)
        match = re.search(r'grant_phrase="([0-9a-f]+)"', permission)
        self.assertIsNotNone(match)

        overwritten = server.write_file(
            path="notes.txt",
            content="two",
            overwrite=True,
            expected_hash=state["sha256"],
            grant_phrase=match.group(1),
            **args,
        )
        self.assertIn("overwrote", overwritten)
        self.assertEqual((self.root / "notes.txt").read_text(encoding="utf-8"), "two")

        revoked = json.loads(server.aegis_revoke(**args))
        self.assertEqual(revoked["state"], "REVOKED")
        denied = server.write_file(path="after.txt", content="blocked", **args)
        self.assertIn("AEGIS:ENVELOPE_REVOKED", denied)
        self.assertFalse((self.root / "after.txt").exists())


if __name__ == "__main__":
    unittest.main()
