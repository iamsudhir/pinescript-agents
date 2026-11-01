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
# Find a real Python 3.9+. On Windows, "python3"/"python" may be Microsoft Store
# stubs that exist on PATH but fail when run, so actually execute each candidate.
PY=""
for cand in python3 python "py -3"; do
  if $cand -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -n "$PY" ] || fail "Python 3.9+ not found. Windows: 'winget install Python.Python.3.12', then turn off the python/python3 App execution aliases in Settings and open a new terminal"
ok "python $($PY -c 'import platform; print(platform.python_version())') ($PY)"
command -v node >/dev/null || fail "node not found (need 18+)"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 18 ? 1 : 0)' || fail "node $(node -v) is too old (need 18+)"
ok "node $(node -v)"
if command -v ffmpeg >/dev/null; then ok "ffmpeg (Whisper fallback available)"; else warn "ffmpeg missing: only needed for --whisper transcription"; fi
if command -v claude >/dev/null; then ok "claude CLI"; else warn "claude CLI missing: install from https://claude.ai/code"; fi

echo "Python tools (.venv)"
[ -d .venv ] || $PY -m venv .venv
if [ -x .venv/Scripts/python.exe ]; then VPY=.venv/Scripts/python.exe; ACTIVATE=".venv/Scripts/activate"
else VPY=.venv/bin/python; ACTIVATE=".venv/bin/activate"; fi
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r requirements.txt
ok "yt-dlp + youtube-transcript-api installed"

echo "Pine Script docs MCP server (docs/server)"
npm --prefix docs/server ci --silent --no-audit --no-fund
ok "node modules installed"
npm --prefix docs/server test --silent >/dev/null 2>&1 && ok "server tests pass" || warn "server tests failed: run 'npm --prefix docs/server test'"

echo
echo "Done. Next:"
echo "  source $ACTIVATE   # for tools/*.py"
echo "  claude                           # open the assistant; approve the 'pinescript' MCP server"
echo "  then type: start"
