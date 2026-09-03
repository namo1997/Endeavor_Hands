"""Request-local AEGIS identity and immutable working-root binding.

The MCP server may serve calls from more than one chat.  A process-global
"current workspace" would let one chat accidentally inherit another chat's
authority, so the active grant is carried in a ContextVar instead.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class EnvelopeContext:
    session_id: str
    working_envelope_id: str
    root: str
    capabilities: frozenset[str]
    expires_at: int


_CURRENT: ContextVar[EnvelopeContext | None] = ContextVar(
    "aegis_current_envelope", default=None
)


def current_context() -> EnvelopeContext | None:
    return _CURRENT.get()


def current_root() -> str | None:
    ctx = current_context()
    return ctx.root if ctx else None


def current_identity() -> tuple[str, str] | None:
    ctx = current_context()
    if not ctx:
        return None
    return ctx.session_id, ctx.working_envelope_id


@contextmanager
def bind_context(context: EnvelopeContext) -> Iterator[EnvelopeContext]:
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)
