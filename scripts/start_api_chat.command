#!/bin/zsh
# Double-click to chat through the OpenAI Responses API and Secure MCP Tunnel.
# Secrets and the machine-specific Tunnel ID are stored in macOS Keychain.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
CLIENT_PATH="$PROJECT_DIR/client/api_chat.py"
STATUS_URL="http://127.0.0.1:8765"
API_KEY_SERVICE="endeavor-openai-responses-api-key"
TUNNEL_ID_SERVICE="endeavor-openai-tunnel-id"

[[ -x "$PYTHON_BIN" ]] || {
  print -u2 "Missing Python environment. Run install_library/install.sh first."
  exit 1
}

if ! /usr/bin/curl --fail --silent --max-time 2 "$STATUS_URL/readyz" >/dev/null; then
  print -u2 "The Secure MCP Tunnel is not ready."
  print -u2 "Open scripts/start_tunnel.command first, then run this launcher again."
  exit 1
fi

if ! OPENAI_API_KEY=$(/usr/bin/security find-generic-password \
  -a "$USER" -s "$API_KEY_SERVICE" -w 2>/dev/null); then
  print "No Responses API key is stored in Keychain yet."
  read -r -s "OPENAI_API_KEY?Paste OpenAI API key (hidden): "
  print
  [[ -n "$OPENAI_API_KEY" ]] || {
    print -u2 "An OpenAI API key is required."
    exit 1
  }
  /usr/bin/security add-generic-password -U \
    -a "$USER" -s "$API_KEY_SERVICE" -w "$OPENAI_API_KEY"
  print "Responses API key saved in Keychain."
fi

if ! OPENAI_TUNNEL_ID=$(/usr/bin/security find-generic-password \
  -a "$USER" -s "$TUNNEL_ID_SERVICE" -w 2>/dev/null); then
  read -r "OPENAI_TUNNEL_ID?Tunnel ID (tunnel_...): "
  [[ "$OPENAI_TUNNEL_ID" == tunnel_* ]] || {
    print -u2 "Tunnel ID must begin with tunnel_."
    exit 1
  }
  /usr/bin/security add-generic-password -U \
    -a "$USER" -s "$TUNNEL_ID_SERVICE" -w "$OPENAI_TUNNEL_ID"
  print "Tunnel ID saved in Keychain."
fi

export OPENAI_API_KEY OPENAI_TUNNEL_ID
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-5.6}"

exec "$PYTHON_BIN" "$CLIENT_PATH" --model "$OPENAI_MODEL"
