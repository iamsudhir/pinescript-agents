#!/usr/bin/env bash
# One-shot dev environment setup for pinescript-agents.
# Creates a Python venv for the video tools and installs the docs MCP server.
# Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; exit 1; }

echo "Checking prerequisites"
command -v python3 >/dev/null || fail "python3 not found (need 3.9+)"
ok "python3 $(python3 -c 'import platform; print(platform.python_version())')"
command -v node >/dev/null || fail "node not found (need 18+)"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 18 ? 1 : 0)' || fail "node $(node -v) is too old (need 18+)"
ok "node $(node -v)"
if command -v ffmpeg >/dev/null; then ok "ffmpeg (Whisper fallback available)"; else warn "ffmpeg missing: only needed for --whisper transcription"; fi
if command -v claude >/dev/null; then ok "claude CLI"; else warn "claude CLI missing: install from https://claude.ai/code"; fi

echo "Python tools (.venv)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
ok "yt-dlp + youtube-transcript-api installed"

echo "Pine Script docs MCP server (docs/server)"
npm --prefix docs/server ci --silent --no-audit --no-fund
ok "node modules installed"
npm --prefix docs/server test --silent >/dev/null 2>&1 && ok "server tests pass" || warn "server tests failed: run 'npm --prefix docs/server test'"

echo
echo "Done. Next:"
echo "  source .venv/bin/activate        # for tools/*.py"
echo "  claude                           # open the assistant; approve the 'pinescript' MCP server"
echo "  then type: start"
