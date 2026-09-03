from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from aegis.context import current_context
from aegis.core import AegisError, AegisStore
from tools._safety import plan_write, resolve_path
from tools._sandbox import build_sandbox_profile


class AegisCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aegis-core-")
        base = Path(self.temp.name)
        self.root = base / "project"
        self.outside = base / "outside"
        self.data = base / "internal"
        self.root.mkdir()
        self.outside.mkdir()
        self.store = AegisStore(self.data)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _grant(self, *capabilities: str):
        return self.store.create_envelope(
            root=str(self.root),
            capabilities=capabilities or ("file_write",),
            ttl_minutes=30,
        )

    def test_exact_pair_capability_and_context_binding(self) -> None:
        grant = self._grant("file_write", "process_exec")
        with self.store.authorized_context(
            session_id=grant.session_id,
            working_envelope_id=grant.working_envelope_id,
            capability="process_exec",
            tool="test",
        ):
            self.assertEqual(current_context().root, os.path.realpath(self.root))
            self.assertEqual(resolve_path("result.txt"), str(self.root / "result.txt"))
        self.assertIsNone(current_context())

        with self.assertRaises(AegisError) as caught:
            self.store.authorize(
                session_id="session_wrong",
                working_envelope_id=grant.working_envelope_id,
                capability="process_exec",
                tool="test",
            )
        self.assertEqual(caught.exception.code, "ENVELOPE_NOT_FOUND")

        with self.assertRaises(AegisError) as caught:
            self.store.authorize(
                session_id=grant.session_id,
                working_envelope_id=grant.working_envelope_id,
                capability="git",
                tool="test",
            )
        self.assertEqual(caught.exception.code, "CAPABILITY_DENIED")

    def test_path_escape_and_symlink_parent_are_denied(self) -> None:
        grant = self._grant("file_write")
        link = self.root / "escape"
        link.symlink_to(self.outside, target_is_directory=True)
        for path in (str(self.outside / "x.txt"), str(link / "new.txt"), "../outside/y.txt"):
            with self.assertRaises(AegisError) as caught:
                self.store.authorize(
                    session_id=grant.session_id,
                    working_envelope_id=grant.working_envelope_id,
                    capability="file_write",
                    tool="test",
                    paths=(path,),
                )
            self.assertEqual(caught.exception.code, "PATH_OUTSIDE_ENVELOPE")

    def test_safety_layer_refuses_new_file_outside_bound_root(self) -> None:
        grant = self._grant("file_write")
        with self.store.authorized_context(
            session_id=grant.session_id,
            working_envelope_id=grant.working_envelope_id,
            capability="file_write",
            tool="test",
        ):
            target, error, note = plan_write(str(self.outside / "brand-new.txt"))
        self.assertEqual(target, str(self.outside / "brand-new.txt"))
        self.assertIn("PATH_OUTSIDE_ENVELOPE", error)
        self.assertIsNone(note)

    def test_optimistic_hash_detects_concurrent_modification(self) -> None:
        grant = self._grant("file_write")
        target = self.root / "notes.txt"
        target.write_text("version one", encoding="utf-8")
        state = self.store.file_state(
            session_id=grant.session_id,
            working_envelope_id=grant.working_envelope_id,
            path=str(target),
        )
        self.store.require_expected_hash(str(target), state["sha256"])
        target.write_text("version two", encoding="utf-8")
        with self.assertRaises(AegisError) as caught:
            self.store.require_expected_hash(str(target), state["sha256"])
        self.assertEqual(caught.exception.code, "CONCURRENT_MODIFICATION_DETECTED")

    def test_revocation_and_expiry_fail_closed(self) -> None:
        grant = self._grant("file_write")
        self.store.revoke(grant.session_id, grant.working_envelope_id)
        with self.assertRaises(AegisError) as caught:
            self.store.authorize(
                session_id=grant.session_id,
                working_envelope_id=grant.working_envelope_id,
                capability="file_write",
                tool="test",
            )
        self.assertEqual(caught.exception.code, "ENVELOPE_REVOKED")

        expiring = self._grant("file_write")
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "UPDATE envelopes SET expires_at=? WHERE working_envelope_id=?",
                (int(time.time()) - 1, expiring.working_envelope_id),
            )
        with self.assertRaises(AegisError) as caught:
            self.store.authorize(
                session_id=expiring.session_id,
                working_envelope_id=expiring.working_envelope_id,
                capability="file_write",
                tool="test",
            )
        self.assertEqual(caught.exception.code, "ENVELOPE_EXPIRED")

    def test_strict_sandbox_is_write_allowlist_and_global_unlink_deny(self) -> None:
        git_dir = self.root / ".git"
        git_dir.mkdir()
        profile = build_sandbox_profile(
            str(self.root),
            extra_unlink_paths=(str(git_dir),),
            strict_writes=True,
        )
        self.assertIn("; AEGIS Working Envelope is a write allow-list", profile)
        self.assertIn("(deny file-write*)", profile)
        self.assertIn("(deny file-write-unlink)", profile)
        self.assertIn(f'(allow file-write* (subpath "{self.root}")', profile)
        self.assertIn(f'(allow file-write-unlink (subpath "{git_dir}"))', profile)


if __name__ == "__main__":
    unittest.main()
