"""AEGIS security boundary for Endeavor Hands."""

from .context import EnvelopeContext, current_context, current_identity, current_root
from .core import (
    AEGIS_CAPABILITIES,
    AegisError,
    AegisStore,
    EnvelopeGrant,
    sha256_file,
)

__all__ = [
    "AEGIS_CAPABILITIES",
    "AegisError",
    "AegisStore",
    "EnvelopeContext",
    "EnvelopeGrant",
    "current_context",
    "current_identity",
    "current_root",
    "sha256_file",
]
