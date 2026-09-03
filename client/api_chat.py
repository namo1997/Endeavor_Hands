#!/usr/bin/env python3
"""Interactive Responses API client backed by an OpenAI Secure MCP Tunnel.

Credentials and the tunnel identifier are read from environment variables. The
launcher in ``scripts/start_api_chat.command`` keeps both values in macOS
Keychain and exports them only to this process.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any


RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6"
DEFAULT_TIMEOUT_SECONDS = 600

AGENT_INSTRUCTIONS = """You are the planning agent for Endeavor Hands on the user's Mac.
The MCP server exposes local tools protected by AEGIS Working Envelopes.

Safety and authorization rules:
- Do not call aegis_start_session until the user explicitly authorizes the exact
  task, absolute root directory, capabilities, and a bounded duration.
- Use the exact session_id + working_envelope_id returned for every effectful
  tool call. Never reuse authority from another task or conversation.
- Use the least capabilities and the narrowest root that can complete the task.
- Before editing or replacing an existing file, call aegis_file_state and pass
  its current sha256 as expected_hash.
- Never route around an AEGIS refusal through a different tool.
- Never request, read, type, or expose passwords, OTPs, payment data, API keys,
  Keychain values, or other credentials.
- Do not delete files. Preserve unrelated user changes and show a concise diff
  and test result after code changes.
- Revoke the Working Envelope when the authorized task is complete.

Explain intended high-impact actions before asking the user to authorize them.
Use Thai when the user writes in Thai.
"""


class ResponsesAPIError(RuntimeError):
    """A concise, credential-free error returned by the Responses API."""


def _approval_requests(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in response.get("output", [])
        if isinstance(item, dict) and item.get("type") == "mcp_approval_request"
    ]


def _output_text(response: dict[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return "\n".join(parts)


def _display_arguments(raw: Any) -> str:
    if not isinstance(raw, str):
        return json.dumps(raw, ensure_ascii=False, indent=2)
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return raw


class ResponsesTunnelChat:
    """Small stateful client with an explicit approval loop for every MCP call."""

    def __init__(
        self,
        *,
        api_key: str,
        tunnel_id: str,
        model: str = DEFAULT_MODEL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        opener: Callable[..., Any] | None = None,
        approval_prompt: Callable[[str], str] = input,
        output: Callable[[str], None] = print,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is required")
        if not tunnel_id.startswith("tunnel_"):
            raise ValueError("OPENAI_TUNNEL_ID must begin with tunnel_")
        if not model.strip():
            raise ValueError("OPENAI_MODEL cannot be empty")
        self._api_key = api_key
        self._tunnel_id = tunnel_id
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._opener = opener or urllib.request.urlopen
        self._approval_prompt = approval_prompt
        self._output = output
        self.previous_response_id: str | None = None
        self.last_turn_usage: dict[str, int] = {}

    def reset(self) -> None:
        self.previous_response_id = None
        self.last_turn_usage = {}

    def usage_summary(self) -> str:
        if not self.last_turn_usage:
            return ""
        return (
            "API usage: "
            f"input {self.last_turn_usage.get('input_tokens', 0):,}, "
            f"output {self.last_turn_usage.get('output_tokens', 0):,}, "
            f"total {self.last_turn_usage.get('total_tokens', 0):,} tokens"
        )

    def _base_payload(self) -> dict[str, Any]:
        return {
            "model": self._model,
            "instructions": AGENT_INSTRUCTIONS,
            "store": True,
            "tools": [
                {
                    "type": "mcp",
                    "server_label": "endeavor_hands",
                    "server_description": (
                        "AEGIS-protected local Mac file, process, Git, and computer tools"
                    ),
                    "tunnel_id": self._tunnel_id,
                    "require_approval": "always",
                }
            ],
        }

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            RESPONSES_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body).get("error", {}).get("message", body)
            except json.JSONDecodeError:
                detail = body
            raise ResponsesAPIError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ResponsesAPIError(f"Could not reach OpenAI API: {exc.reason}") from exc

        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ResponsesAPIError("OpenAI API returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ResponsesAPIError("OpenAI API returned an unexpected response")
        return decoded

    def _approval_responses(
        self, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        decisions: list[dict[str, Any]] = []
        for request in requests:
            request_id = request.get("id")
            if not isinstance(request_id, str) or not request_id:
                raise ResponsesAPIError("MCP approval request is missing its ID")
            tool_name = str(request.get("name", "unknown_tool"))
            self._output(f"\nMCP tool requests approval: {tool_name}")
            self._output(_display_arguments(request.get("arguments", "{}")))
            answer = self._approval_prompt("Approve this tool call? [y/N]: ")
            approve = answer.strip().lower() in {"y", "yes"}
            decisions.append(
                {
                    "type": "mcp_approval_response",
                    "approval_request_id": request_id,
                    "approve": approve,
                }
            )
            self._output("Approved." if approve else "Denied.")
        return decisions

    def send(self, user_text: str) -> str:
        if not user_text.strip():
            return ""
        turn_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        payload = self._base_payload()
        payload["input"] = user_text
        if self.previous_response_id:
            payload["previous_response_id"] = self.previous_response_id

        while True:
            response = self._request(payload)
            usage = response.get("usage")
            if isinstance(usage, dict):
                for key in turn_usage:
                    value = usage.get(key)
                    if isinstance(value, int):
                        turn_usage[key] += value
            response_id = response.get("id")
            if not isinstance(response_id, str) or not response_id:
                raise ResponsesAPIError("OpenAI API response is missing its ID")

            approvals = _approval_requests(response)
            if not approvals:
                self.previous_response_id = response_id
                self.last_turn_usage = turn_usage
                return _output_text(response)

            payload = self._base_payload()
            payload["previous_response_id"] = response_id
            payload["input"] = self._approval_responses(approvals)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chat with an OpenAI model that can use Endeavor Hands through a tunnel."
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        help=f"Responses API model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--once",
        metavar="PROMPT",
        help="send one prompt and exit instead of starting an interactive chat",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        chat = ResponsesTunnelChat(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            tunnel_id=os.getenv("OPENAI_TUNNEL_ID", ""),
            model=args.model,
        )
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.once:
        try:
            answer = chat.send(args.once)
        except ResponsesAPIError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if answer:
            print(answer)
        if summary := chat.usage_summary():
            print(summary)
        return 0

    print(f"Endeavor Hands API chat ({args.model})")
    print("Commands: /new starts a fresh conversation, /quit exits.")
    print("Authorize an exact absolute root and task before asking for Mac changes.\n")
    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0
        if not user_text:
            continue
        if user_text.lower() in {"/quit", "/exit"}:
            print("Bye.")
            return 0
        if user_text.lower() == "/new":
            chat.reset()
            print("Started a fresh conversation.\n")
            continue
        try:
            answer = chat.send(user_text)
        except ResponsesAPIError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue
        print(f"\nAssistant: {answer or '[No text response]'}\n")
        if summary := chat.usage_summary():
            print(f"{summary}\n")


if __name__ == "__main__":
    raise SystemExit(main())
