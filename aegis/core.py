"""Durable AEGIS session and Working Envelope authorization core.

Every effectful call is selected by the exact ``session_id +
working_envelope_id`` pair.  The canonical root and capability set are
immutable for the grant lifetime.  Authorization is fail-closed on missing,
expired, revoked, cross-session, out-of-root, or concurrent-modification
requests.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Iterable, Iterator, Sequence

from .context import EnvelopeContext, bind_context


AEGIS_CAPABILITIES = frozenset(
    {
        "file_write",
        "process_exec",
        "git",
        "computer_control",
        "mcp_call",
        "mcp_manage",
    }
)

_BLOCKED_ROOTS = (
    "/System",
    "/Library",
    "/Applications",
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/private/etc",
)


class AegisError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    def render(self) -> str:
        return f"[AEGIS:{self.code}] {self}"


@dataclass(frozen=True)
class EnvelopeGrant:
    session_id: str
    working_envelope_id: str
    root: str
    capabilities: frozenset[str]
    state: str
    created_at: int
    expires_at: int
    revoked_at: int | None

    def as_context(self) -> EnvelopeContext:
        return EnvelopeContext(
            session_id=self.session_id,
            working_envelope_id=self.working_envelope_id,
            root=self.root,
            capabilities=self.capabilities,
            expires_at=self.expires_at,
        )


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def _canonical_target(path: str, root: str) -> str:
    expanded = os.path.expanduser(path)
    candidate = expanded if os.path.isabs(expanded) else os.path.join(root, expanded)

    # realpath() resolves an existing symlink target.  For a path that does not
    # exist yet, resolve the nearest existing ancestor first so a symlinked
    # parent cannot smuggle a create outside the envelope.
    probe = os.path.abspath(candidate)
    suffix: list[str] = []
    while not os.path.lexists(probe):
        parent, name = os.path.split(probe)
        if parent == probe:
            break
        suffix.append(name)
        probe = parent
    resolved = os.path.realpath(probe)
    for name in reversed(suffix):
        resolved = os.path.join(resolved, name)
    return os.path.normpath(resolved)


class AegisStore:
    """SQLite-backed grant and audit store with owner-only local state."""

    def __init__(self, data_root: str | os.PathLike[str]):
        self.data_root = os.path.realpath(os.path.expanduser(str(data_root)))
        Path(self.data_root).mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.data_root, 0o700)
        self.db_path = os.path.join(self.data_root, "aegis.sqlite3")
        try:
            configured_audit_limit = int(os.getenv("AEGIS_AUDIT_MAX_ENTRIES", "20000"))
        except ValueError:
            configured_audit_limit = 20_000
        self.audit_max_entries = max(100, configured_audit_limit)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS envelopes (
                    working_envelope_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    root TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'REVOKED')),
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER
                );
                CREATE UNIQUE INDEX IF NOT EXISTS envelopes_exact_pair
                    ON envelopes(session_id, working_envelope_id);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    session_id TEXT,
                    working_envelope_id TEXT,
                    tool TEXT NOT NULL,
                    capability TEXT,
                    decision TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                );
                """
            )
        os.chmod(self.db_path, 0o600)

    def _audit(
        self,
        *,
        session_id: str | None,
        working_envelope_id: str | None,
        tool: str,
        capability: str | None,
        decision: str,
        detail: dict | None = None,
    ) -> None:
        payload = json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO audit
                   (timestamp, session_id, working_envelope_id, tool,
                    capability, decision, detail_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(time.time()),
                    session_id,
                    working_envelope_id,
                    tool,
                    capability,
                    decision,
                    payload,
                ),
            )
            conn.execute(
                """DELETE FROM audit WHERE id <= COALESCE(
                       (SELECT MAX(id) FROM audit), 0
                   ) - ?""",
                (self.audit_max_entries,),
            )

    def _validate_root(self, root: str) -> str:
        expanded = os.path.expanduser(root)
        if not os.path.isabs(expanded):
            raise AegisError("INVALID_ROOT", "root must be an existing absolute directory")
        canonical = os.path.realpath(expanded)
        if not os.path.isdir(canonical):
            raise AegisError("INVALID_ROOT", "root must be an existing absolute directory")
        home = os.path.realpath(os.path.expanduser("~"))
        if canonical in {"/", home}:
            raise AegisError("ROOT_TOO_BROAD", "root cannot be / or the whole home directory")
        for blocked in _BLOCKED_ROOTS:
            blocked_real = os.path.realpath(blocked)
            if canonical == blocked_real or canonical.startswith(blocked_real + os.sep):
                raise AegisError("PROTECTED_ROOT", f"root is protected: {blocked}")
        if canonical == self.data_root or canonical.startswith(self.data_root + os.sep):
            raise AegisError("INTERNAL_ROOT", "AEGIS internal data cannot be a working root")
        return canonical

    @staticmethod
    def _normalize_capabilities(capabilities: Iterable[str]) -> frozenset[str]:
        normalized = frozenset(str(value).strip() for value in capabilities if str(value).strip())
        unknown = normalized - AEGIS_CAPABILITIES
        if unknown:
            raise AegisError(
                "UNKNOWN_CAPABILITY", f"unsupported capabilities: {', '.join(sorted(unknown))}"
            )
        if not normalized:
            raise AegisError("EMPTY_CAPABILITIES", "at least one capability is required")
        return normalized

    def create_envelope(
        self,
        *,
        root: str,
        capabilities: Iterable[str],
        ttl_minutes: int = 480,
    ) -> EnvelopeGrant:
        canonical = self._validate_root(root)
        normalized = self._normalize_capabilities(capabilities)
        if ttl_minutes < 5 or ttl_minutes > 7 * 24 * 60:
            raise AegisError("INVALID_TTL", "ttl_minutes must be between 5 and 10080")
        now = int(time.time())
        grant = EnvelopeGrant(
            session_id="session_" + secrets.token_urlsafe(24),
            working_envelope_id="we_" + secrets.token_urlsafe(24),
            root=canonical,
            capabilities=normalized,
            state="ACTIVE",
            created_at=now,
            expires_at=now + ttl_minutes * 60,
            revoked_at=None,
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO envelopes
                   (working_envelope_id, session_id, root, capabilities_json,
                    state, created_at, expires_at, revoked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    grant.working_envelope_id,
                    grant.session_id,
                    grant.root,
                    json.dumps(sorted(grant.capabilities)),
                    grant.state,
                    grant.created_at,
                    grant.expires_at,
                ),
            )
        self._audit(
            session_id=grant.session_id,
            working_envelope_id=grant.working_envelope_id,
            tool="aegis_start_session",
            capability=None,
            decision="ACTIVE",
            detail={"root": grant.root, "capabilities": sorted(grant.capabilities)},
        )
        return grant

    @staticmethod
    def _row_to_grant(row: sqlite3.Row) -> EnvelopeGrant:
        return EnvelopeGrant(
            session_id=row["session_id"],
            working_envelope_id=row["working_envelope_id"],
            root=row["root"],
            capabilities=frozenset(json.loads(row["capabilities_json"])),
            state=row["state"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

    def get(self, session_id: str, working_envelope_id: str) -> EnvelopeGrant:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM envelopes
                   WHERE session_id=? AND working_envelope_id=?""",
                (session_id, working_envelope_id),
            ).fetchone()
        if row is None:
            raise AegisError("ENVELOPE_NOT_FOUND", "exact session/envelope pair was not found")
        return self._row_to_grant(row)

    def status(self, session_id: str, working_envelope_id: str) -> EnvelopeGrant:
        grant = self.get(session_id, working_envelope_id)
        if grant.state == "ACTIVE" and grant.expires_at <= int(time.time()):
            return EnvelopeGrant(**{**grant.__dict__, "state": "EXPIRED"})
        return grant

    def revoke(self, session_id: str, working_envelope_id: str) -> EnvelopeGrant:
        grant = self.get(session_id, working_envelope_id)
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """UPDATE envelopes SET state='REVOKED', revoked_at=?
                   WHERE session_id=? AND working_envelope_id=?""",
                (now, session_id, working_envelope_id),
            )
        self._audit(
            session_id=session_id,
            working_envelope_id=working_envelope_id,
            tool="aegis_revoke",
            capability=None,
            decision="REVOKED",
        )
        return EnvelopeGrant(**{**grant.__dict__, "state": "REVOKED", "revoked_at": now})

    def _assert_path(self, grant: EnvelopeGrant, path: str) -> str:
        canonical = _canonical_target(path, grant.root)
        if not _inside(canonical, grant.root):
            raise AegisError(
                "PATH_OUTSIDE_ENVELOPE",
                f"path escapes immutable working root: {canonical}",
            )
        if canonical == self.data_root or canonical.startswith(self.data_root + os.sep):
            raise AegisError("INTERNAL_PATH", "AEGIS internal data is not accessible")
        return canonical

    def authorize(
        self,
        *,
        session_id: str,
        working_envelope_id: str,
        capability: str,
        tool: str,
        paths: Sequence[str] = (),
    ) -> EnvelopeGrant:
        try:
            grant = self.get(session_id, working_envelope_id)
            if grant.state != "ACTIVE":
                raise AegisError("ENVELOPE_REVOKED", "working envelope is not active")
            if grant.expires_at <= int(time.time()):
                raise AegisError("ENVELOPE_EXPIRED", "working envelope has expired")
            if capability not in grant.capabilities:
                raise AegisError(
                    "CAPABILITY_DENIED", f"working envelope lacks capability: {capability}"
                )
            canonical_paths = [self._assert_path(grant, path) for path in paths if path]
        except AegisError as exc:
            self._audit(
                session_id=session_id or None,
                working_envelope_id=working_envelope_id or None,
                tool=tool,
                capability=capability,
                decision="DENY",
                detail={"code": exc.code},
            )
            raise
        self._audit(
            session_id=session_id,
            working_envelope_id=working_envelope_id,
            tool=tool,
            capability=capability,
            decision="ALLOW",
            detail={"paths": canonical_paths},
        )
        return grant

    @contextmanager
    def authorized_context(
        self,
        *,
        session_id: str,
        working_envelope_id: str,
        capability: str,
        tool: str,
        paths: Sequence[str] = (),
    ) -> Iterator[EnvelopeGrant]:
        grant = self.authorize(
            session_id=session_id,
            working_envelope_id=working_envelope_id,
            capability=capability,
            tool=tool,
            paths=paths,
        )
        with bind_context(grant.as_context()):
            yield grant

    def file_state(
        self,
        *,
        session_id: str,
        working_envelope_id: str,
        path: str,
    ) -> dict:
        # file_state is bound to file_write authority because it exists to
        # obtain the optimistic-concurrency token for a later mutation.
        grant = self.authorize(
            session_id=session_id,
            working_envelope_id=working_envelope_id,
            capability="file_write",
            tool="aegis_file_state",
            paths=(path,),
        )
        canonical = self._assert_path(grant, path)
        if not os.path.exists(canonical):
            return {"path": canonical, "exists": False, "sha256": None, "size": None}
        if not os.path.isfile(canonical):
            return {"path": canonical, "exists": True, "type": "directory", "sha256": None}
        stat = os.stat(canonical)
        return {
            "path": canonical,
            "exists": True,
            "type": "file",
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(canonical),
        }

    def require_expected_hash(self, path: str, expected_hash: str) -> str:
        canonical = os.path.realpath(path)
        if not os.path.isfile(canonical):
            raise AegisError("FILE_NOT_FOUND", f"existing file required: {canonical}")
        if not expected_hash:
            raise AegisError(
                "EXPECTED_HASH_REQUIRED",
                "inspect the file with aegis_file_state and pass its sha256 as expected_hash",
            )
        actual = sha256_file(canonical)
        if not secrets.compare_digest(actual, expected_hash.strip().lower()):
            raise AegisError(
                "CONCURRENT_MODIFICATION_DETECTED",
                "the file changed after it was inspected; read it again before retrying",
            )
        return actual
