"""config.py — Endeavor Hands configuration

This server has no local LLM, no web tools, no RAG, no multi-user identity
mapping, and no LangGraph orchestration — ChatGPT (or another MCP client) is
the planner. What remains here is exactly what the tools in tools/ import:
WORKSPACE; READ_FILE_*; MCP_*; LOG_DIR/LOG_MAX_ENTRIES.
"""
from __future__ import annotations
import os

# ── Workspace ─────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.getenv("V2_WORKSPACE", os.path.join(PROJECT_ROOT, "workspace"))
os.makedirs(WORKSPACE, exist_ok=True)


def get_workspace() -> str:
    """Return the request-local AEGIS root, or the legacy default workspace.

    The lazy import avoids making configuration depend on AEGIS during early
    interpreter startup and keeps existing unit-test overrides of WORKSPACE
    working when no envelope is bound.
    """
    try:
        from aegis.context import current_root
        bound = current_root()
    except Exception:
        bound = None
    return bound or WORKSPACE


# AEGIS authorization/audit state is an internal-operation area.  It is never
# part of a GPT mutation surface, even when the chosen envelope is an ancestor
# of this directory.
INTERNAL_WORK_ROOT = os.path.realpath(os.path.join(PROJECT_ROOT, "work"))
AEGIS_DATA_ROOT = os.path.realpath(
    os.path.expanduser(os.getenv("AEGIS_DATA_ROOT", os.path.join(INTERNAL_WORK_ROOT, "aegis")))
)

# ── read_file limits ──────────────────────────────────────────────────────
READ_FILE_MAX_CHARS = int(os.getenv("V2_READ_FILE_MAX_CHARS", "10000"))
READ_FILE_MAX_BYTES = int(os.getenv("V2_READ_FILE_MAX_BYTES", str(50 * 1024 * 1024)))
READ_FILE_AUDIO_VIDEO_MAX_BYTES = int(os.getenv("V2_READ_FILE_AUDIO_VIDEO_MAX_BYTES", str(500 * 1024 * 1024)))
READ_FILE_AUDIO_VIDEO_MAX_DURATION_SEC = int(os.getenv("V2_READ_FILE_AUDIO_VIDEO_MAX_DURATION_SEC", str(90 * 60)))

# ── MCP bridge (mcp_list_tools / mcp_call_tool / mcp_add_server / mcp_remove_server) ──
# Supports Streamable HTTP and local stdio. HTTP entries use {"url", "headers"};
# stdio entries use {"transport": "stdio", "command": <absolute executable>,
# "args": [...], "cwd": <path inside WORKSPACE>}. Dynamic registrations live
# under Endeavor_Hands/work/tool_mcp/ rather than in WORKSPACE.
# Example (not enabled):
#   MCP_SERVERS = {"worldmonitor": {"url": "https://worldmonitor.app/mcp",
#                                    "headers": {"X-WorldMonitor-Key": os.getenv("WORLDMONITOR_API_KEY", "")}}}
MCP_SERVERS: dict[str, dict] = {}
MCP_MAX_CHARS = int(os.getenv("V2_MCP_MAX_CHARS", "4000"))
MCP_TIMEOUT = int(os.getenv("V2_MCP_TIMEOUT", "60"))  # seconds per list_tools/call_tool round trip

# ── Activity logging (agent_log.AgentLogger) ──────────────────────────────
LOG_DIR = os.getenv("V2_LOG_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))
LOG_MAX_ENTRIES = int(os.getenv("V2_LOG_MAX_ENTRIES", "5000"))
os.makedirs(LOG_DIR, exist_ok=True)
